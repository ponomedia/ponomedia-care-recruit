#!/usr/bin/env python3
"""
approver_server.py — スマホ承認サーバー

起動方法:
    python approver_server.py

スマホからのアクセス:
    http://192.168.1.13:5050  （同じWiFi内）

フロー:
    1. run_pipeline.py --queue-mode でキューファイルに保存
    2. このサーバーを起動
    3. スマホで http://[PCのIP]:5050 にアクセス
    4. 施設ごとに「承認」「却下」ボタンをタップ
    5. 承認 → その場でメール/フォーム送信
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request

load_dotenv()

# パスをautomationディレクトリに固定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import config
from email_sender import GmailSender
from form_submitter import FormSubmitter
from researcher import FacilityResearcher
from sales_guard import SalesGuard
from sent_log import already_sent, domain_already_sent, daily_limit_reached, record_sent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _normalize_url_simple(url: str) -> str:
    """URLを正規化（スキーム・末尾スラッシュを除去して比較用に統一）"""
    url = (url or "").lower().strip().rstrip("/")
    url = url.replace("https://", "").replace("http://", "").replace("www.", "")
    return url


def reconcile_queue_with_sent_log():
    """
    sent_log.json とキューを突き合わせ、乖離を修正する。

    ① processing のまま残っているアイテムをリセット
       - sent_log に記録あり → duplicate（送信済み扱い）
       - sent_log に記録なし → pending に戻す（再承認可能）
    ② pending/needs_review なのに sent_log に記録あり → duplicate
    ③ sent なのに sent_log に未記録（sent_log_failed フラグあり）→ sent_log に追記
    ④ sent_emergency.txt が残っていれば sent_log に取り込んで削除
    """
    from sent_log import _load as _load_sent, record_sent

    queue = load_queue()
    sent_records = _load_sent()

    sent_urls   = {_normalize_url_simple(r.get("url", ""))  for r in sent_records}
    sent_emails = {(r.get("email") or "").lower()            for r in sent_records if r.get("email")}
    sent_names  = {(r.get("facility_name") or "").strip()    for r in sent_records if r.get("facility_name")}

    changed = False

    # ④ 緊急ログ（sent_emergency.txt）を sent_log に取り込む
    emergency_path = os.path.join(BASE_DIR, "output", "sent_emergency.txt")
    if os.path.exists(emergency_path):
        try:
            with open(emergency_path, "r", encoding="utf-8") as ef:
                lines = ef.readlines()
            for line in lines:
                parts = line.strip().split("\t")
                if len(parts) >= 4:
                    ts, name_e, url_e, email_e = parts[0], parts[1], parts[2], parts[3]
                    method_e = parts[4] if len(parts) > 4 else "不明"
                    norm_url = _normalize_url_simple(url_e)
                    if norm_url not in sent_urls:
                        logger.warning(f"[reconcile] 緊急ログ取り込み: {name_e}")
                        record_sent(
                            facility_name=name_e,
                            url=url_e,
                            email=email_e,
                            method=method_e,
                        )
                        sent_urls.add(norm_url)
                        sent_names.add(name_e.strip())
            os.remove(emergency_path)
            logger.info(f"[reconcile] sent_emergency.txt を取り込み・削除しました ({len(lines)}件)")
        except Exception as e:
            logger.warning(f"[reconcile] 緊急ログ取り込みエラー: {e}")

    for item in queue:
        status = item.get("status", "")
        name   = (item.get("facility_name") or "").strip()
        url    = _normalize_url_simple(item.get("url", ""))
        email  = (item.get("contact_email") or "").lower()

        def _is_in_sent_log():
            return (
                (url   and url   in sent_urls)  or
                (email and email in sent_emails) or
                (name  and name  in sent_names)
            )

        # ① processing のまま残っている（クラッシュで中断）
        if status == "processing":
            if _is_in_sent_log():
                # 実際には送信済みだった → duplicate
                logger.info(f"[reconcile] processing→duplicate（sent_logに記録あり）: {name}")
                item["status"] = "duplicate"
            else:
                # 送信されていない → pending に戻して再承認可能にする
                logger.info(f"[reconcile] processing→pending（sent_logに記録なし）: {name}")
                item["status"] = "pending"
                item.pop("sent_at", None)
            changed = True

        # ② pending/needs_review なのに sent_log に記録あり → duplicate
        elif status in ("pending", "needs_review"):
            if _is_in_sent_log():
                logger.info(f"[reconcile] {status}→duplicate（sent_logと不一致）: {name}")
                item["status"] = "duplicate"
                item["sent_at"] = item.get("sent_at", datetime.now().isoformat())
                changed = True

        # ③ sent なのに sent_log に未記録 → sent_log に追記
        elif status == "sent":
            if url and url not in sent_urls:
                logger.warning(f"[reconcile] sent→sent_logへ追記（ログ漏れ検出）: {name}")
                try:
                    record_sent(
                        facility_name=name,
                        url=item.get("url", ""),
                        email=item.get("contact_email", ""),
                        method=item.get("contact_method", "不明"),
                    )
                    sent_urls.add(url)
                    sent_names.add(name)
                    item.pop("sent_log_failed", None)  # フラグ解除
                    changed = True
                except Exception as e:
                    logger.error(f"[reconcile] sent_log追記失敗: {name} / {e}")

    if changed:
        save_queue(queue)
        logger.info("[reconcile] キューを更新しました")

QUEUE_FILE = os.path.join(BASE_DIR, "output", "approval_queue.json")

# キューのpending件数がこれを下回ったら自動補充する
REPLENISH_THRESHOLD = 20
# 1回の補充で追加する最大件数
REPLENISH_COUNT = 100

_replenishing = False  # 補充中フラグ（二重起動防止）


# =========================================================
# キューの読み書き
# =========================================================

def load_queue() -> list:
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_queue(items: list):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# =========================================================
# モジュール初期化
# =========================================================

_sender = None
_form_submitter = None
_processing_ids: set = set()  # 現在処理中のitem_id（二重タップ防止）
_researcher = None


def get_sender():
    global _sender
    if _sender is None and config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD:
        _sender = GmailSender(
            gmail_address=config.GMAIL_ADDRESS,
            app_password=config.GMAIL_APP_PASSWORD,
            sender_name=config.SENDER_NAME,
        )
    return _sender


def get_form_submitter():
    global _form_submitter
    if _form_submitter is None:
        _form_submitter = FormSubmitter(
            sales_guard=SalesGuard(),
            wait_seconds=config.WAIT_BETWEEN_REQUESTS,
        )
    return _form_submitter


def get_researcher():
    global _researcher
    if _researcher is None:
        _researcher = FacilityResearcher()
    return _researcher


def trigger_replenish_if_needed():
    """pending件数が閾値を下回ったらバックグラウンドでパイプラインを起動する"""
    global _replenishing
    if _replenishing:
        return
    queue = load_queue()
    pending = sum(1 for i in queue if i.get("status") in ("pending", "needs_review"))
    if pending < REPLENISH_THRESHOLD:
        _replenishing = True
        logger.info(f"[補充] pending={pending}件 → パイプライン自動起動 ({REPLENISH_COUNT}件追加)")
        pipeline_path = os.path.join(BASE_DIR, "run_pipeline.py")
        log_path = os.path.join(BASE_DIR, "output", "replenish.log")
        with open(log_path, "a", encoding="utf-8") as log_f:
            subprocess.Popen(
                [sys.executable, pipeline_path,
                 "--queue-mode", f"--max-facilities={REPLENISH_COUNT}"],
                stdout=log_f,
                stderr=log_f,
                cwd=BASE_DIR,
            )
        logger.info(f"[補充] パイプライン起動完了 (ログ: {log_path})")


# =========================================================
# HTML テンプレート（モバイルファースト）
# =========================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>営業承認 — PonoMedia</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif;
         background: #f0f4f8; color: #1a202c; }

  .header {
    background: #2b6cb0; color: white; padding: 16px 20px;
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; justify-content: space-between;
  }
  .header h1 { font-size: 18px; }
  .badge {
    background: #fc8181; color: white; border-radius: 999px;
    padding: 2px 10px; font-size: 14px; font-weight: bold;
  }

  .empty { text-align: center; padding: 60px 20px; color: #718096; font-size: 16px; }

  .card {
    background: white; margin: 12px 16px; border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden;
    transition: opacity 0.3s;
  }
  .card.done { opacity: 0.4; pointer-events: none; }
  .card.done-card {
    opacity: 0.35;
    background: #f0f4f8;
    pointer-events: none;
    user-select: none;
  }

  .card-header {
    padding: 14px 16px 10px;
    border-bottom: 1px solid #e2e8f0;
  }
  .facility-name { font-size: 17px; font-weight: bold; margin-bottom: 4px; }
  .meta { font-size: 13px; color: #718096; }

  .rank-a { border-left: 5px solid #f56565; }
  .rank-b { border-left: 5px solid #ed8936; }

  .score-bar { background: #e2e8f0; height: 6px; border-radius: 3px; margin: 8px 0 4px; }
  .score-fill { height: 6px; border-radius: 3px; background: #f56565; }

  .email-preview {
    padding: 10px 16px; font-size: 13px; color: #4a5568;
    background: #f7fafc; border-top: 1px solid #e2e8f0;
    white-space: pre-wrap; max-height: 160px; overflow-y: auto;
    line-height: 1.5;
  }

  .weaknesses {
    padding: 8px 16px; font-size: 13px;
  }
  .tag {
    display: inline-block; background: #fff5f5; color: #c53030;
    border: 1px solid #fed7d7; border-radius: 4px;
    padding: 2px 8px; margin: 2px 2px; font-size: 12px;
  }

  .url-row {
    padding: 6px 16px; font-size: 12px; color: #3182ce;
    word-break: break-all;
  }

  .actions {
    display: flex; gap: 0; border-top: 1px solid #e2e8f0;
  }
  .btn {
    flex: 1; padding: 16px; font-size: 16px; font-weight: bold;
    border: none; cursor: pointer; transition: background 0.15s;
  }
  .btn-approve {
    background: #48bb78; color: white;
  }
  .btn-approve:active { background: #38a169; }
  .btn-reject {
    background: #f7fafc; color: #718096;
    border-left: 1px solid #e2e8f0;
  }
  .btn-reject:active { background: #e2e8f0; }

  .status-sent { text-align: center; padding: 12px; color: #38a169; font-weight: bold; font-size: 14px; }
  .status-rejected { text-align: center; padding: 12px; color: #a0aec0; font-size: 14px; }
  .status-error { text-align: center; padding: 12px; color: #e53e3e; font-size: 14px; }
  .sent-badge {
    display: inline-block; background: #c6f6d5; color: #276749;
    border: 1px solid #9ae6b4; border-radius: 4px;
    padding: 3px 10px; font-size: 12px; font-weight: bold; margin-left: 8px;
  }
  .rejected-badge {
    display: inline-block; background: #e2e8f0; color: #718096;
    border: 1px solid #cbd5e0; border-radius: 4px;
    padding: 3px 10px; font-size: 12px; font-weight: bold; margin-left: 8px;
  }
  .section-divider {
    text-align: center; padding: 12px 20px; color: #a0aec0;
    font-size: 13px; border-top: 1px solid #e2e8f0; margin-top: 8px;
  }
  .review-banner { background: #fffbeb; border: 1px solid #f6e05e; color: #744210;
    padding: 8px 16px; font-size: 13px; font-weight: bold; }

  .footer { text-align: center; padding: 30px 20px; color: #a0aec0; font-size: 13px; }
</style>
</head>
<body>

<div class="header">
  <h1>📋 営業承認</h1>
  <span class="badge" id="pending-count">{{ pending_count }}件待機</span>
</div>

{% if items %}
  {% for item in items %}
  <div class="card rank-{{ item.rank | lower }}" id="card-{{ item.id }}">
    <div class="card-header">
      <div class="facility-name">{{ item.facility_name }}</div>
      <div class="meta">
        {{ item.area }} / {{ item.facility_type }} &nbsp;|&nbsp;
        <strong style="color:{% if item.rank=='A' %}#e53e3e{% else %}#dd6b20{% endif %}">
          ランク{{ item.rank }}
        </strong> &nbsp;{{ item.score }}点/100点
      </div>
      <div class="score-bar">
        <div class="score-fill" style="width:{{ item.score }}%; background:{% if item.score < 40 %}#f56565{% else %}#ed8936{% endif %};"></div>
      </div>
    </div>

    {% if item.status == 'needs_review' %}
    <div class="review-banner">⚠️ 要確認URL：このURLが本当に施設の公式サイトか確認してから承認してください</div>
    {% endif %}

    <div class="weaknesses">
      {% for w in item.weaknesses %}
        <span class="tag">{{ w }}</span>
      {% endfor %}
    </div>

    <div style="padding:8px 16px;">
      <a href="/visit/{{ item.id }}" style="display:block;background:#ebf8ff;border:1px solid #bee3f8;border-radius:8px;padding:12px 14px;color:#2b6cb0;font-size:13px;word-break:break-all;text-decoration:none;-webkit-tap-highlight-color:rgba(0,0,0,0.1);position:relative;z-index:1;">🔗 サイトを確認する<br><span style="font-size:11px;color:#4a90d9;">{{ item.url }}</span></a>
    </div>

    <div class="email-preview">{{ item.email_body }}</div>

    <div id="actions-{{ item.id }}" class="actions">
      <button class="btn btn-approve" onclick="approve('{{ item.id }}')">✅ 承認して送信</button>
      <button class="btn btn-reject" onclick="reject('{{ item.id }}')">✗ 却下</button>
    </div>
    <div id="result-{{ item.id }}" style="display:none;"></div>
  </div>
  {% endfor %}
{% else %}
  <div class="empty">
    <div style="font-size:48px;margin-bottom:16px;">📭</div>
    <div>承認待ちの施設はありません</div>
    <div style="font-size:13px;margin-top:8px;color:#a0aec0;">
      run_pipeline.py --queue-mode を実行してください
    </div>
  </div>
{% endif %}

{% if done_items %}
  <div class="section-divider">── 送信済み・却下済み（{{ done_items | length }}件） ──</div>
  {% for item in done_items %}
  <div class="card done-card" id="card-{{ item.id }}">
    <div class="card-header">
      <div class="facility-name">
        {{ item.facility_name }}
        {% if item.status == 'sent' %}
          <span class="sent-badge">✓ 送信済み{% if item.contact_method %} ({{ item.contact_method }}){% endif %}</span>
        {% elif item.status == 'rejected' %}
          <span class="rejected-badge">✗ 却下済み</span>
        {% elif item.status == 'blocked' %}
          <span class="rejected-badge">⛔ ブロック</span>
        {% elif item.status == 'duplicate' %}
          <span class="rejected-badge">重複</span>
        {% endif %}
      </div>
      <div class="meta">
        {{ item.area }} / {{ item.facility_type }} &nbsp;|&nbsp;
        ランク{{ item.rank }} &nbsp;{{ item.score }}点/100点
        {% if item.sent_at %}
          &nbsp;— {{ item.sent_at[:16] | replace('T', ' ') }}
        {% elif item.rejected_at %}
          &nbsp;— {{ item.rejected_at[:16] | replace('T', ' ') }}
        {% endif %}
      </div>
    </div>
    <div style="padding:8px 16px;font-size:12px;color:#a0aec0;word-break:break-all;">{{ item.url }}</div>
  </div>
  {% endfor %}
{% endif %}

<div class="footer">PonoMedia 介護採用支援</div>

<script>
let pendingCount = {{ pending_count }};

function approve(id) {
  const btn = document.querySelector(`#actions-${id}`);
  btn.style.opacity = '0.5';
  btn.style.pointerEvents = 'none';

  fetch(`/approve/${id}`, {method: 'POST'})
    .then(r => r.json())
    .then(data => {
      btn.style.display = 'none';
      const result = document.getElementById(`result-${id}`);
      result.style.display = 'block';
      if (data.success) {
        result.innerHTML = `<div class="status-sent">✅ 送信完了（${data.method}）</div>`;
        document.getElementById(`card-${id}`).classList.add('done');
        pendingCount--;
        document.getElementById('pending-count').textContent = pendingCount + '件待機';
      } else {
        result.innerHTML = `<div class="status-error">⚠️ 送信失敗: ${data.reason}</div>`;
        btn.style.opacity = '';
        btn.style.pointerEvents = '';
      }
    })
    .catch(() => {
      btn.style.opacity = '';
      btn.style.pointerEvents = '';
    });
}

function reject(id) {
  fetch(`/reject/${id}`, {method: 'POST'})
    .then(r => r.json())
    .then(() => {
      document.getElementById(`actions-${id}`).style.display = 'none';
      const result = document.getElementById(`result-${id}`);
      result.style.display = 'block';
      result.innerHTML = '<div class="status-rejected">却下しました</div>';
      document.getElementById(`card-${id}`).classList.add('done');
      pendingCount--;
      document.getElementById('pending-count').textContent = pendingCount + '件待機';
    });
}
</script>
</body>
</html>
"""


