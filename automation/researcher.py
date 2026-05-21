"""
researcher.py — 介護施設の検索・スクレイピングモジュール

DuckDuckGoで施設URLを収集し、各サイトから採用情報を抽出する。
"""

import re
import time
import logging
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger(__name__)


class FacilityResearcher:
    """介護施設の検索とWebスクレイピングを担当するクラス"""

    # ブラウザに偽装するためのUser-Agentヘッダー
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # 採用ページと判断するキーワード
    HIRING_KEYWORDS_HREF = [
        "recruit", "career", "join", "staff", "saiyo", "kyujin",
        "採用", "求人", "スタッフ",
    ]
    HIRING_KEYWORDS_TEXT = [
        "採用情報", "求人情報", "スタッフ募集", "一緒に働く",
        "仲間募集", "採用", "求人", "募集要項",
    ]

    # 日本語電話番号パターン（固定・携帯）
    PHONE_PATTERN = re.compile(
        r"0\d{1,4}[-（\(]\d{1,4}[-）\)]\d{4}"
        r"|0[5789]0[-\s]?\d{4}[-\s]?\d{4}"
    )

    # メールアドレスパターン
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    )

    def search_facilities(
        self,
        area: str,
        facility_type: str,
        max_results: int = 5,
        wait_seconds: int = 2,
    ) -> list[dict]:
        """
        DuckDuckGoで介護施設を検索してURLリストを返す。

        Args:
            area: 検索対象エリア（例: "千葉県八千代市"）
            facility_type: 施設種別（例: "デイサービス"）
            max_results: 取得件数上限
            wait_seconds: 検索後の待機秒数

        Returns:
            施設情報dictのリスト
        """
        # 施設名+エリアで検索（採用・求人は含めない → ポータル混入を減らす）
        query = f"{facility_type} {area}"
        logger.info(f"検索クエリ: {query}")

        # 絞り込みのため検索件数を多めに取得してフィルタリング
        fetch_count = max_results * 4

        results = []
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=fetch_count):
                    url = item.get("href", "")
                    title = item.get("title", "")
                    snippet = item.get("body", "")

                    # 求人ポータルは除外
                    if self._is_job_portal(url):
                        logger.debug(f"求人ポータルのためスキップ: {url}")
                        continue

                    # 日本のサイト以外は除外（.jpドメインまたはJP関連コンテンツ）
                    if not self._is_likely_japanese_facility(url, title, snippet, facility_type, area):
                        logger.debug(f"介護施設でないためスキップ: {url}")
                        continue

                    facility = {
                        "name": self._extract_name_from_title(title, facility_type),
                        "url": url,
                        "snippet": snippet,
                        "area": area,
                        "facility_type": facility_type,
                    }
                    results.append(facility)
                    logger.debug(f"  発見: {facility['name']} — {url}")

                    if len(results) >= max_results:
                        break

        except Exception as e:
            logger.warning(f"DuckDuckGo検索エラー ({query}): {e}")

        # 礼儀正しいクロールのため待機
        time.sleep(wait_seconds)
        return results

    def scrape_facility(self, url: str, timeout: int = 10, follow_hiring_page: bool = True) -> Optional[dict]:
        """
        施設サイトをスクレイピングして採用関連情報を抽出する。

        Args:
            url: スクレイピング対象URL
            timeout: HTTPタイムアウト秒数

        Returns:
            抽出データのdict、エラー時はNone
        """
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=timeout)
            resp.raise_for_status()
            # 文字コードを自動検出
            resp.encoding = resp.apparent_encoding or "utf-8"
        except requests.exceptions.RequestException as e:
            logger.warning(f"スクレイピング失敗 ({url}): {e}")
            return None

        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.text, "html.parser")

        # ページ全文テキスト（空白・改行を正規化）
        full_text = " ".join(soup.get_text(separator=" ").split())

        # 全リンクを収集
        all_links = []
        for tag in soup.find_all("a", href=True):
            all_links.append({
                "href": tag["href"],
                "text": tag.get_text(strip=True),
            })

        # メタディスクリプション
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"]

        # メールアドレスを抽出（HTML全体から検索）
        emails = list(set(self.EMAIL_PATTERN.findall(resp.text)))
        # 画像ファイルや不正なメールを除外
        emails = [e for e in emails if not e.endswith((".png", ".jpg", ".gif", ".svg"))]

        # 電話番号を抽出
        phones = list(set(self.PHONE_PATTERN.findall(full_text)))

        # 採用ページリンクを抽出
        hiring_links = self._find_hiring_links(all_links, url)

        # フォームの有無を確認
        has_form = bool(soup.find("form"))

        # ビューポートメタタグの確認（スマホ対応）
        viewport_tag = soup.find("meta", attrs={"name": "viewport"})
        has_viewport = bool(viewport_tag)

        # 営業禁止チェック Pass 1（スクレイピング時）
        # 循環インポートを避けるため、ここでローカルインポートする
        from sales_guard import SalesGuard
        _guard = SalesGuard()
        _pass1 = _guard.check(full_text)
        if _pass1["is_prohibited"]:
            logger.warning(
                f"営業禁止サイト検出 (Pass 1): {url} — {_pass1['matched_patterns'][:2]}"
            )

        data = {
            "url": url,
            "title": soup.title.string.strip() if soup.title and soup.title.string else "",
            "meta_description": meta_desc,
            "full_text": full_text[:5000],  # 後続処理のため上限5000文字
            "all_links": all_links,
            "emails": emails,
            "phones": phones,
            "hiring_links": hiring_links,
            "has_form": has_form,
            "has_viewport": has_viewport,
            "html_length": len(resp.text),
            # Pass 1 営業禁止チェック結果
            "is_sales_prohibited": _pass1["is_prohibited"],
            "sales_guard_pass1": _pass1,
        }

        # 採用ページの中身を追加スクレイピング（最大1ページ）
        # トップページだけでは採用サイトの充実度を正しく評価できないため
        if follow_hiring_page and hiring_links:
            hiring_page_data = self._scrape_hiring_page(hiring_links, url, timeout)
            if hiring_page_data:
                data["hiring_page_text"] = hiring_page_data["text"]
                data["hiring_page_url"] = hiring_page_data["url"]
                data["hiring_page_has_form"] = hiring_page_data["has_form"]
                # 採用ページにもメールがあれば追加
                extra_emails = [e for e in hiring_page_data["emails"] if e not in data["emails"]]
                data["emails"] = data["emails"] + extra_emails

        return data

    # ------------------------------------------------------------------
    # 内部ヘルパーメソッド
    # ------------------------------------------------------------------

    def _is_job_portal(self, url: str) -> bool:
        """求人ポータル・施設ディレクトリサイトか判定する（施設公式サイト以外を除外）"""
        portals = [
            # 大手求人ポータル
            "indeed.com", "doda.jp", "mynavi.jp", "rikunabi.com",
            "hellowork.go.jp", "townwork.net", "baitoru.com", "shigoto.jp",
            # 介護専門求人ポータル
            "kaigo-job.net", "care-garden.jp", "job-medley.com",
            "kaigonohimitsu.com", "kaigojob.com", "s-kaigo.jp",
            "kiracare.jp", "kaigo-center.jp", "kaigoshigoto.com",
            "caresapo.jp", "kaigo-kyujin.com", "hitometubo.jp",
            "care-kyujin.net", "kaigo-matching.com", "kaigofukushi.com",
            "carepro.jp", "carenejp.com", "kaigo-yell.com",
            "smile-nurse.jp", "job-net.jp", "hw-jobs.careermine.jp",
            # ハローワーク関連・アグリゲーター
            "hellowork-plus.com", "hellowork-search.com", "hw-plus.com",
            "xn--pckua2a7gp15o89zb.com",
            # 介護施設ディレクトリ・一覧サイト
            "ansinkaigo.jp", "i-careservice.com", "lyxis.com",
            "kaigo.net", "kaigodb.com", "homecare.or.jp",
            "carekarte.jp", "e-nursingcare.com", "kaigo-map.net",
            "minnanokaigo.com", "kaigo-times.jp", "kaigokensaku.jp",
            "kaigo114.jp", "carenavi.jp", "fukushi.jp",
            "wam.go.jp", "kaigokensaku.mhlw.go.jp",
            # その他アグリゲーター
            "google.com/search", "yahoo.co.jp/search",
            "en-gage.net", "wantedly.com", "workplacejapan.com",
            "fukushishigoto.com", "fukushi-work.jp",
        ]
        url_lower = url.lower()
        if any(portal in url_lower for portal in portals):
            return True

        # URLに「一覧」「list」「search」「/area/」などが含まれる場合も除外
        # （施設名ではなくエリア一覧ページと判断）
        listing_patterns = [
            "/list", "/search", "/area/", "/chiba/", "/tokyo/",
            "/shokai/", "/category/", "/navi/", "/ranking/",
            "/p-chiba", "/p-tokyo", "/22", "/12",  # 都道府県コード
        ]
        import re
        # URLパスに市区町村コード相当（6桁以上の数字）のセグメントがあれば一覧ページと判断
        try:
            path = urlparse(url_lower).path
            segments = [s for s in path.split("/") if s]
            numeric_segments = sum(1 for s in segments if re.match(r"^\d{6,}$", s))
            if numeric_segments >= 1:
                return True
        except Exception:
            pass

        return False

    def _extract_name_from_title(self, title: str, facility_type: str) -> str:
        """検索結果タイトルから施設名を抽出する"""
        # パイプや全角パイプで区切られた最初の部分を施設名とみなす
        for separator in [" | ", " ｜ ", " - ", " – ", "｜", "|"]:
            if separator in title:
                return title.split(separator)[0].strip()
        return title.strip() or "不明施設"

    def _is_likely_japanese_facility(
        self, url: str, title: str, snippet: str, facility_type: str, area: str
    ) -> bool:
        """
        URLがエリアの介護施設サイトである可能性が高いか判定する。

        以下のいずれかを満たす場合に True を返す:
        - .jp / .co.jp ドメイン
        - タイトル・スニペットに施設種別またはエリア名が含まれる
        """
        url_lower = url.lower()

        # 明らかな海外大手サービスは除外
        exclude_domains = [
            "microsoft.com", "office.com", "google.com", "apple.com",
            "amazon.com", "facebook.com", "twitter.com", "youtube.com",
            "wikipedia.org", "github.com", "stackoverflow.com",
        ]
        if any(d in url_lower for d in exclude_domains):
            return False

        # .jpドメインはOK
        if ".jp" in url_lower:
            return True

        # タイトルまたはスニペットに施設種別・エリア名・介護キーワードが含まれる
        care_keywords = ["介護", "福祉", "デイ", "訪問", "グループホーム", "老人", "障害"]
        combined = f"{title} {snippet}"
        if any(kw in combined for kw in care_keywords):
            return True
        if area.replace("県", "").replace("市", "").replace("町", "") in combined:
            return True

        return False

    def _scrape_hiring_page(
        self, hiring_links: list[dict], base_url: str, timeout: int = 10
    ) -> Optional[dict]:
        """
        採用ページを1件スクレイピングして基本情報を返す。

        Args:
            hiring_links: _find_hiring_links() が返したリスト
            base_url: 施設トップページのURL（相対URLの解決に使用）
            timeout: HTTPタイムアウト秒数

        Returns:
            {"url", "text", "has_form", "emails"} または None
        """
        from urllib.parse import urljoin, urlparse

        for link in hiring_links[:3]:  # 最大3候補を試みる
            href = link.get("href", "")
            if not href:
                continue

            # 相対URLを絶対URLに変換
            if href.startswith("http"):
                target_url = href
            else:
                target_url = urljoin(base_url, href)

            # 外部ドメインには飛ばない（施設公式サイト内のみ）
            base_host = urlparse(base_url).netloc
            target_host = urlparse(target_url).netloc
            if base_host and target_host and base_host != target_host:
                logger.debug(f"採用ページが別ドメインのためスキップ: {target_url}")
                continue

            # 同一ページへのループを防ぐ
            if target_url.rstrip("/") == base_url.rstrip("/"):
                continue

            try:
                resp = requests.get(target_url, headers=self.HEADERS, timeout=timeout)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                soup = BeautifulSoup(resp.text, "lxml")
                text = " ".join(soup.get_text(separator=" ").split())
                has_form = bool(soup.find("form"))
                emails = list(set(self.EMAIL_PATTERN.findall(resp.text)))
                emails = [e for e in emails if not e.endswith((".png", ".jpg", ".gif", ".svg"))]
                logger.debug(f"採用ページスクレイピング成功: {target_url} ({len(text)}字)")
                return {
                    "url": target_url,
                    "text": text[:5000],
                    "has_form": has_form,
                    "emails": emails,
                }
            except Exception as e:
                logger.debug(f"採用ページ取得失敗 ({target_url}): {e}")
                continue

        return None

    def _find_hiring_links(self, links: list[dict], base_url: str) -> list[dict]:
        """採用・求人関連のリンクを抽出する"""
        hiring = []
        for link in links:
            href = link["href"].lower()
            text = link["text"]

            href_match = any(kw in href for kw in self.HIRING_KEYWORDS_HREF)
            text_match = any(kw in text for kw in self.HIRING_KEYWORDS_TEXT)

            if href_match or text_match:
                hiring.append(link)

        return hiring
