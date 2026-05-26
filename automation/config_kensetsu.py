"""
config_kensetsu.py — 建設業・工務店向けパイプライン設定
"""
import os
from dotenv import load_dotenv
load_dotenv()

INDUSTRY = "kensetsu"
INDUSTRY_NAME = "建設"

TARGET_AREAS = [
    ("千葉県千葉市",   None),
    ("千葉県船橋市",   None),
    ("千葉県市川市",   None),
    ("千葉県習志野市", None),
    ("千葉県柏市",     None),
    ("千葉県八千代市", None),
    ("千葉県浦安市",   None),
    ("東京都江戸川区", None),
    ("東京都江東区",   None),
    ("東京都足立区",   None),
    ("東京都葛飾区",   None),
    ("東京都板橋区",   None),
    ("東京都練馬区",   None),
    ("東京都大田区",   None),
    ("東京都世田谷区", None),
    ("東京都杉並区",   None),
    ("東京都品川区",   None),
]

FACILITY_TYPES = [
    "工務店",
    "電気工事",
    "管工事",
    "内装工事",
    "塗装工事",
]

SEARCH_RESULTS_PER_QUERY = 5
MIN_SCORE_TO_CONTACT = 60

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDER_NAME        = "PonoMedia 建設採用支援"
SERVICE_URL        = os.getenv("KENSETSU_LP_URL", "")
SAMPLE_SITE_URL    = os.getenv("KENSETSU_SAMPLE_URL", "")

WAIT_BETWEEN_REQUESTS = 2
WAIT_BETWEEN_EMAILS   = 30
OUTPUT_DIR = "output_kensetsu"