# =========================================================
# ルート
# =========================================================

@app.route("/")
def index():
    queue = load_queue()
    items = [i for i in queue if i.get("status") in ("pending", "needs_review", "processing")]
    # 送信済み・却下済みは最新50件のみ表示（古いものは省略）
    done_statuses = ("sent", "rejected", "blocked", "duplicate")
    done_items = [i for i in queue if i.get("status") in done_statuses][-50:]
    done_items = list(reversed(done_items))  # 新しいものを上に
    return render_template_string(
        HTML_TEMPLATE,
        items=items,
        done_items=done_items,
        pending_count=len(items),
    )


@app.route("/approve/<item_id>", methods=["POST"])
def approve(item_id):
    queue = load_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    if not item:
        return jsonify({"success": False, "reason": "not found"})

    # ★ 二重タップ防止（同じIDが処理中なら即リターン）
    if item_id in _processing_ids:
        return jsonify({"success": False, "reason": "処理中です。しばらくお待ちください"})
    _processing_ids.add(item_id)

    try:
        return _do_approve(item_id, item, queue)
    finally:
        _processing_ids.discard(item_id)


def _codex_sales_guard_check(facility_name: str, url: str, facility_data: dict) -> bool:
    """
    CODEXを使って、サイトに「営業お断り」「勧誘禁止」等の文言があるか独立検証する。
    True  → 営業禁止と判定（送信をブロック）
    False → セーフ（送信続行可）
    """
    fd = facility_data or {}
    text_preview = fd.get("full_text", "")[:600]
    title = fd.get("title", "")
    meta = fd.get("meta_description", "")

    prompt = (
        f"以下のウェブサイト情報を確認し、このサイトに「営業お断り」「勧誘禁止」「セールスお断り」"
        f"「営業電話・メール不可」「広告・宣伝お断り」などの営業禁止を示す文言があるかどうか判定してください。\n\n"
        f"施設名: {facility_name}\n"
        f"URL: {url}\n"
        f"ページタイトル: {title}\n"
        f"メタ説明: {meta}\n"
        f"本文冒頭: {text_preview}\n\n"
        f"以下のいずれか1語のみで答えてください:\n"
        f"PROHIBITED — 営業禁止の文言が確認できる\n"
        f"SAFE       — 営業禁止の文言はない\n"
        f"UNCLEAR    — 判断できない（テキスト不足等）"
    )

    try:
        result = subprocess.run(
            [
                "codex", "exec",
                "-c", 'sandbox_permissions=["disk-full-read-access"]',
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout + result.stderr).upper()
        logger.info(f"[CODEX営業禁止チェック] {facility_name}: {output[:80]}")

        if "PROHIBITED" in output:
            return True   # ブロック
        # SAFE / UNCLEAR / エラー → 送信続行（安全方向へ倒す）
        return False

    except subprocess.TimeoutExpired:
        logger.warning(f"[CODEX営業禁止] タイムアウト: {facility_name} — SAFEとして処理")
        return False
    except FileNotFoundError:
        logger.warning("[CODEX営業禁止] codexコマンド未インストール — SAFEとして処理")
        return False
    except Exception as e:
        logger.warning(f"[CODEX営業禁止] エラー: {e} — SAFEとして処理")
        return False


def _do_approve(item_id, item, queue):
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 送信前 全チェック（1つでも引っかかれば絶対に送信しない）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # [1] ステータス確認（pending/needs_review 以外は送らない）
    if item.get("status") not in ("pending", "needs_review"):
        logger.warning(f"[送信拒否] ステータス異常: {item['facility_name']} = '{item.get('status')}'")
        return jsonify({"success": False, "reason": f"ステータスが {item.get('status')} のため送信できません"})

    # [2] 施設名・メール本文の空チェック（不完全なデータは送らない）
    if not item.get("facility_name", "").strip():
        logger.warning("[送信拒否] 施設名が空です")
        return jsonify({"success": False, "reason": "施設名が空のため送信できません"})
    if not item.get("email_body", "").strip():
        logger.warning("[送信拒否] メール本文が空です")
        return jsonify({"success": False, "reason": "メール本文が空のため送信できません"})

    # [3] 行政・公的機関ブロック
    url = item.get("url", "")
    BLOCKED_DOMAINS = [".go.jp", ".lg.jp", ".ed.jp", "pref.", "city.", "mhlw", "mext"]
    if any(b in url.lower() for b in BLOCKED_DOMAINS):
        logger.warning(f"[送信拒否] 行政・公的機関URL: {url}")
        item["status"] = "blocked"
        save_queue(queue)
        return jsonify({"success": False, "reason": "行政・公的機関のため送信できません"})

    # [4] 大手チェーン・グループ施設ブロック（グループ全体への営業はNG）
    BLOCKED_CHAINS = [
        "sompocare", "cordially", "benesse", "watami", "comson",
        "nichiigakkan", "nichii", "secom", "alsok", "panasonic-es",
        "humanlife", "human-lifecare", "bestlife", "message-kk",
        "medics", "seiwa", "yamato-welfare",
    ]
    if any(c in url.lower() for c in BLOCKED_CHAINS):
        logger.warning(f"[送信拒否] 大手チェーン: {url}")
        item["status"] = "blocked"
        save_queue(queue)
        return jsonify({"success": False, "reason": "大手チェーン施設のため送信対象外です"})

    # [5] 1日の送信上限チェック
    if daily_limit_reached():
        return jsonify({"success": False, "reason": f"本日の送信上限({20}件)に達しました。明日以降に承認してください"})

    # [6] 処理開始を即座にファイルへ書き込む（再起動後の二重送信防止）
    item["status"] = "processing"
    save_queue(queue)

    # [7] 送信済みURL・メール・施設名の最終確認
    if already_sent(url=url, email=item.get("contact_email", ""), facility_name=item.get("facility_name", "")):
        item["status"] = "duplicate"
        save_queue(queue)
        logger.warning(f"[重複ブロック] {item['facility_name']} は送信済みです")
        return jsonify({"success": False, "reason": "この施設には既に送信済みです"})

    # [8] 同一ドメイン送信済みチェック（グループ施設への重複送信防止）
    if domain_already_sent(url=url):
        item["status"] = "duplicate"
        save_queue(queue)
        logger.warning(f"[ドメイン重複ブロック] {item['facility_name']} の同一ドメインへ送信済みです")
        return jsonify({"success": False, "reason": "同一ドメイン（グループ施設）に既に送信済みです"})

    # 送信実行
    sent = False
    method = "none"
    reason = ""

    researcher = get_researcher()
    form_sub = get_form_submitter()
    sender = get_sender()

    facility_data = researcher.scrape_facility(item["url"]) if item.get("url") else None

    # [9] CODEX 営業禁止二重チェック（Pass 1の正規表現に加えてCODEXで独立確認）
    if facility_data:
        if _codex_sales_guard_check(item.get("facility_name", ""), url, facility_data):
            logger.warning(f"[CODEX営業禁止] {item['facility_name']}: サイト上に営業お断り文言を検出 → ブロック")
            item["status"] = "blocked"
            save_queue(queue)
            return jsonify({"success": False, "reason": "CODEX確認: 営業禁止の文言がサイトに存在します"})

    # ──────────────────────────────────────────────
    # 送信ルート: フォーム優先 → フォームNGならメール
    # ★ フォーム送信成功後は絶対にメールを送らない（sent フラグで制御）
    # ★ ブロックされた場合も絶対にメールへフォールバックしない
    # ──────────────────────────────────────────────
    form_blocked = False  # 営業禁止によりブロックされたか

    # Step A: フォーム送信を試みる
    if facility_data:
        contact_form_url = form_sub.find_contact_form_url(facility_data)
        if contact_form_url:
            result = form_sub.submit_to_facility(
                facility_data=facility_data,
                contact_form_url=contact_form_url,
                message_subject=item["email_subject"],
                message_body=item["email_body"],
                sender_name=config.SENDER_NAME,
                sender_email=config.GMAIL_ADDRESS,
            )
            if result.get("blocked"):
                # 営業禁止 → メールへも絶対に送らない
                form_blocked = True
                item["status"] = "blocked"
                save_queue(queue)
                return jsonify({"success": False, "reason": "営業禁止サイト"})
            if result["success"]:
                sent = True
                method = "フォーム"

    # Step B: フォーム未送信 かつ ブロックなし の場合のみメール送信
    # ★ sent=True（フォーム成功）または form_blocked=True の場合は絶対にここに到達しない
    if not sent and not form_blocked and sender and item.get("contact_email"):
        ok = sender.send(
            to_email=item["contact_email"],
            subject=item["email_subject"],
            body=item["email_body"],
        )
        if ok:
            sent = True
            method = "メール"
        else:
            reason = "メール送信失敗"

    if not sent and not reason:
        reason = "フォームもメールも利用不可"

    # 送信成功時のみ永続ログに記録
    # ★ record_sent が失敗してもキューを "sent" にするが、log_failed フラグを立てる
    #    → 次回起動時の reconcile で sent_log への再取り込みを試みる
    log_failed = False
    if sent:
        try:
            record_sent(
                facility_name=item["facility_name"],
                url=item.get("url", ""),
                email=item.get("contact_email", ""),
                method=method,
            )
        except Exception as e:
            # sent_log への書き込み失敗 → 緊急バックアップ（追記テキスト）
            log_failed = True
            logger.critical(
                f"[CRITICAL] sent_log 書き込み失敗！送信済みなのに記録できていない: "
                f"{item['facility_name']} / {e}"
            )
            try:
                emergency_path = os.path.join(BASE_DIR, "output", "sent_emergency.txt")
                with open(emergency_path, "a", encoding="utf-8") as ef:
                    ef.write(
                        f"{datetime.now().isoformat()}\t"
                        f"{item.get('facility_name','')}\t"
                        f"{item.get('url','')}\t"
                        f"{item.get('contact_email','')}\t"
                        f"{method}\n"
                    )
                logger.warning(f"[緊急ログ] {emergency_path} に記録しました")
            except Exception as e2:
                logger.critical(f"[CRITICAL] 緊急ログへの書き込みも失敗: {e2}")

    # キュー更新
    item["status"] = "sent" if sent else "failed"
    item["sent_at"] = datetime.now().isoformat()
    item["contact_method"] = method
    if log_failed:
        item["sent_log_failed"] = True  # reconcile で再取り込みするフラグ
    save_queue(queue)

    logger.info(f"[承認] {item['facility_name']} → {method if sent else '失敗: ' + reason}")
    trigger_replenish_if_needed()
    return jsonify({"success": sent, "method": method, "reason": reason})


@app.route("/visit/<item_id>")
def visit(item_id):
    queue = load_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    if item and item.get("url"):
        return redirect(item["url"])
    return "URL not found", 404


@app.route("/reject/<item_id>", methods=["POST"])
def reject(item_id):
    queue = load_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    if item:
        item["status"] = "rejected"
        item["rejected_at"] = datetime.now().isoformat()
        save_queue(queue)
        logger.info(f"[却下] {item.get('facility_name', item_id)}")
    trigger_replenish_if_needed()
    return jsonify({"success": True})


@app.route("/status")
def status():
    global _replenishing
    queue = load_queue()
    pending = sum(1 for i in queue if i["status"] in ("pending", "needs_review", "processing"))
    # 補充後にpendingが閾値を超えたらフラグリセット
    if _replenishing and pending >= REPLENISH_THRESHOLD:
        _replenishing = False
        logger.info(f"[補充] 完了 — pending={pending}件")
    return jsonify({
        "pending": pending,
        "sent": sum(1 for i in queue if i["status"] == "sent"),
        "rejected": sum(1 for i in queue if i["status"] == "rejected"),
        "needs_review": sum(1 for i in queue if i["status"] == "needs_review"),
        "replenishing": _replenishing,
        "total": len(queue),
    })


# =========================================================
# エントリーポイント
# =========================================================

if __name__ == "__main__":
    import socket
    from waitress import serve

    # ローカルIPを取得して表示
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    print("=" * 50)
    print("PonoMedia 営業承認サーバー 起動中")
    print("=" * 50)
    print(f"  PC:     http://localhost:5050")
    print(f"  スマホ: http://{local_ip}:5050")
    print("  ※同じWiFiに接続してください")
    print("  終了: Ctrl+C")
    print("=" * 50)

    # 起動時にキューと sent_log を突き合わせて乖離を修正
    try:
        reconcile_queue_with_sent_log()
        logger.info("[起動] sent_log との reconcile 完了")
    except Exception as e:
        logger.warning(f"[起動] reconcile スキップ（エラー）: {e}")

    # waitress: Flask開発サーバーより安定した本番用WSGIサーバー
    serve(app, host="0.0.0.0", port=5050, threads=4)
