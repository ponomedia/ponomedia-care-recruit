"""
auto_approver.py — 承認キューの自動処理スクリプト

output/approval_queue.json を読み込み、
  - status == "pending"  のアイテムを自動承認・送信する
  - status == "needs_review" は --force フラグ付きのときのみ処理する

送信方法の優先順位:
  1. フォーム送信 (FormSubmitter)
  2. メール送信 (GmailSender)
  3. どちらも不可の場合はスキップ（failed として記録）

実行例:
  python auto_approver.py
  python auto_approver.py --force
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import shutil
from datetime import datetime

# ---------------------------------------------------------------------------
# パス設定（このファイルのディレクトリを基準にする）
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(BASE_DIR, "output", "approval_queue.json")
LOG_FILE = os.path.join(BASE_DIR, "output", "auto_approver.log")

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------
os.makedirs(os.path.join(BASE_DIR, "output"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("auto_approver")


# ---------------------------------------------------------------------------
# モジュールインポート
# ---------------------------------------------------------------------------
def _import_modules():
    """automation ディレクトリ内の既存モジュールを遅延インポートする。"""
    sys.path.insert(0, BASE_DIR)
    try:
        from form_submitter import FormSubmitter
    except ImportError as e:
        logger.warning(f"form_submitter をインポートできませんでした: {e}")
        FormSubmitter = None

    try:
        from email_sender import GmailSender
    except ImportError as e:
        logger.warning(f"email_sender をインポートできませんでした: {e}")
        GmailSender = None

    try:
        from sales_guard import SalesGuard
    except ImportError as e:
        logger.warning(f"sales_guard をインポートできませんでした: {e}")
        SalesGuard = None

    try:
        from sent_log import record_sent, already_sent, daily_limit_reached
    except ImportError as e:
        logger.error(f"sent_log をインポートできませんでした（必須）: {e}")
        sys.exit(1)

    try:
        import config
    except ImportError as e:
        logger.warning(f"config をインポートできませんでした: {e}")
        config = None

    return FormSubmitter, GmailSender, SalesGuard, record_sent, already_sent, daily_limit_reached, config


# ---------------------------------------------------------------------------
# キューファイルの読み書き
# ---------------------------------------------------------------------------
def load_queue() -> list:
    """approval_queue.json を読み込む。ファイルがなければ空リストを返す。"""
    if not os.path.exists(QUEUE_FILE):
        logger.warning(f"キューファイルが見つかりません: {QUEUE_FILE}")
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.error("approval_queue.json の形式が不正です（リストを期待）")
        return []
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"approval_queue.json の読み込みに失敗しました: {e}")
        return []


def save_queue(queue: list):
    """approval_queue.json を原子的に書き込む（クラッシュ対策）。"""
    dir_path = os.path.dirname(QUEUE_FILE)
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, QUEUE_FILE)
        logger.debug(f"キューファイルを保存しました: {QUEUE_FILE}")
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.error(f"キューファイルの保存に失敗しました: {e}")
        raise


# ---------------------------------------------------------------------------
# 送信処理
# ---------------------------------------------------------------------------
def try_form_submit(item: dict, FormSubmitter, SalesGuard) -> bool:
    """
    フォーム送信を試みる。
    Returns:
        True  — 送信成功
        False — 送信失敗またはスキップ
    """
    if FormSubmitter is None:
        return False

    url = item.get("url", "")
    if not url:
        logger.info(f"[フォーム] URLなし → スキップ: {item.get('facility_name')}")
        return False

    # SalesGuard チェック
    if SalesGuard is not None:
        guard = SalesGuard()
        try:
            import requests
            resp = requests.get(url, timeout=10, verify=False)
            if guard.is_prohibited(resp.text, url):
                logger.warning(f"[フォーム] SalesGuard ブロック: {url}")
                return False
        except Exception as e:
            logger.warning(f"[フォーム] SalesGuard チェック中にエラー（スキップして続行）: {e}")

    try:
        facility_data = {
            "name": item.get("facility_name", ""),
            "url": url,
            "all_links": [],
            "email_subject": item.get("email_subject", ""),
            "email_body": item.get("email_body", ""),
        }
        submitter = FormSubmitter()
        result = submitter.submit(facility_data)
        if result:
            logger.info(f"[フォーム] 送信成功: {item.get('facility_name')} ({url})")
            return True
        else:
            logger.info(f"[フォーム] 送信失敗（フォームが見つからないか入力不可）: {url}")
            return False
    except Exception as e:
        logger.warning(f"[フォーム] 例外発生: {e}")
        return False


def try_email_send(item: dict, GmailSender, config) -> bool:
    """
    メール送信を試みる。
    Returns:
        True  — 送信成功
        False — 送信失敗またはスキップ
    """
    if GmailSender is None:
        return False

    contact_email = item.get("contact_email", "").strip()
    if not contact_email:
        logger.info(f"[メール] メールアドレスなし → スキップ: {item.get('facility_name')}")
        return False

    # config から認証情報を取得
    gmail_address = None
    app_password = None
    if config is not None:
        gmail_address = getattr(config, "GMAIL_ADDRESS", None)
        app_password = getattr(config, "GMAIL_APP_PASSWORD", None)

    # 環境変数でも上書き可能
    gmail_address = os.environ.get("GMAIL_ADDRESS", gmail_address)
    app_password  = os.environ.get("GMAIL_APP_PASSWORD", app_password)

    if not gmail_address or not app_password:
        logger.warning("[メール] Gmail認証情報が設定されていません（GMAIL_ADDRESS / GMAIL_APP_PASSWORD）")
        return False

    try:
        sender = GmailSender(
            gmail_address=gmail_address,
            app_password=app_password,
        )
        result = sender.send(
            to_email=contact_email,
            subject=item.get("email_subject", "採用ページ整備のご提案"),
            body=item.get("email_body", ""),
        )
        if result:
            logger.info(f"[メール] 送信成功: {item.get('facility_name')} ({contact_email})")
            return True
        else:
            logger.warning(f"[メール] 送信失敗: {contact_email}")
            return False
    except Exception as e:
        logger.warning(f"[メール] 例外発生: {e}")
        return False


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------
def process_queue(force: bool = False):
    """
    キューを処理する。

    Args:
        force: True の場合、"needs_review" のアイテムも処理対象にする。
    """
    logger.info("=" * 60)
    logger.info(f"auto_approver 開始 — force={force}")
    logger.info("=" * 60)

    # モジュールインポート
    FormSubmitter, GmailSender, SalesGuard, record_sent, already_sent, daily_limit_reached, config = _import_modules()

    # キュー読み込み
    queue = load_queue()
    if not queue:
        logger.info("処理するアイテムがありません。終了します。")
        return

    # 処理対象ステータスの決定
    target_statuses = {"pending"}
    if force:
        target_statuses.add("needs_review")
        logger.info("--force フラグ有効: 'needs_review' のアイテムも処理対象に追加します")

    # 統計カウンタ
    stats = {
        "total":    0,
        "sent":     0,
        "skipped":  0,
        "failed":   0,
        "limit":    0,
    }

    changed = False

    for idx, item in enumerate(queue):
        status = item.get("status", "")
        facility_name = item.get("facility_name", f"不明施設#{idx}")

        # 対象外ステータスはスキップ
        if status not in target_statuses:
            logger.debug(f"スキップ（ステータス={status}）: {facility_name}")
            continue

        stats["total"] += 1

        # 日次上限チェック
        if daily_limit_reached():
            logger.warning(f"日次送信上限に達しました。残りの {stats['total'] - stats['sent']} 件は明日以降に処理されます。")
            stats["limit"] += 1
            break

        # 重複チェック
        url   = item.get("url", "")
        email = item.get("contact_email", "")
        if already_sent(url=url, email=email, facility_name=facility_name):
            logger.info(f"送信済みのためスキップ: {facility_name}")
            queue[idx]["status"] = "sent"  # キューのステータスも更新
            stats["skipped"] += 1
            changed = True
            continue

        # 送信試行（フォーム → メール の順）
        sent = False
        method = "none"

        sent = try_form_submit(item, FormSubmitter, SalesGuard)
        if sent:
            method = "フォーム"
        else:
            sent = try_email_send(item, GmailSender, config)
            if sent:
                method = "メール"

        # 結果の反映
        if sent:
            queue[idx]["status"] = "sent"
            queue[idx]["sent_at"] = datetime.now().isoformat()
            queue[idx]["contact_method"] = method
            record_sent(
                facility_name=facility_name,
                url=url,
                email=email,
                method=method,
            )
            stats["sent"] += 1
            logger.info(f"[完了] {facility_name} — {method} で送信済み ({idx+1}/{len(queue)})")
        else:
            queue[idx]["status"] = "failed"
            queue[idx]["sent_at"] = datetime.now().isoformat()
            queue[idx]["contact_method"] = "none"
            stats["failed"] += 1
            logger.warning(f"[失敗] {facility_name} — フォーム・メール共に送信できませんでした")

        changed = True

    # キューファイルを更新
    if changed:
        save_queue(queue)

    # サマリー
    logger.info("=" * 60)
    logger.info(
        f"処理完了 — 対象: {stats['total']}件 | "
        f"送信: {stats['sent']}件 | "
        f"スキップ(重複): {stats['skipped']}件 | "
        f"失敗: {stats['failed']}件 | "
        f"上限超過: {stats['limit']}件"
    )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="approval_queue.json の pending アイテムを自動処理する"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="needs_review ステータスのアイテムも強制処理する",
    )
    args = parser.parse_args()

    process_queue(force=args.force)
