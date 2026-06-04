"""
config_seisou.py — 清掃・ビルメンテナンス業向けパイプライン設定
"""
import os
from dotenv import load_dotenv
load_dotenv()

INDUSTRY = "seisou"
INDUSTRY_NAME = "清掃・ビルメン"

TARGET_AREAS = [
    ("東京都新宿区",   None),
    ("東京都渋谷区",   None),
    ("東京都千代田区", None),
    ("東京都中央区",   None),
    ("東京都港区",     None),
    ("東京都品川区",   None),
    ("東京都大田区",   None),
    ("東京都江東区",   None),
    ("東京都江戸川区", None),
    ("東京都足立区",   None),
    ("東京都板橋区",   None),
    ("東京都練馬区",   None),
    ("東京都世田谷区", None),
    ("千葉県千葉市",   None),
    ("千葉県船橋市",   None),
    ("千葉県市川市",   None),
    ("神奈川県横浜市", None),
    ("神奈川県川崎市", None),
    ("埼玉県さいたま市", None),
]

FACILITY_TYPES = [
    "ビル清掃",
    "清掃会社",
    "ハウスクリーニング",
    "ビルメンテナンス",
    "施設管理",
    "清掃業者",
]

SEARCH_RESULTS_PER_QUERY = 5
MIN_SCORE_TO_CONTACT = 60

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDER_NAME        = "PonoMedia 清掃採用支援"
SERVICE_URL        = os.getenv(
    "SEISOU_LP_URL",
    "https://ponomedia.github.io/ponomedia-care-recruit/sites/service-seisou/"
)
SAMPLE_SITE_URL    = os.getenv(
    "SEISOU_SAMPLE_URL",
    "https://ponomedia.github.io/ponomedia-care-recruit/sites/sample-seisou/"
)

WAIT_BETWEEN_REQUESTS = 2
WAIT_BETWEEN_EMAILS   = 30
OUTPUT_DIR = "output_seisou"
