"""
sent_log.py — 送信済み施設の永続ログ管理 + 日次上限管理

ログファイル: output/sent_log.json
バックアップ:  output/sent_log.backup.json
"""

import json
import logging
import os
import shutil
import threading
from datetime import datetime, date

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENT_LOG_FILE = os.path.join(BASE_DIR, "output", "sent_log.json")
SENT_LOG_BACKUP = os.path.join(BASE_DIR, "output", "sent_log.backup.json")

# 1日に送信できる上限（Gmail無料枠 + スパム判定回避）
DAILY_SEND_LIMIT = 20

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
    """書き込み前にバックアップを作成してから保存する（ロック済み前提）。"""
    os.makedirs(os.path.dirname(SENT_LOG_FILE), exist_ok=True)
    if os.path.exists(SENT_LOG_FILE):
        shutil.copy2(SENT_LOG_FILE, SENT_LOG_BACKUP)
    with open(SENT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def already_sent(url: str = "", email: str = "", facility_name: str = "") -> bool:
    """このURL・メール・施設名のいずれかで送信済みかどうかを確認する（ロック付き）"""
    with _lock:
        records = _load()
        norm_url = _normalize_url(url) if url else ""
        for r in records:
            # URL比較（正規化して比較 ← CODEXが指摘したCRITICAL修正）
            if norm_url and r.get("url") and norm_url == r["url"]:
                logger.warning(f"[重複ブロック] 送信済みURL: {url} ({r.get('facility_name')} / {r.get('sent_at', '')[:10]})")
                return True
            # メール比較
            if email and r.get("email") and email.lower() == r["email"].lower():
                logger.warning(f"[重複ブロック] 送信済みメール: {email} ({r.get('facility_name')} / {r.get('sent_at', '')[:10]})")
                return True
            # 施設名比較（URL/メールが変わっても同一施設への再送を防ぐ）
            if facility_name and r.get("facility_name") and facility_name.strip() == r["facility_name"].strip():
                logger.warning(f"[重複ブロック] 送信済み施設名: {facility_name} ({r.get('sent_at', '')[:10]})")
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
