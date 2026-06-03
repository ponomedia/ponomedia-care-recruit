#!/usr/bin/env python3
"""
PonoMedia 介護採用 営業自動化パイプライン
=============================================
使い方:
    python run_pipeline.py --dry-run              # テスト実行（メール送信なし）
    python run_pipeline.py                        # 本番実行
    python run_pipeline.py --area 千葉県八千代市   # 特定エリアのみ
    python run_pipeline.py --rank-filter A        # ランクAのみ対象

出力:
    output/results_{timestamp}.csv にスコアリング・メール送信結果を保存
"""

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime

from dotenv import load_dotenv

# .env ファイルを最初に読み込む（config.pyのインポート前）
load_dotenv()

import config
from researcher import FacilityResearcher
from directory_scraper import DirectoryScraper
from scorer import HiringPageScorer
from email_generator import EmailGenerator
from email_sender import GmailSender
from sales_guard import SalesGuard
from form_submitter import FormSubmitter
from sent_log import already_sent, domain_already_sent, record_sent, get_sent_urls
from quality_checker import QualityChecker

# =========================================================
# ロギング設定
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# =========================================================
# CSV カラム定義
# =========================================================
CSV_COLUMNS = [
    "timestamp",
    "facility_name",
    "facility_type",
    "area",
    "url",
    "rank",
    "score",
    "has_hiring_page",
    "has_form",
    "weakness_reasons",
    "contact_email",
    "email_subject",
    "email_sent",
    "form_submitted",
    "contact_method",
    "notes",
]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="PonoMedia 介護採用 営業自動化パイプライン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--area",
        type=str,
        default=None,
        help="対象エリアを指定（例: 千葉県八千代市）。未指定時はconfig.pyの全エリアを処理",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="メールを実際に送信しないテストモード",
    )
    parser.add_argument(
        "--queue-mode",
        action="store_true",
        help="送信せずにスマホ承認キューへ保存（approver_server.py で承認後に送信）",
    )
    parser.add_argument(
        "--max-facilities",
        type=int,
        default=100,
        help="処理する施設の最大数（デフォルト: 100）",
    )
    parser.add_argument(
        "--rank-filter",
        type=str,
        default="A,B",
        help="処理対象ランク（例: A,B または A のみ）。デフォルト: A,B",
    )
    parser.add_argument(
        "--strict-auto",
        action="store_true",
        help="(非推奨: デフォルト動作になりました。このフラグは無視されます)",
    )
    parser.add_argument(
        "--form-only",
        action="store_true",
        help="フォーム送信のみ。メール送信を一切行わない（メール営業停止モード）",
    )
    return parser.parse_args()


