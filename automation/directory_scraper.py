"""
directory_scraper.py — ハートページから施設名・電話番号を収集するモジュール

heartpage.jp の各エリア一覧ページから施設情報を取得し、
DDGで各施設の公式サイトURLを検索して返す。

heartpageエリアID一覧（主要）:
  千葉: chiba / ichikawa / funabashi / narashino / kashiwa / yachiyo / urayasu / ichihara
  東京: tokyochuo / minato / shinjuku / bunkyo / koto / shinagawa / meguro / tokyoota /
         setagaya / shibuya / suginami / toshima / tokyokita / arakawa / itabashi / nerima / edogawa
"""

import logging
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger(__name__)

# heartpage の施設種別 → type パラメータのマッピング
FACILITY_TYPE_PARAMS = {
    "デイサービス":         "type=day_service",
    "訪問介護":             "type=visit_care",
    "グループホーム":       "type=group_home",
    "住宅型有料老人ホーム": "type=nursing_home",
    "障害福祉サービス":     "type=disability",   # heartpageにない場合は空リストを返す
}

HEARTPAGE_BASE = "https://www.heartpage.jp"


class DirectoryScraper:
    """
    heartpage.jp から施設リストを取得し、公式サイトURLを特定するクラス。

    フロー:
      1. heartpage の一覧ページをスクレイピング → 施設名・電話・法人名を取得
      2. 各施設名 + エリア名で DDG 検索 → 公式サイト URL を特定
      3. {name, url, phone, area, facility_type} のリストを返す
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # 求人ポータル・大手サービスは除外
    EXCLUDE_DOMAINS = [
        # 求人ポータル
        "heartpage.jp", "indeed.com", "doda.jp", "mynavi.jp",
        "hellowork.go.jp", "job-medley.com", "townwork.net",
        "kaigojob.com", "kiracare.jp", "caresapo.jp",
        "hellowork-plus.com", "job-net.jp", "careermine.jp",
        "arubaito-ex.jp", "baitoru.com", "an-job.com", "r-staffing.jp",
        "recruit.co.jp", "en-japan.com", "nikkei.com",
        # 介護施設ディレクトリ・検索
        "ansinkaigo.jp", "lyxis.com", "kaigo.net", "kaigodb.com",
        "minnanokaigo.com", "carenavi.jp", "kaigo114.jp",
        "wam.go.jp", "kaigokensaku.mhlw.go.jp", "kaigo-map.net",
        "i-careservice.com", "carepro-navi.jp",
        "caremanagement.jp", "r-guide.jp", "kaigonohonne.com",
        "kaigo-ryoukin.com", "ninchisho-navi.net", "carely.org",
        "kaigo.homes.co.jp", "homes.co.jp", "caresul-kaigo.jp", "machbaito.jp",
        "oasisnavi.jp", "platinum-care.jp", "kaigodb.com",
        "kaigo-search.jp", "kaigopostnavi.jp",
        "woman-type.jp", "type.jp", "telnavi.jp", "sagasix.jp",
        "lovewalker.jp", "navitime.co.jp", "jorudan.co.jp",
        # 地図・電話帳
        "mapion.co.jp", "map.yahoo.co.jp", "navitime.co.jp",
        "iタウンページ", "itp.ne.jp", "phonebook", "ekiten.jp",
        "jalan.net", "tabelog.com", "hotpepper.jp",
        # 行政・公的機関
        "mhlw.go.jp", "mext.go.jp", "cao.go.jp",
        "pref.", "city.", ".lg.jp",
        # SNS・動画
        "facebook.com", "twitter.com", "instagram.com", "youtube.com",
        "tiktok.com", "line.me", "yelp.com",
        # 海外・大手
        "yahoo.co.jp", "google.com", "microsoft.com",
        "benesse-careeros.co.jp", "wikipedia.org",
        "ypsort.com", "locatefamily.com", "econstats.com",
        "textus-receptus.com", "elleyarns.com",
    ]

    def scrape_facilities(
        self,
        area_id: str,
        area_name: str,
        facility_type: str,
        max_per_page: int = 20,
        wait_seconds: int = 2,
    ) -> list[dict]:
        """
        heartpage の一覧ページから施設基本情報を収集する。

        Args:
            area_id: heartpage のエリアID（例: "yachiyo", "funabashi"）
            area_name: エリア表示名（例: "千葉県八千代市"）
            facility_type: 施設種別（config.FACILITY_TYPES の値）
            max_per_page: 1ページあたりの最大取得件数
            wait_seconds: リクエスト間隔

        Returns:
            施設情報リスト [{name, phone, address, area, facility_type, detail_url}]
        """
        type_param = FACILITY_TYPE_PARAMS.get(facility_type)
        if not type_param:
            logger.info(f"heartpage に対応パラメータなし: {facility_type} → スキップ")
            return []

        list_url = f"{HEARTPAGE_BASE}/{area_id}/list?{type_param}"
        logger.info(f"heartpage一覧取得: {list_url}")

        facilities = []

        try:
            resp = requests.get(list_url, headers=self.HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            # 施設ブロックを抽出（法人名 + 電話番号 + 事業所情報リンク）
            # heartpageは施設名が <strong> か見出しタグ、電話が dl/dd に入る構造
            facility_blocks = self._extract_facility_blocks(soup, area_id)

            for block in facility_blocks[:max_per_page]:
                block["area"] = area_name
                block["facility_type"] = facility_type
                facilities.append(block)

        except Exception as e:
            logger.warning(f"heartpageスクレイピングエラー ({list_url}): {e}")

        time.sleep(wait_seconds)
        return facilities

    def find_official_website(
        self,
        facility_name: str,
        facility_type: str,
        area_name: str,
        phone: str = "",
        wait_seconds: int = 2,
    ) -> Optional[str]:
        """
        施設名 + エリア名で DDG 検索して公式サイト URL を返す。

        Args:
            facility_name: 施設名
            facility_type: 施設種別
            area_name: エリア名
            phone: 電話番号（あれば検索精度向上に使用）
            wait_seconds: 検索後の待機秒数

        Returns:
            公式サイト URL、見つからなければ None
        """
        # 電話番号があれば精度向上
        if phone:
            query = f'"{facility_name}" {phone}'
        else:
            query = f'"{facility_name}" {area_name} {facility_type}'

        logger.debug(f"公式サイト検索: {query}")

        try:
            with DDGS() as ddgs:
                candidates = []
                for item in ddgs.text(query, max_results=15):
                    url = item.get("href", "")
                    if not url:
                        continue
                    if self._is_excluded(url):
                        continue
                    if not url.startswith("http"):
                        continue
                    candidates.append(url)

                # .jp ドメインのみ採用（外国サイトは返さない）
                jp_candidates = [u for u in candidates if self._is_jp_domain(u)]
                if jp_candidates:
                    url = jp_candidates[0]
                    logger.debug(f"  公式サイト候補: {url}")
                    time.sleep(wait_seconds)
                    return url
                # .jp が見つからなければ None を返す（要確認URLを量産しない）
                logger.debug(f"  .jpドメインが見つからず: {facility_name}")
        except Exception as e:
            logger.warning(f"DDG検索エラー ({facility_name}): {e}")

        time.sleep(wait_seconds)
        return None

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _extract_facility_blocks(self, soup: BeautifulSoup, area_id: str) -> list[dict]:
        """
        heartpage の一覧ページから施設ブロックを抽出する。

        heartpage の HTML 構造:
          - 施設ブロック: <div class="store item">
          - 施設名: 「事業所情報を見る」リンクの alt 属性
          - 電話番号: ブロックテキスト内「電話番号 XXXX-XXXX」パターン
          - 詳細リンク: href="/area_id/XXXXXXXX"
        """
        import re
        facilities = []

        # 「事業所情報を見る」テキストを含む <a> タグをすべて取得
        detail_links = [a for a in soup.find_all("a") if "事業所情報を見る" in a.get_text()]

        for link in detail_links:
            # 施設名は alt 属性から取得
            name = link.get("alt", "").strip()
            detail_url = urljoin(HEARTPAGE_BASE, link.get("href", ""))

            # 施設ブロック: div.store が親要素2つ上
            # link → div.dtl_btn → div.detail → div.store.item
            block = link.find_parent("div", class_="store")

            phone = ""
            address = ""

            if block:
                text = block.get_text(" ", strip=True)

                # 施設名をブロックの最初のテキストから取得（altがない場合）
                if not name:
                    lines = [t.strip() for t in text.split() if t.strip()]
                    if lines:
                        name = lines[0]

                # 電話番号: 「電話番号」の直後
                phone_match = re.search(
                    r"電話番号\s+([\d\-（）()]{9,15})", text
                )
                if phone_match:
                    phone = phone_match.group(1).strip()

                # 住所: 「所在地」の直後（「電話」「FAX」「受付」の前まで）
                addr_match = re.search(
                    r"所在地\s+(.+?)(?:電話番号|FAX|受付休業日|$)", text
                )
                if addr_match:
                    address = addr_match.group(1).strip()[:60]

            if name:
                facilities.append({
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "detail_url": detail_url,
                    "url": "",
                })

        return facilities

    def _is_excluded(self, url: str) -> bool:
        """求人ポータルや大手サービスのURLを除外する"""
        url_lower = url.lower()
        return any(d in url_lower for d in self.EXCLUDE_DOMAINS)

    def _is_jp_domain(self, url: str) -> bool:
        """URLが .jp ドメインまたは日本系プラットフォームかどうかを判定する"""
        from urllib.parse import urlparse
        try:
            host = urlparse(url).netloc.lower()
            if host.endswith(".jp"):
                return True
            # 日本のブログ・CMSプラットフォーム
            jp_platforms = ["ameblo.jp", "fc2.com", "wix.com", "jimdo.com",
                            "goope.jp", "localplace.jp"]
            return any(p in host for p in jp_platforms)
        except Exception:
            return False
