"""
sent_log.py — 送信済み施設の永続ログ管理 + 日次上限管理

ログファイル: output/sent_log.json
バックアップ:  output/sent_log.backup.json
"""

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import unicodedata
from datetime import datetime, date

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENT_LOG_FILE = os.path.join(BASE_DIR, "output", "sent_log.json")
SENT_LOG_BACKUP = os.path.join(BASE_DIR, "output", "sent_log.backup.json")

# 1日に送信できる上限（Gmail無料枠 + スパム判定回避）
DAILY_SEND_LIMIT = 40

_lock = threading.Lock()  # ファイル排他制御（同時書き込み防止）


def _load() -> list:
    """sent_log を読み込む。破損していればバックアップから復元する。"""
    for filepath in [SENT_LOG_FILE, SENT_LOG_BACKUP]:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, IOError):
            logger.warning(f"[sent_log] 読み込み失敗: {filepath} — 次のファイルを試みます")
    return []


def _save(records: list):
    """
    原子的書き込み（temp→rename）でログを保存する（ロック済み前提）。

    クラッシュしても旧ファイルが残るため、重複送信が発生しない。
    書き込み成功後にバックアップを更新する。
    """
    os.makedirs(os.path.dirname(SENT_LOG_FILE), exist_ok=True)
    dir_path = os.path.dirname(SENT_LOG_FILE)
    # 同じディレクトリにtempファイルを作成（rename が atomic になる）
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        # 旧ファイルをバックアップしてから rename（atomic swap）
        if os.path.exists(SENT_LOG_FILE):
            shutil.copy2(SENT_LOG_FILE, SENT_LOG_BACKUP)
        os.replace(tmp_path, SENT_LOG_FILE)  # os.replace は Windows でも atomic
    except Exception:
        # 書き込み失敗時は tempファイルを削除して例外を再送出
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def already_sent(url: str = "", email: str = "", facility_name: str = "") -> bool:
    """
    このURL・ドメイン・メール・施設名のいずれかで送信済みかどうかを確認する。
    5段階チェック（ロック付き）:
      1. URL完全一致（正規化後）
      2. ドメイン一致（同一法人の別ページ対策）
      3. メールアドレス一致
      4. 施設名完全一致
      5. 施設名ファジー一致（法人種別除去・表記ゆれ吸収）
    """
    with _lock:
        records = _load()
        norm_url = _normalize_url(url) if url else ""
        target_domain = _extract_domain(url) if url else ""
        norm_name = _normalize_name(facility_name) if facility_name else ""

        for r in records:
            sent_at = r.get("sent_at", "")[:10]
            past_name = r.get("facility_name", "")

            # [1] URL完全一致（正規化後）
            if norm_url and r.get("url") and norm_url == r["url"]:
                logger.warning(
                    f"[重複ブロック-L1] 送信済みURL: {url} "
                    f"({past_name} / {sent_at})"
                )
                return True

            # [2] ドメイン一致（同一法人の別ページへの誤送信防止）
            if target_domain and r.get("url"):
                past_domain = _extract_domain(r["url"])
                if past_domain and past_domain == target_domain:
                    logger.warning(
                        f"[重複ブロック-L2] 同一ドメイン送信済み: {target_domain} "
                        f"({past_name} / {sent_at})"
                    )
                    return True

            # [3] メールアドレス一致
            if email and r.get("email") and email.lower() == r["email"].lower():
                logger.warning(
                    f"[重複ブロック-L3] 送信済みメール: {email} "
                    f"({past_name} / {sent_at})"
                )
                return True

            # [4] 施設名完全一致
            if facility_name and past_name and facility_name.strip() == past_name.strip():
                logger.warning(
                    f"[重複ブロック-L4] 送信済み施設名（完全一致）: {facility_name} "
                    f"({sent_at})"
                )
                return True

            # [5] 施設名ファジー一致（法人種別除去・表記ゆれ吸収）
            if norm_name and past_name:
                norm_past = _normalize_name(past_name)
                if norm_past and len(norm_name) >= 4 and (
                    norm_name == norm_past
                    or norm_name in norm_past
                    or norm_past in norm_name
                ):
                    logger.warning(
                        f"[重複ブロック-L5] 類似施設名: 「{facility_name}」≈「{past_name}」"
                        f" ({sent_at})"
                    )
                    return True

    return False


def domain_already_sent(url: str) -> bool:
    """同一ドメインに既に送信済みかどうかを確認する（グループ施設対策・ロック付き）"""
    if not url:
        return False
    target_domain = _extract_domain(url)
    if not target_domain:
        return False
    with _lock:
        records = _load()
        for r in records:
            past_domain = _extract_domain(r.get("url", ""))
            if past_domain and past_domain == target_domain:
                logger.warning(f"[ドメイン重複ブロック] 同一ドメイン送信済み: {target_domain} ({r.get('facility_name')} / {r.get('sent_at', '')[:10]})")
                return True
    return False


def daily_limit_reached() -> bool:
    """本日の送信数が上限に達しているかどうかを確認する"""
    today = date.today().isoformat()
    records = _load()
    today_count = sum(1 for r in records if r.get("sent_at", "")[:10] == today)
    if today_count >= DAILY_SEND_LIMIT:
        logger.warning(f"[日次上限] 本日の送信数が上限({DAILY_SEND_LIMIT}件)に達しています (送信済み: {today_count}件)")
        return True
    logger.info(f"[日次上限] 本日の送信数: {today_count}/{DAILY_SEND_LIMIT}件")
    return False


def get_today_sent_count() -> int:
    """本日の送信数を返す"""
    today = date.today().isoformat()
    return sum(1 for r in _load() if r.get("sent_at", "")[:10] == today)


def record_sent(facility_name: str, url: str, email: str, method: str):
    """送信完了を記録する（ロック付き・正規化済みURLで保存）"""
    with _lock:
        records = _load()
        records.append({
            "facility_name": facility_name,
            "url": _normalize_url(url) if url else "",
            "email": email.lower() if email else "",
            "method": method,
            "sent_at": datetime.now().isoformat(),
        })
        _save(records)
    logger.info(f"[送信ログ] 記録: {facility_name} ({method}) — 本日計{get_today_sent_count()}件")


def get_sent_urls() -> set:
    """送信済みURLの集合を返す（パイプライン側の重複排除用）"""
    return {_normalize_url(r["url"]) for r in _load() if r.get("url")}


def get_sent_emails() -> set:
    """送信済みメールアドレスの集合を返す"""
    return {r["email"].lower() for r in _load() if r.get("email")}


def _normalize_url(url: str) -> str:
    """URLを正規化（末尾スラッシュ・https/http の差異を吸収）"""
    url = url.lower().rstrip("/")
    url = url.replace("https://", "").replace("http://", "")
    return url


def _extract_domain(url: str) -> str:
    """URLからドメインを抽出する"""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        # www. を除去して法人単位で比較
        return host.replace("www.", "")
    except Exception:
        return ""


def _normalize_name(name: str) -> str:
    """
    施設名を正規化して表記ゆれを吸収する。
    - 全角→半角変換
    - 法人種別プレフィックスを除去
    - スペース・記号・句読点を除去
    - 小文字化
    """
    name = unicodedata.normalize("NFKC", name)
    for prefix in [
        "株式会社", "有限会社", "合同会社", "一般社団法人", "一般財団法人",
        "社会福祉法人", "医療法人", "NPO法人", "特定非営利活動法人",
    ]:
        name = name.replace(prefix, "")
    name = re.sub(r"[\s　・\-_・。、「」『』【】（）()【】]", "", name)
    return name.lower()