def setup_output_dir() -> str:
    """output ディレクトリを作成してパスを返す"""
    output_dir = os.path.join(os.path.dirname(__file__), config.OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


QUEUE_FILE = os.path.join(os.path.dirname(__file__), "output", "approval_queue.json")


# =========================================================
# 送信前ガード関数
# =========================================================

def is_business_hours() -> bool:
    """9:00〜18:00 の範囲内かどうかを確認する（土日も送信可）"""
    now = datetime.now()
    return 9 <= now.hour < 18


def load_client_blocklist() -> set:
    """
    既存クライアントのドメイン・メールを読み込む。
    clients/ フォルダ内の *.txt ファイルに1行1エントリで記載する。
    """
    blocklist = set()
    clients_dir = os.path.join(os.path.dirname(__file__), "..", "clients")
    clients_dir = os.path.normpath(clients_dir)
    if not os.path.isdir(clients_dir):
        return blocklist
    for fname in os.listdir(clients_dir):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(clients_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    entry = line.strip().lower()
                    if entry and not entry.startswith("#"):
                        blocklist.add(entry)
        except Exception:
            pass
    return blocklist


def is_existing_client(url: str, email: str, facility_name: str, blocklist: set) -> bool:
    """既存クライアントかどうかをブロックリストと照合する"""
    if not blocklist:
        return False
    from urllib.parse import urlparse
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        domain = ""
    checks = [domain, email.lower() if email else "", facility_name.strip()]
    for entry in blocklist:
        if any(entry in c or c in entry for c in checks if c):
            return True
    return False


# 大手チェーン介護事業者（営業対象外 — Codex不在時も確実に除外）
LARGE_CHAIN_DOMAINS = [
    "benesse", "nichii-kaigo", "nichiicare",
    "solasto", "tsukui-group", "message-kaigo",
    "cocofump", "sonpo-care", "sompo-care",
    "careritz.co.jp",
    "kinoshita-kaigo.co.jp",
    "gakkencocofump", "universalpark",
    "irs-japan", "care-partner.co.jp",
]

LARGE_CHAIN_FACILITY_NAMES = [
    "ニチイ", "ソラスト", "ツクイ", "ベネッセ", "コムスン",
    "メッセージ", "ライフコミューン", "リアンレーヴ",
    "ケアリッツ", "SOMPOケア", "ベストライフ",
    "グッドタイム", "ウェルビー", "アミカ",
]


def is_large_chain(url: str, facility_name: str) -> bool:
    """大手チェーン介護事業者かどうかを判定する（Codex不在時のフォールバック）"""
    url_lower = url.lower()
    if any(chain in url_lower for chain in LARGE_CHAIN_DOMAINS):
        return True
    if any(name in facility_name for name in LARGE_CHAIN_FACILITY_NAMES):
        return True
    return False


# 介護・福祉以外の業種キーワード（これらが施設名に入っていたらスキップ）
NON_CARE_KEYWORDS = [
    "タクシー", "介護タクシー", "福祉タクシー", "移送",
    "医療機器", "介護用品", "福祉用具", "レンタル",
    "薬局", "調剤", "ドラッグ",
    "建設", "工務店", "リフォーム",
    "保険", "金融", "不動産",
    "IT", "システム", "コンサル",
    "飲食", "レストラン", "カフェ",
]

def is_non_care_facility(facility_name: str, url: str) -> bool:
    """施設名・URLから介護以外の業種を検出する"""
    combined = f"{facility_name} {url}".lower()
    for kw in NON_CARE_KEYWORDS:
        if kw in combined:
            return True
    return False


# 明らかに介護施設と無関係なURLパターン（要確認扱いにする）
SUSPICIOUS_URL_PATTERNS = [
    "monacoin", "bitcoin", "blockchain", "crypto", "block?page=",
    "wikipedia.org", "news.yahoo", "google.com/maps", "google.co.jp/maps",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com",
    "amazon.co.jp", "rakuten.co.jp",
]

# 介護施設の公式サイトらしいキーワード（1つでも含めばOK）
CARE_FACILITY_KEYWORDS = [
    "kaigo", "care", "service", "welfare", "fukushi", "デイ", "介護",
    "グループ", "ホーム", "訪問", "riei", "facility",
]


def is_suspicious_url(url: str, facility_name: str) -> bool:
    """URLが明らかに介護施設と無関係かどうかを判定する"""
    if not url:
        return False
    url_lower = url.lower()

    # 明らかに無関係なパターンに一致する場合
    for pattern in SUSPICIOUS_URL_PATTERNS:
        if pattern in url_lower:
            return True

    from urllib.parse import urlparse
    try:
        host = urlparse(url).netloc.lower()

        # .jp でも非公式・ポータルと判断するドメイン
        jp_non_official = [
            "mapion.co.jp", "itp.ne.jp", "ekiten.jp", "tabelog.com",
            "caremanagement.jp", "r-guide.jp", "kaigo114.jp",
            "minnanokaigo.com", "ansinkaigo.jp", "carenavi.jp",
            "kaigokensaku.mhlw.go.jp", "wam.go.jp", "mhlw.go.jp",
            "mext.go.jp", ".lg.jp", "arubaito-ex.jp", "job-medley.com",
            "kaigojob.com", "yelp.com", "jalan.net", "hotpepper.jp",
            "navitime.co.jp", "caresapo.jp", "kiracare.jp",
        ]
        if any(d in host for d in jp_non_official):
            return True

        # .jp ドメインはOK
        if host.endswith(".jp"):
            return False

        # 日本系プラットフォームはOK
        jp_safe = ["ameblo.jp", "fc2.com", "wix.com", "jimdo.com",
                   "goope.jp", "localplace.jp", "blogspot.com", "wordpress.com"]
        if any(p in host for p in jp_safe):
            return False

        # それ以外の外国ドメインは要確認
        return True
    except Exception:
        return False


def enqueue_for_approval(
    facility: dict,
    score_result: dict,
    email_data: dict,
    contact_email: str,
    force_needs_review: bool = False,
) -> None:
    """承認キューに1件追加する（approver_server.py で処理）"""
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    queue = []
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)

    url = facility.get("url", "")
    facility_name = facility.get("name", "")

    # ★ キュー内重複チェック（URL または施設名が一致すれば再キューイングしない）
    url_norm = url.lower().rstrip("/").replace("https://", "").replace("http://", "")
    DONE_STATUSES = ("pending", "needs_review", "processing", "sent", "duplicate", "blocked")
    for existing in queue:
        if existing.get("status") not in DONE_STATUSES:
            continue
        ex_url = existing.get("url", "").lower().rstrip("/").replace("https://", "").replace("http://", "")
        ex_name = (existing.get("facility_name") or "").strip()
        if (ex_url and ex_url == url_norm) or (facility_name and ex_name == facility_name):
            logger.info(f"  → キュー内重複スキップ: {facility_name} ({url})")
            return

    # 怪しいURLは「要確認」ステータスにしてキューには入れるが自動送信対象外
    suspicious = is_suspicious_url(url, facility_name) or force_needs_review
    if suspicious:
        logger.warning(f"  ⚠️ 要確認URL: {facility_name} → {url}")
        logger.warning(f"  → 承認画面に「要確認」として表示します（手動確認してください）")

    item = {
        "id": str(uuid.uuid4())[:8],
        "status": "needs_review" if suspicious else "pending",
        "added_at": datetime.now().isoformat(),
        "facility_name": facility.get("name", ""),
        "facility_type": facility.get("facility_type", ""),
        "area": facility.get("area", ""),
        "url": facility.get("url", ""),
        "rank": score_result.get("rank", ""),
        "score": score_result.get("total_score", 0),
        "weaknesses": score_result.get("weakness_reasons", []),
        "email_subject": email_data.get("subject", ""),
        "email_body": email_data.get("body", ""),
        "contact_email": contact_email,
    }
    queue.append(item)

    # 原子的書き込み（temp→rename）でクラッシュ時のJSONファイル破損を防ぐ
    import tempfile
    queue_dir = os.path.dirname(QUEUE_FILE)
    os.makedirs(queue_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=queue_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, QUEUE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info(f"  → キューに追加: {item['facility_name']} (id: {item['id']})")


def validate_email_config() -> bool:
    """メール送信に必要な設定が揃っているか確認する"""
    if not config.GMAIL_ADDRESS:
        logger.warning("GMAIL_ADDRESS が未設定です (.env を確認してください)")
        return False
    if not config.GMAIL_APP_PASSWORD:
        logger.warning("GMAIL_APP_PASSWORD が未設定です (.env を確認してください)")
        return False
    return True


def main():
    args = parse_args()

    # =========================================================
    # 初期化
    # =========================================================
    logger.info("=" * 60)
    logger.info("PonoMedia 介護採用 営業自動化パイプライン 開始")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("★ DRY-RUNモード: メールは送信されません")
    if args.queue_mode:
        logger.info("★ QUEUEモード: 送信せずにスマホ承認キューへ保存します")
        logger.info(f"   → キューファイル: {QUEUE_FILE}")
        logger.info("   → approver_server.py を起動してスマホから承認してください")
    logger.info("★ 自動送信モード（デフォルト）: フォーム取得済み・営業禁止なし・採用ページ弱い施設のみ自動送信")
    logger.info("   条件: スコア<40 / 品質Pass(CODEX不使用) / 営業禁止なし / フォームorメールあり")
    logger.info("   → 条件外はキューへ保存（approver_server.py で手動承認）")

    # ★ 夜間・休日の送信ブロック（dry-run / queue-mode は除外、strict-auto は適用）
    if not args.dry_run and not args.queue_mode and not is_business_hours():
        logger.warning("★ 営業時間外（平日9:00〜18:00以外）のため送信をスキップします")
        logger.warning("  dry-run や --queue-mode なら時間外でも実行できます")
        sys.exit(0)

    # ★ SERVICE_URLが空の場合は警告（メール本文にURLが入らない）
    if not config.SERVICE_URL and not args.dry_run:
        logger.warning("⚠ SERVICE_LP_URL が未設定です。メール本文にサービスURLが入りません。")
        logger.warning("  .env の SERVICE_LP_URL を設定するか、--dry-run で内容確認してください。")

    # 既存クライアントのブロックリストを読み込む
    client_blocklist = load_client_blocklist()
    if client_blocklist:
        logger.info(f"既存クライアントブロックリスト: {len(client_blocklist)} 件読み込み済み")

    # 対象エリアを決定（(name, heartpage_id) タプルのリスト）
    if args.area:
        # --area が指定された場合: 名前で検索して対応するタプルを探す
        matched = [(n, hid) for n, hid in config.TARGET_AREAS if args.area in n]
        target_areas = matched if matched else [(args.area, None)]
    else:
        target_areas = config.TARGET_AREAS

    rank_filter = [r.strip().upper() for r in args.rank_filter.split(",")]

    logger.info(f"対象エリア: {[n for n, _ in target_areas]}")
    logger.info(f"対象施設タイプ: {config.FACILITY_TYPES}")
    logger.info(f"処理ランクフィルタ: {rank_filter}")
    logger.info(f"最大施設数: {args.max_facilities}")

    # 出力ディレクトリ準備
    output_dir = setup_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(output_dir, f"results_{timestamp}.csv")

    # モジュール初期化
    researcher = FacilityResearcher()
    directory = DirectoryScraper()
    scorer = HiringPageScorer()
    generator = EmailGenerator()
    sales_guard = SalesGuard()
    form_submitter = FormSubmitter(
        sales_guard=sales_guard,
        wait_seconds=config.WAIT_BETWEEN_REQUESTS,
    )
    quality_checker = QualityChecker()

    # メール送信機能の準備（--form-only 時は完全スキップ）
    email_configured = validate_email_config()
    sender = None
    if args.form_only:
        logger.info("★ FORM-ONLYモード: メール送信は完全無効。フォーム送信のみ実行します。")
    elif email_configured and not args.dry_run:
        sender = GmailSender(
            gmail_address=config.GMAIL_ADDRESS,
            app_password=config.GMAIL_APP_PASSWORD,
            sender_name=config.SENDER_NAME,
        )
        # 接続テスト
        logger.info("Gmail SMTP接続テスト中...")
        if not sender.test_connection():
            logger.error("Gmail接続失敗。メール送信をスキップします。")
            sender = None

    # =========================================================
    # パイプライン実行
    # =========================================================
    seen_urls: set = get_sent_urls()  # 送信済みURL（過去分）を初期値として読み込む
    all_results: list = []       # CSVに書き込む全結果

    # 統計カウンタ
    stats = {
        "total_searched": 0,
        "total_scraped": 0,
        "rank_a": 0,
        "rank_b": 0,
        "rank_c": 0,
        "forms_submitted": 0,
        "emails_sent": 0,
        "emails_skipped_no_address": 0,
        "sales_prohibited_blocked": 0,
        "errors": 0,
    }

    facility_count = 0  # 処理済み施設数

    for area_name, area_id in target_areas:
        if facility_count >= args.max_facilities:
            logger.info(f"最大施設数 ({args.max_facilities}) に達したため終了します")
            break

        for facility_type in config.FACILITY_TYPES:
            if facility_count >= args.max_facilities:
                break

            logger.info(f"\n--- 検索: {area_name} × {facility_type} ---")

            # Step 1: heartpageから施設一覧を取得（area_idがある場合）
            facilities = []
            if area_id:
                raw_facilities = directory.scrape_facilities(
                    area_id=area_id,
                    area_name=area_name,
                    facility_type=facility_type,
                    max_per_page=config.SEARCH_RESULTS_PER_QUERY * 2,
                    wait_seconds=config.WAIT_BETWEEN_REQUESTS,
                )
                # 各施設の公式サイトURLをDDGで検索
                for fac in raw_facilities:
                    official_url = directory.find_official_website(
                        facility_name=fac["name"],
                        facility_type=facility_type,
                        area_name=area_name,
                        phone=fac.get("phone", ""),
                        wait_seconds=config.WAIT_BETWEEN_REQUESTS,
                    )
                    fac["url"] = official_url or ""
                    if not official_url:
                        logger.debug(f"  公式サイト未取得: {fac['name']}")
                        continue
                    facilities.append(fac)
            else:
                # heartpageなし → DDGフォールバック
                facilities = researcher.search_facilities(
                    area=area_name,
                    facility_type=facility_type,
                    max_results=config.SEARCH_RESULTS_PER_QUERY,
                    wait_seconds=config.WAIT_BETWEEN_REQUESTS,
                )

            stats["total_searched"] += len(facilities)
            logger.info(f"  {len(facilities)}件の施設を発見（公式サイトURL取得済み）")

            for facility in facilities:
                if facility_count >= args.max_facilities:
                    break

                url = facility.get("url", "")
                facility_name = facility.get("name", "不明施設")

                # Step 2: 重複URLをスキップ（seen_urlsは正規化済みなので比較前に正規化する）
                url_norm = url.lower().rstrip("/").replace("https://", "").replace("http://", "")
                if url_norm in seen_urls:
                    logger.debug(f"  重複URL スキップ: {url}")
                    continue
                seen_urls.add(url_norm)

                logger.info(f"  処理中: {facility_name} ({url[:60]}...)" if len(url) > 60 else f"  処理中: {facility_name} ({url})")

                # ★ 施設名「不明施設」「不明」のまま処理しない
                if not facility_name.strip() or facility_name in ("不明施設", "不明", "unknown"):
                    logger.warning(f"  施設名が不明のためスキップ: '{facility_name}'")
                    facility_count += 1
                    continue

                # ★ 既存クライアントブロック
                if is_existing_client(url, "", facility_name, client_blocklist):
                    logger.info(f"  既存クライアントのためスキップ: {facility_name}")
                    facility_count += 1
                    continue

                # ★ 介護以外の業種を検出してスキップ
                if is_non_care_facility(facility_name, url):
                    logger.warning(f"  介護以外の業種と判断してスキップ: {facility_name}")
                    facility_count += 1
                    continue

                # ★ 大手チェーン事業者をスキップ（Codex不在時のフォールバック）
                if is_large_chain(url, facility_name):
                    logger.info(f"  大手チェーン事業者のためスキップ: {facility_name}")
                    facility_count += 1
                    continue

                # Step 3: サイトをスクレイピング
                facility_data = researcher.scrape_facility(url)
                stats["total_scraped"] += 1
                time.sleep(config.WAIT_BETWEEN_REQUESTS)

                # Step 3.5: Codex 営業適格チェック（ページ内容ベース）
                #   - 営業禁止文言がないか
                #   - 入居者・ご家族専用フォームだけでないか
                #   - 大手チェーン・行政・病院でないか
                eligibility = _codex_list_eligibility_check(
                    facility_name=facility_name,
                    facility_type=facility_type,
                    area_name=area_name,
                    phone=facility.get("phone", ""),
                    address=facility.get("address", ""),
                    url=url,
                    facility_data=facility_data,
                )
                if eligibility["verdict"] == "EXCLUDE":
                    logger.warning(
                        f"  [Codex-適格除外] {facility_name} — {eligibility['reason']}"
                    )
                    _append_result(
                        all_results, facility, {"rank": "C", "total_score": 0,
                            "has_hiring_page": False, "has_form": False, "weakness_reasons": []},
                        contact_email="", email_subject="", email_sent=False,
                        form_submitted=False, contact_method="codex-excluded",
                        notes=f"Codex適格チェック除外: {eligibility['reason']}",
                    )
                    facility_count += 1
                    continue
                if eligibility["verdict"] == "REVIEW":
                    logger.warning(
                        f"  [Codex-要確認] {facility_name} — {eligibility['reason']}"
                    )
                    facility["needs_review"] = True  # 後段enqueueでneeds_review扱い

                # Step 4: 採用ページをスコアリング
                score_result = scorer.score(facility_data)
                rank = score_result["rank"]

                # ランクカウント
                stats[f"rank_{rank.lower()}"] += 1
                logger.info(
                    f"  スコア: {score_result['total_score']}/100 | "
                    f"ランク: {rank} | "
                    f"弱点: {len(score_result['weakness_reasons'])}件"
                )

                # Step 4.5: 品質2重チェック（内部ルール + CODEX）
                contact_email_tmp = ""
                if facility_data and facility_data.get("emails"):
                    contact_email_tmp = facility_data["emails"][0]
                quality = quality_checker.check(
                    facility_name=facility_name,
                    url=url,
                    facility_data=facility_data,
                    contact_email=contact_email_tmp,
                )
                if quality["verdict"] == "fail":
                    logger.warning(
                        f"  ★ 品質チェックNG → スキップ: {quality['reason']}"
                        + (" (CODEX)" if quality["codex_used"] else "")
                    )
                    facility_count += 1
                    continue
                if quality["verdict"] == "needs_review":
                    logger.warning(
                        f"  ⚠️ 品質チェック要確認 → needs_reviewでキュー追加: {quality['reason']}"
                        + (" (CODEX)" if quality["codex_used"] else "")
                    )
                    # needs_review として強制フラグを立てて enqueue（後段で処理）

                # Step 5: ランクフィルタ + MIN_SCORE_TO_CONTACT チェック
                # ランクCまたはフィルタ外はスキップ
                if rank not in rank_filter:
                    logger.info(f"  ランク {rank} はフィルタ対象外のためスキップ")
                    _append_result(
                        all_results,
                        facility, score_result,
                        contact_email="",
                        email_subject="",
                        email_sent=False,
                        form_submitted=False,
                        contact_method="skipped",
                        notes=f"ランク{rank}のためスキップ",
                    )
                    facility_count += 1
                    continue
                # スコアが MIN_SCORE_TO_CONTACT 以上なら採用ページが十分 → スキップ
                if score_result.get("total_score", 0) >= config.MIN_SCORE_TO_CONTACT:
                    logger.info(
                        f"  スコア {score_result['total_score']} >= {config.MIN_SCORE_TO_CONTACT}"
                        f"（採用ページ十分）のためスキップ"
                    )
                    _append_result(
                        all_results,
                        facility, score_result,
                        contact_email="",
                        email_subject="",
                        email_sent=False,
                        form_submitted=False,
                        contact_method="skipped",
                        notes=f"スコア{score_result['total_score']}≥{config.MIN_SCORE_TO_CONTACT}で採用ページ充実",
                    )
                    facility_count += 1
                    continue

                # Step 6: メール生成
                email_data = generator.generate_outreach_email(
                    facility_name=facility_name,
                    facility_type=facility_type,
                    area=area_name,
                    score_result=score_result,
                    service_lp_url=config.SERVICE_URL,
                    sample_site_url=config.SAMPLE_SITE_URL,
                )

                # ★ 施設名・本文の空チェック（不完全データは絶対に送らない）
                if not facility_name.strip():
                    logger.warning("  施設名が空のためスキップ")
                    facility_count += 1
                    continue
                if not email_data.get("body", "").strip():
                    logger.warning("  メール本文が空のためスキップ")
                    facility_count += 1
                    continue

                # 連絡先メールを特定
                contact_email = ""
                if facility_data and facility_data.get("emails"):
                    contact_email = facility_data["emails"][0]

                # =========================================================
                # Step 6.5: Pass 1 営業禁止チェック（スクレイピング時フラグ）
                # =========================================================
                if facility_data and facility_data.get("is_sales_prohibited"):
                    matched_info = facility_data.get("sales_guard_pass1", {}).get(
                        "matched_patterns", []
                    )[:2]
                    logger.warning(
                        f"  ★ 営業禁止サイト（Pass 1済み）— {facility_name} への送信をスキップ"
                        f" | 検出: {matched_info}"
                    )
                    stats["sales_prohibited_blocked"] += 1
                    _append_result(
                        all_results,
                        facility, score_result,
                        contact_email=contact_email,
                        email_subject=email_data["subject"],
                        email_sent=False,
                        form_submitted=False,
                        contact_method="blocked",
                        notes=f"営業禁止検出（Pass 1）のためスキップ: {matched_info}",
                    )
                    facility_count += 1
                    continue

                # =========================================================
                # --queue-mode: 送信せずにキューに保存してスキップ
                # =========================================================
                if args.queue_mode:
                    # 送信済みチェック（URL・メール・施設名）
                    if already_sent(url=url, email=contact_email, facility_name=facility_name):
                        logger.info(f"  → 送信済みのためキュースキップ: {facility_name}")
                        facility_count += 1
                        continue
                    enqueue_for_approval(
                        facility=facility,
                        score_result=score_result,
                        email_data=email_data,
                        contact_email=contact_email,
                        force_needs_review=(
                            quality["verdict"] == "needs_review"
                            or facility.get("needs_review", False)
                        ),
                    )
                    _append_result(
                        all_results,
                        facility, score_result,
                        contact_email=contact_email,
                        email_subject=email_data["subject"],
                        email_sent=False,
                        form_submitted=False,
                        contact_method="queued",
                        notes="承認待ちキューに追加",
                    )
                    facility_count += 1
                    continue

                # =========================================================
                # 自動送信判定（デフォルト動作）
                #   ① 採用ページが弱い (score < 40)
                #   ② 公式サイトと確定 (quality pass, CODEX不使用)
                #   ③ 営業禁止なし (上の Pass 1 で既にブロック済み)
                #   ④ フォームまたはメールが取得できている
                # 条件を満たさない場合はキューへ（手動確認）
                # =========================================================

                # ─────────────────────────────────────────────────
                # 重複送信防止 Layer 1: URL+ドメイン+メール+施設名（5段階）
                # ─────────────────────────────────────────────────
                if already_sent(url=url, email=contact_email, facility_name=facility_name):
                    logger.info(f"  → [Layer1] 送信済みのためスキップ: {facility_name}")
                    facility_count += 1
                    continue

                # ─────────────────────────────────────────────────
                # 重複送信防止 Layer 2: ドメイン重複チェック（独立した別呼び出し）
                # ─────────────────────────────────────────────────
                if domain_already_sent(url):
                    logger.info(f"  → [Layer2] 同一ドメイン送信済みのためスキップ: {facility_name} ({url})")
                    facility_count += 1
                    continue

                total_score = score_result.get("total_score", 0)
                contact_form_url_tmp = (
                    form_submitter.find_contact_form_url(facility_data)
                    if facility_data else None
                )
                has_contact = bool(contact_form_url_tmp or contact_email)

                # 自動送信条件チェック
                is_auto_sendable = (
                    quality["verdict"] == "pass"        # 内部ルールで確定Pass
                    and not quality.get("codex_used")   # CODEXは使っていない（グレー判定なし）
                    and total_score < 40                # 採用ページが弱い（スコア<40）
                    and has_contact                     # フォームまたはメールあり
                )

                if not is_auto_sendable:
                    reason = []
                    if quality["verdict"] != "pass": reason.append(f"品質:{quality['verdict']}")
                    if quality.get("codex_used"):    reason.append("CODEX使用")
                    if total_score >= 40:            reason.append(f"スコア{total_score}≥40")
                    if not has_contact:              reason.append("連絡先なし")
                    logger.info(f"  → 自動送信条件外（{', '.join(reason)}）→ キューへ: {facility_name}")
                    enqueue_for_approval(
                        facility=facility,
                        score_result=score_result,
                        email_data=email_data,
                        contact_email=contact_email,
                        force_needs_review=(
                            quality["verdict"] == "needs_review"
                            or facility.get("needs_review", False)
                        ),
                    )
                    _append_result(
                        all_results, facility, score_result,
                        contact_email=contact_email,
                        email_subject=email_data["subject"],
                        email_sent=False, form_submitted=False,
                        contact_method="queued",
                        notes=f"自動送信条件外({', '.join(reason)}) → キュー",
                    )
                    facility_count += 1
                    continue

                logger.info(
                    f"  ✅ 自動送信条件クリア → 送信: {facility_name} "
                    f"(スコア:{total_score}, 品質:{quality['verdict']})"
                )
                # 以降は送信フローへ fall-through（contact_form_url_tmp を使い回す）
                _preloaded_form_url = contact_form_url_tmp

                email_sent = False
                form_submitted = False
                contact_method = "none"
                notes = ""

                # =========================================================
                # Step 7a: 問い合わせフォーム送信を試みる（Pass 2チェック込み）
                # =========================================================
                form_result = {"success": False, "blocked": False, "reason": "未試行"}
                # 自動送信判定時に取得済みのURLを再利用（2度スクレイピングしない）
                contact_form_url = contact_form_url_tmp

                if contact_form_url and not args.dry_run:
                    # ─────────────────────────────────────────────
                    # 重複送信防止 Layer 3: フォームPOST直前の最終確認
                    # ─────────────────────────────────────────────
                    if already_sent(url=url, email=contact_email, facility_name=facility_name):
                        logger.critical(
                            f"  ★ [Layer3-CRITICAL] フォーム送信直前で重複検出 → 緊急停止: {facility_name}"
                        )
                        facility_count += 1
                        continue
                    # ─────────────────────────────────────────────
                    # Codex Wチェック: 送信して本当に大丈夫か最終判定
                    # ─────────────────────────────────────────────
                    codex_check = _codex_send_check(
                        facility_name=facility_name,
                        url=url,
                        contact_email=contact_email,
                        email_subject=email_data["subject"],
                        email_body=email_data["body"],
                        score_result=score_result,
                    )
                    if codex_check["verdict"] != "SEND":
                        logger.warning(
                            f"  ★ [Codex-BLOCK] フォーム送信を中止: {facility_name} "
                            f"— {codex_check['reason']}"
                        )
                        stats["codex_blocked"] = stats.get("codex_blocked", 0) + 1
                        _append_result(
                            all_results, facility, score_result,
                            contact_email=contact_email,
                            email_subject=email_data["subject"],
                            email_sent=False, form_submitted=False,
                            contact_method="codex-blocked",
                            notes=f"Codex最終判定でブロック: {codex_check['reason']}",
                        )
                        facility_count += 1
                        continue
                    logger.info(f"  フォームURL発見: {contact_form_url}")
                    form_result = form_submitter.submit_to_facility(
                        facility_data=facility_data,
                        contact_form_url=contact_form_url,
                        message_subject=email_data["subject"],
                        message_body=email_data["body"],
                        sender_name=config.SENDER_NAME,
                        sender_email=config.GMAIL_ADDRESS,
                    )

                    if form_result.get("blocked"):
                        # Pass 2 でも営業禁止を検出 → ハードブロック
                        logger.warning(
                            f"  ★ 営業禁止（Pass 2）ブロック: {form_result['reason']}"
                        )
                        stats["sales_prohibited_blocked"] += 1
                        _append_result(
                            all_results,
                            facility, score_result,
                            contact_email=contact_email,
                            email_subject=email_data["subject"],
                            email_sent=False,
                            form_submitted=False,
                            contact_method="blocked",
                            notes=f"営業禁止（Pass 2）: {form_result['reason']}",
                        )
                        facility_count += 1
                        continue

                    if form_result["success"]:
                        stats["forms_submitted"] += 1
                        form_submitted = True
                        contact_method = "form"
                        notes = f"フォーム送信成功: {contact_form_url}"
                        logger.info(f"  フォーム送信成功: {contact_form_url}")
                        try:
                            record_sent(facility_name, url, contact_email, "form")
                        except Exception as e_log:
                            logger.critical(f"  [CRITICAL] sent_log書き込み失敗（フォーム）: {e_log}")
                            _write_emergency_log(output_dir, facility_name, url, contact_email, "form")
                        time.sleep(config.WAIT_BETWEEN_EMAILS)

                elif contact_form_url and args.dry_run:
                    # dry-runモード: フォームURLのみプレビュー
                    logger.info(
                        f"  [DRY-RUN] フォームURL発見（送信スキップ）: {contact_form_url}"
                    )
                    logger.info(f"  [DRY-RUN] 件名: {email_data['subject']}")
                    _print_email_preview(email_data, contact_email)
                    notes = f"dry-run: フォーム送信スキップ ({contact_form_url})"
                    contact_method = "dry-run-form"

                # =========================================================
                # Step 7b: フォーム送信できなかった場合のメールフォールバック
                #          --form-only 時はメール送信を行わず記録のみ
                # =========================================================
                if not form_submitted and not form_result.get("blocked") and contact_method not in ("dry-run-form",):
                    if args.form_only:
                        notes = "form-onlyモード: フォームなしのためスキップ（メール送信なし）"
                        contact_method = "form-only-skip"
                        logger.info(f"  [FORM-ONLY] フォーム未取得のためスキップ: {facility_name}")
                    elif args.dry_run:
                        notes = "dry-run: 送信スキップ"
                        logger.info(f"  [DRY-RUN] 件名: {email_data['subject']}")
                        _print_email_preview(email_data, contact_email)
                        contact_method = "dry-run-email"

                    elif not contact_email:
                        notes = "メールアドレス未取得・フォームなしのためスキップ"
                        stats["emails_skipped_no_address"] += 1
                        logger.info("  フォームもメールアドレスも見つからないためスキップ")
                        contact_method = "none"

                    elif sender:
                        # ★ 日次上限チェック（本番実行時も上限を守る）
                        from sent_log import daily_limit_reached
                        if daily_limit_reached():
                            logger.warning("  本日の送信上限に達しました。送信をスキップします")
                            notes = "日次送信上限到達のためスキップ"
                            contact_method = "limit-reached"
                            facility_count += 1
                            continue
                        # ─────────────────────────────────────────────
                        # 重複送信防止 Layer 3: メール送信直前の最終確認
                        # ─────────────────────────────────────────────
                        if already_sent(url=url, email=contact_email, facility_name=facility_name):
                            logger.critical(
                                f"  ★ [Layer3-CRITICAL] メール送信直前で重複検出 → 緊急停止: {facility_name}"
                            )
                            facility_count += 1
                            continue
                        # ─────────────────────────────────────────────
                        # Codex Wチェック: メール送信して本当に大丈夫か最終判定
                        # ─────────────────────────────────────────────
                        codex_check_mail = _codex_send_check(
                            facility_name=facility_name,
                            url=url,
                            contact_email=contact_email,
                            email_subject=email_data["subject"],
                            email_body=email_data["body"],
                            score_result=score_result,
                        )
                        if codex_check_mail["verdict"] != "SEND":
                            logger.warning(
                                f"  ★ [Codex-BLOCK] メール送信を中止: {facility_name} "
                                f"— {codex_check_mail['reason']}"
                            )
                            stats["codex_blocked"] = stats.get("codex_blocked", 0) + 1
                            _append_result(
                                all_results, facility, score_result,
                                contact_email=contact_email,
                                email_subject=email_data["subject"],
                                email_sent=False, form_submitted=False,
                                contact_method="codex-blocked",
                                notes=f"Codex最終判定でブロック: {codex_check_mail['reason']}",
                            )
                            facility_count += 1
                            continue
                        # メール実送信
                        success = sender.send(
                            to_email=contact_email,
                            subject=email_data["subject"],
                            body=email_data["body"],
                        )
                        email_sent = success
                        if success:
                            stats["emails_sent"] += 1
                            contact_method = "email"
                            notes = f"メール送信成功: {contact_email}"
                            logger.info(f"  メール送信成功: {contact_email}")
                            try:
                                record_sent(facility_name, url, contact_email, "email")
                            except Exception as e_log:
                                logger.critical(f"  [CRITICAL] sent_log書き込み失敗（メール）: {e_log}")
                                _write_emergency_log(output_dir, facility_name, url, contact_email, "email")
                            time.sleep(config.WAIT_BETWEEN_EMAILS)
                        else:
                            notes = "メール送信失敗"
                            contact_method = "email-failed"
                            stats["errors"] += 1
                    else:
                        notes = "Gmail未設定のため送信スキップ"
                        contact_method = "none"

                # Step 8: 結果を記録
                _append_result(
                    all_results,
                    facility, score_result,
                    contact_email=contact_email,
                    email_subject=email_data["subject"],
                    email_sent=email_sent,
                    form_submitted=form_submitted,
                    contact_method=contact_method,
                    notes=notes,
                )

                facility_count += 1

    # =========================================================
    # CSV出力
    # =========================================================
    _write_csv(csv_path, all_results)
    logger.info(f"\nCSV保存完了: {csv_path}")

    # =========================================================
    # サマリー表示
    # =========================================================
    logger.info("\n" + "=" * 60)
    logger.info("パイプライン完了 — サマリー")
    logger.info("=" * 60)
    logger.info(f"  検索でヒットした施設数:  {stats['total_searched']}")
    logger.info(f"  スクレイピング実行数:    {stats['total_scraped']}")
    logger.info(f"  ランクA（最優先）:       {stats['rank_a']} 件")
    logger.info(f"  ランクB（要フォロー）:   {stats['rank_b']} 件")
    logger.info(f"  ランクC（スキップ）:     {stats['rank_c']} 件")
    logger.info(f"  フォーム送信成功:        {stats['forms_submitted']} 件")
    logger.info(f"  メール送信成功:          {stats['emails_sent']} 件")
    logger.info(f"  アドレス未取得スキップ:  {stats['emails_skipped_no_address']} 件")
    logger.info(f"  営業禁止ブロック:        {stats['sales_prohibited_blocked']} 件")
    logger.info(f"  Codex最終判定ブロック:   {stats.get('codex_blocked', 0)} 件")
    logger.info(f"  エラー:                  {stats['errors']} 件")
    logger.info(f"\n  出力ファイル: {csv_path}")
    logger.info("=" * 60)

    # =========================================================
    # 月収目標トラッカー（目標: 30万円/月 = 5.5件/月）
    # =========================================================
    _print_revenue_tracker(output_dir)


def _print_revenue_tracker(output_dir: str) -> None:
    """
    月収目標トラッカー。
    output/results_*.csv を集計して今月の送信数・推定受注数・推定売上を表示する。
    目標: 月収30万円（55,000円 × 5.5件）
    """
    import glob
    from datetime import date

    PRICE_PER_CLIENT = 55000
    MONTHLY_GOAL = 300000
    CLIENTS_NEEDED = MONTHLY_GOAL / PRICE_PER_CLIENT  # ≈ 5.45

    # 今月のCSVを集計
    today = date.today()
    month_prefix = today.strftime("%Y%m")
    pattern = os.path.join(output_dir, f"results_{month_prefix}*.csv")
    csvs = glob.glob(pattern)

    total_sent = 0
    for csv_path in csvs:
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sent = row.get("email_sent", "").lower()
                    submitted = row.get("form_submitted", "").lower()
                    if sent == "true" or submitted == "true":
                        total_sent += 1
        except Exception:
            pass

    # 仮定: 返信率1%、成約率50%
    estimated_replies = total_sent * 0.01
    estimated_clients = estimated_replies * 0.5
    estimated_revenue = estimated_clients * PRICE_PER_CLIENT

    progress_pct = min(100, estimated_revenue / MONTHLY_GOAL * 100)
    bar_filled = int(progress_pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    logger.info("\n" + "=" * 60)
    logger.info(f"  💰 月収目標トラッカー ({today.strftime('%Y年%m月')})")
    logger.info("=" * 60)
    logger.info(f"  今月の送信数:       {total_sent:,} 件")
    logger.info(f"  推定返信数(1%):     {estimated_replies:.1f} 件")
    logger.info(f"  推定成約数(50%):    {estimated_clients:.1f} 件")
    logger.info(f"  推定売上:           {estimated_revenue:,.0f} 円")
    logger.info(f"  目標 ({MONTHLY_GOAL:,}円):  [{bar}] {progress_pct:.0f}%")
    logger.info(f"  目標達成まで:       {max(0, CLIENTS_NEEDED - estimated_clients):.1f} 件の成約が必要")
    logger.info(f"  → 目安: あと {max(0, int((CLIENTS_NEEDED - estimated_clients) / 0.005) - total_sent):,} 件の送信で目標射程圏")
    logger.info("=" * 60)


# =========================================================
# ヘルパー関数
# =========================================================

def _codex_list_eligibility_check(
    facility_name: str,
    facility_type: str,
    area_name: str,
    phone: str,
    address: str,
    url: str,
    facility_data: dict = None,
) -> dict:
    """
    「この施設に営業してよいか」をCodexに確認する包括的Wチェック。

    チェック項目:
      - 大手チェーン・病院・行政・公的機関でないか
      - ページに「営業お断り」「営業禁止」等の文言がないか
      - 問い合わせフォームが入居者・ご家族専用でないか（採用担当への窓口があるか）
      - ポータルサイト・比較サイトの施設ページでないか

    Returns:
        {"verdict": "INCLUDE" | "EXCLUDE" | "REVIEW", "reason": str}
    """
    fd = facility_data or {}
    page_title = fd.get("title", "（未取得）")
    page_meta = fd.get("meta_description", "（未取得）")
    page_text = fd.get("full_text", "")[:600]

    prompt = (
        f"介護採用支援サービス（採用ページ改善・求人サイト構築）の営業先として"
        f"この施設に連絡してよいか判定してください。\n\n"
        f"【施設情報】\n"
        f"施設名: {facility_name}\n"
        f"施設種別: {facility_type}\n"
        f"エリア: {area_name}\n"
        f"電話番号: {phone or '不明'}\n"
        f"住所: {address or '不明'}\n"
        f"公式サイトURL: {url}\n\n"
        f"【ページ内容（スクレイピング結果）】\n"
        f"ページタイトル: {page_title}\n"
        f"メタ説明: {page_meta}\n"
        f"本文冒頭:\n{page_text}\n\n"
        f"【必ずEXCLUDEにすべき条件】\n"
        f"1. 大手チェーン法人（ニチイ・ソラスト・ツクイ・コムスン・メッセージ・ベネッセ等）\n"
        f"2. 病院・クリニック・医療機関（介護施設でない）\n"
        f"3. 行政機関・社会福祉協議会・公的機関\n"
        f"4. ページ内に「営業お断り」「電話・メールでの営業はお断り」「業者からの連絡不可」\n"
        f"   「セールスはご遠慮ください」等の営業禁止文言がある\n"
        f"5. 問い合わせ先・フォームが入居希望者・ご家族専用で採用・業者向け窓口が一切ない\n"
        f"   （「ご入居のご相談」「見学のお申し込み」のみで、採用・その他への連絡手段がない）\n"
        f"6. ポータルサイト・比較サイトの施設個別ページ（みんなの介護・LIFULL介護等）\n"
        f"7. 複数施設を束ねる法人本社HPのみ（個別事業所の連絡先がない）\n\n"
        f"【INCLUDEにすべき条件】\n"
        f"・中小規模の介護・福祉事業所の公式サイト\n"
        f"・営業禁止の文言がない\n"
        f"・問い合わせフォームやメールアドレスが採用・その他にも使えそう\n"
        f"・採用ページが弱く、改善余地がある\n\n"
        f"以下の1語のみを1行目に、理由（30字以内）を2行目に書いてください:\n"
        f"INCLUDE — 営業してよい\n"
        f"EXCLUDE — 除外（理由必須）\n"
        f"REVIEW  — 判断できない（要人間確認）"
    )

    try:
        result = subprocess.run(
            ["codex", "exec", "-c", 'sandbox_permissions=["disk-full-read-access"]', prompt],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        raw = result.stdout + result.stderr
        upper = raw.upper()
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        reason_line = lines[1] if len(lines) > 1 else ""

        if "EXCLUDE" in upper:
            return {"verdict": "EXCLUDE", "reason": f"Codex除外: {reason_line}"}
        elif "INCLUDE" in upper:
            return {"verdict": "INCLUDE", "reason": f"Codex承認: {reason_line}"}
        else:
            return {"verdict": "REVIEW", "reason": f"Codex判定不明 → 要確認: {raw[:80]}"}

    except subprocess.TimeoutExpired:
        logger.warning(f"  [Codex-適格] タイムアウト → INCLUDE継続: {facility_name}")
        return {"verdict": "INCLUDE", "reason": "Codexタイムアウト → INCLUDE継続"}
    except FileNotFoundError:
        logger.warning("  [Codex-適格] codexコマンドが見つかりません → INCLUDE継続")
        return {"verdict": "INCLUDE", "reason": "Codex未インストール → INCLUDE継続"}
    except Exception as e:
        logger.warning(f"  [Codex-適格] エラー → INCLUDE継続: {e}")
        return {"verdict": "INCLUDE", "reason": f"Codexエラー → INCLUDE継続: {e}"}


def _codex_send_check(
    facility_name: str,
    url: str,
    contact_email: str,
    email_subject: str,
    email_body: str,
    score_result: dict,
) -> dict:
    """
    Codexに送信前最終確認を行う（Wチェック）。

    Returns:
        {"verdict": "SEND" | "SKIP" | "REVIEW", "reason": str}
    """
    weaknesses = "、".join(score_result.get("weakness_reasons", [])[:5])
    score = score_result.get("total_score", 0)
    body_preview = email_body[:300].replace("\n", " ")

    prompt = (
        f"介護採用支援サービスの営業メール送信について、送って大丈夫かを判定してください。\n\n"
        f"【施設情報】\n"
        f"施設名: {facility_name}\n"
        f"URL: {url}\n"
        f"連絡先: {contact_email or 'フォーム送信'}\n"
        f"採用ページスコア: {score}/100（低いほど採用ページが弱い）\n"
        f"採用ページの弱点: {weaknesses}\n\n"
        f"【送信予定メール冒頭】\n"
        f"件名: {email_subject}\n"
        f"本文: {body_preview}\n\n"
        f"【SKIPにすべき条件】\n"
        f"・施設名が空・不自然・介護施設ではない\n"
        f"・ポータルサイト・求人サイト・行政サイト\n"
        f"・採用ページスコアが40以上（採用ページが十分整っている）\n"
        f"・メール本文に施設名が含まれていない・テンプレートのまま\n"
        f"・明らかに送り先が間違っている\n\n"
        f"【SENDにすべき条件】\n"
        f"・介護・福祉施設の公式サイトである\n"
        f"・採用ページが弱い（スコア40未満・弱点が複数ある）\n"
        f"・メール本文が施設名入りで自然な日本語\n\n"
        f"以下の1語のみ1行目に、理由を2行目に書いてください:\n"
        f"SEND — 送信してよい\n"
        f"SKIP — 送信してはいけない\n"
        f"REVIEW — 判断できない（安全のためスキップ扱い）"
    )

    try:
        result = subprocess.run(
            ["codex", "exec", "-c", 'sandbox_permissions=["disk-full-read-access"]', prompt],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        raw = result.stdout + result.stderr
        upper = raw.upper()

        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        reason_line = lines[1] if len(lines) > 1 else ""

        if "SEND" in upper and "SKIP" not in upper:
            logger.info(f"  [Codex最終判定] SEND承認: {facility_name} — {reason_line}")
            return {"verdict": "SEND", "reason": f"Codex承認: {reason_line}"}
        elif "SKIP" in upper:
            logger.warning(f"  [Codex最終判定] SKIP拒否: {facility_name} — {reason_line}")
            return {"verdict": "SKIP", "reason": f"Codex拒否: {reason_line}"}
        else:
            logger.warning(f"  [Codex最終判定] REVIEW（安全のためスキップ）: {facility_name}")
            return {"verdict": "REVIEW", "reason": f"Codex判定不明 → 安全のためスキップ: {raw[:100]}"}

    except subprocess.TimeoutExpired:
        logger.warning(f"  [Codex最終判定] タイムアウト → スキップ: {facility_name}")
        return {"verdict": "REVIEW", "reason": "Codexタイムアウト → 安全のためスキップ"}
    except FileNotFoundError:
        # Codex未インストール時は内部チェック済みとして送信を許可する
        # （quality_checker・sales_guard・URL検証が既に通過済みのため）
        logger.info(f"  [Codex最終判定] codexコマンドなし → 内部チェック通過済みで送信: {facility_name}")
        return {"verdict": "SEND", "reason": "Codex未インストール → 内部チェック通過済みで送信"}
    except Exception as e:
        logger.warning(f"  [Codex最終判定] エラー → スキップ: {e}")
        return {"verdict": "REVIEW", "reason": f"Codexエラー → 安全のためスキップ: {e}"}


def _write_emergency_log(output_dir: str, facility_name: str, url: str, email: str, method: str):
    """sent_log書き込み失敗時の緊急バックアップ（approver_serverのreconcileが次回取り込む）"""
    try:
        emergency_path = os.path.join(output_dir, "sent_emergency.txt")
        with open(emergency_path, "a", encoding="utf-8") as ef:
            ef.write(
                f"{datetime.now().isoformat()}\t{facility_name}\t{url}\t{email}\t{method}\n"
            )
        logger.warning(f"  [緊急ログ] {emergency_path} に記録しました")
    except Exception as e2:
        logger.critical(f"  [CRITICAL] 緊急ログへの書き込みも失敗: {e2}")


def _append_result(
    results: list,
    facility: dict,
    score_result: dict,
    contact_email: str,
    email_subject: str,
    email_sent: bool,
    notes: str,
    form_submitted: bool = False,
    contact_method: str = "none",
):
    """結果リストに1件追加する"""
    results.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "facility_name": facility.get("name", ""),
        "facility_type": facility.get("facility_type", ""),
        "area": facility.get("area", ""),
        "url": facility.get("url", ""),
        "rank": score_result.get("rank", ""),
        "score": score_result.get("total_score", 0),
        "has_hiring_page": score_result.get("has_hiring_page", False),
        "has_form": score_result.get("has_form", False),
        "weakness_reasons": " / ".join(score_result.get("weakness_reasons", [])),
        "contact_email": contact_email,
        "email_subject": email_subject,
        "email_sent": email_sent,
        "form_submitted": form_submitted,
        "contact_method": contact_method,
        "notes": notes,
    })


def _write_csv(csv_path: str, results: list):
    """結果リストをCSVファイルに書き出す"""
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        # utf-8-sig: Excelで文字化けしないBOM付きUTF-8
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(results)


def _print_email_preview(email_data: dict, contact_email: str):
    """dry-runモード時にメール内容をコンソールにプレビュー表示する"""
    print("\n" + "-" * 50)
    print(f"[メールプレビュー]")
    print(f"宛先: {contact_email or '(未取得)'}")
    print(f"件名: {email_data['subject']}")
    print("本文:")
    print(email_data["body"])
    print("-" * 50 + "\n")


if __name__ == "__main__":
    main()
