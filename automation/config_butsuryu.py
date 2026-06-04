"""
config_butsuryu.py — 物流・運送業向けパイプライン設定
"""
import os
from dotenv import load_dotenv
load_dotenv()

INDUSTRY = "butsuryu"
INDUSTRY_NAME = "物流・運送"

TARGET_AREAS = [
    ("千葉県千葉市",   None),
    ("千葉県船橋市",   None),
    ("千葉県市川市",   None),
    ("千葉県習志野市", None),
    ("千葉県柏市",     None),
    ("千葉県八千代市", None),
    ("千葉県浦安市",   None),
    ("千葉県松戸市",   None),
    ("千葉県流山市",   None),
    ("東京都江戸川区", None),
    ("東京都江東区",   None),
    ("東京都足立区",   None),
    ("東京都葛飾区",   None),
    ("東京都板橋区",   None),
    ("東京都練馬区",   None),
    ("東京都大田区",   None),
    ("東京都品川区",   None),
    ("東京都北区",     None),
    ("神奈川県川崎市", None),
    ("神奈川県横浜市", None),
    ("埼玉県さいたま市", None),
    ("埼玉県川口市",   None),
]

FACILITY_TYPES = [
    "運送会社",
    "配送センター",
    "物流センター",
    "宅配業者",
    "トラック運送",
    "倉庫業",
]

SEARCH_RESULTS_PER_QUERY = 5
MIN_SCORE_TO_CONTACT = 60

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDER_NAME        = "PonoMedia 物流採用支援"
SERVICE_URL        = os.getenv(
    "BUTSURYU_LP_URL",
    "https://ponomedia.github.io/ponomedia-care-recruit/sites/service-butsuryu/"
)
SAMPLE_SITE_URL    = os.getenv(
    "BUTSURYU_SAMPLE_URL",
    "https://ponomedia.github.io/ponomedia-care-recruit/sites/sample-butsuryu/"
)

WAIT_BETWEEN_REQUESTS = 2
WAIT_BETWEEN_EMAILS   = 30
OUTPUT_DIR = "output_butsuryu"
