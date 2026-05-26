#!/usr/bin/env python3
"""
run_industry_pipeline.py — 業種別採用LP営業パイプライン
介護以外の業種（保育・建設・薬局・飲食）向けに既存パイプラインを流用する。

使い方:
    python run_industry_pipeline.py --industry hoiku
    python run_industry_pipeline.py --industry kensetsu
    python run_industry_pipeline.py --industry yakkyoku
    python run_industry_pipeline.py --industry inshoku
    python run_industry_pipeline.py --industry hoiku --dry-run
"""

import argparse
import importlib
import sys
import os

SUPPORTED_INDUSTRIES = {
    "hoiku":     "config_hoiku",
    "kensetsu":  "config_kensetsu",
    "yakkyoku":  "config_yakkyoku",
    "inshoku":   "config_inshoku",
}

def main():
    parser = argparse.ArgumentParser(description="業種別採用LP営業パイプライン")
    parser.add_argument("--industry", required=True, choices=SUPPORTED_INDUSTRIES.keys(),
                        help="対象業種: hoiku / kensetsu / yakkyoku / inshoku")
    parser.add_argument("--dry-run", action="store_true", help="送信せずに内容確認")
    parser.add_argument("--max-facilities", type=int, default=50)
    parser.add_argument("--rank-filter", type=str, default="A,B")
    args = parser.parse_args()

    # 業種別configをロードしてrun_pipelineのconfigとして差し込む
    config_module_name = SUPPORTED_INDUSTRIES[args.industry]
    industry_config = importlib.import_module(config_module_name)

    # run_pipeline.pyが使うconfigモジュールを動的に差し替え
    import config as default_config
    for attr in ["TARGET_AREAS", "FACILITY_TYPES", "SEARCH_RESULTS_PER_QUERY",
                 "MIN_SCORE_TO_CONTACT", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD",
                 "SENDER_NAME", "SERVICE_URL", "SAMPLE_SITE_URL",
                 "WAIT_BETWEEN_REQUESTS", "WAIT_BETWEEN_EMAILS", "OUTPUT_DIR"]:
        if hasattr(industry_config, attr):
            setattr(default_config, attr, getattr(industry_config, attr))

    # EmailGeneratorに業種を渡す
    from email_generator import EmailGenerator, INDUSTRY_CONFIG
    original_init = EmailGenerator.__init__
    industry = args.industry

    # EmailGeneratorに_industryを設定するパッチ
    _orig_generate = EmailGenerator.generate_outreach_email
    def _patched_generate(self, *a, **kw):
        self._industry = industry
        return _orig_generate(self, *a, **kw)
    EmailGenerator.generate_outreach_email = _patched_generate

    # outputディレクトリを業種別に作成
    output_dir = os.path.join(os.path.dirname(__file__), industry_config.OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    print(f"=== {industry_config.INDUSTRY_NAME}業種 採用LP営業パイプライン 開始 ===")
    print(f"  業種: {industry_config.INDUSTRY_NAME}")
    print(f"  ドライラン: {args.dry_run}")
    print(f"  最大施設数: {args.max_facilities}")

    # 既存のrun_pipeline.mainを引数を差し替えて実行
    sys.argv = [
        "run_pipeline.py",
        "--max-facilities", str(args.max_facilities),
        "--rank-filter", args.rank_filter,
    ]
    if args.dry_run:
        sys.argv.append("--dry-run")

    import run_pipeline
    run_pipeline.main()


if __name__ == "__main__":
    main()
