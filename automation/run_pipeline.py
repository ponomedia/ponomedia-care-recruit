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
import logging
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

# .env ファイルを最初に読み込む（config.pyのインポート前）
load_dotenv()

import config
from researcher import FacilityResearcher
from scorer import HiringPageScorer
from email_generator import EmailGenerator
from email_sender import GmailSender
from sales_guard import SalesGuard
from form_submitter import FormSubmitter

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
        "--max-facilities",
        type=int,
        default=50,
        help="処理する施設の最大数（デフォルト: 50）",
    )
    parser.add_argument(
        "--rank-filter",
        type=str,
        default="A,B",
        help="処理対象ランク（例: A,B または A のみ）。デフォルト: A,B",
    )
    return parser.parse_args()


def setup_output_dir() -> str:
    """output ディレクトリを作成してパスを返す"""
    output_dir = os.path.join(os.path.dirname(__file__), config.OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


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

    # 対象エリアを決定
    target_areas = [args.area] if args.area else config.TARGET_AREAS
    rank_filter = [r.strip().upper() for r in args.rank_filter.split(",")]

    logger.info(f"対象エリア: {target_areas}")
    logger.info(f"対象施設タイプ: {config.FACILITY_TYPES}")
    logger.info(f"処理ランクフィルタ: {rank_filter}")
    logger.info(f"最大施設数: {args.max_facilities}")

    # 出力ディレクトリ準備
    output_dir = setup_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(output_dir, f"results_{timestamp}.csv")

    # モジュール初期化
    researcher = FacilityResearcher()
    scorer = HiringPageScorer()
    generator = EmailGenerator()
    sales_guard = SalesGuard()
    form_submitter = FormSubmitter(
        sales_guard=sales_guard,
        wait_seconds=config.WAIT_BETWEEN_REQUESTS,
    )

    # メール送信機能の準備
    email_configured = validate_email_config()
    sender = None
    if email_configured and not args.dry_run:
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
    seen_urls: set = set()       # 重複URL排除用
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

    for area in target_areas:
        if facility_count >= args.max_facilities:
            logger.info(f"最大施設数 ({args.max_facilities}) に達したため終了します")
            break

        for facility_type in config.FACILITY_TYPES:
            if facility_count >= args.max_facilities:
                break

            logger.info(f"\n--- 検索: {area} × {facility_type} ---")

            # Step 1: DuckDuckGoで施設を検索
            facilities = researcher.search_facilities(
                area=area,
                facility_type=facility_type,
                max_results=config.SEARCH_RESULTS_PER_QUERY,
                wait_seconds=config.WAIT_BETWEEN_REQUESTS,
            )
            stats["total_searched"] += len(facilities)
            logger.info(f"  {len(facilities)}件の施設を発見")

            for facility in facilities:
                if facility_count >= args.max_facilities:
                    break

                url = facility.get("url", "")
                facility_name = facility.get("name", "不明施設")

                # Step 2: 重複URLをスキップ
                if url in seen_urls:
                    logger.debug(f"  重複URL スキップ: {url}")
                    continue
                seen_urls.add(url)

                logger.info(f"  処理中: {facility_name} ({url[:60]}...)" if len(url) > 60 else f"  処理中: {facility_name} ({url})")

                # Step 3: サイトをスクレイピング
                facility_data = researcher.scrape_facility(url)
                stats["total_scraped"] += 1
                time.sleep(config.WAIT_BETWEEN_REQUESTS)

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

                # Step 5: ランクフィルタ（CまたはフィルタにないランクはスキップCSVに記録のみ）
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

                # Step 6: メール生成
                email_data = generator.generate_outreach_email(
                    facility_name=facility_name,
                    facility_type=facility_type,
                    area=area,
                    score_result=score_result,
                    service_lp_url=config.SERVICE_URL,
                    sample_site_url=config.SAMPLE_SITE_URL,
                )

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

                email_sent = False
                form_submitted = False
                contact_method = "none"
                notes = ""

                # =========================================================
                # Step 7a: 問い合わせフォーム送信を試みる（Pass 2チェック込み）
                # =========================================================
                form_result = {"success": False, "blocked": False, "reason": "未試行"}
                contact_form_url = (
                    form_submitter.find_contact_form_url(facility_data)
                    if facility_data else None
                )

                if contact_form_url and not args.dry_run:
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
                # =========================================================
                if not form_submitted and not form_result.get("blocked") and contact_method not in ("dry-run-form",):
                    if args.dry_run:
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
    logger.info(f"  エラー:                  {stats['errors']} 件")
    logger.info(f"\n  出力ファイル: {csv_path}")
    logger.info("=" * 60)


# =========================================================
# ヘルパー関数
# =========================================================

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
