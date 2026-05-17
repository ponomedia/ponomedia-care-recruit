"""
researcher.py — 介護施設の検索・スクレイピングモジュール

DuckDuckGoで施設URLを収集し、各サイトから採用情報を抽出する。
"""

import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

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
        query = f"{facility_type} {area} 採用 求人"
        logger.info(f"検索クエリ: {query}")

        results = []
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    # 求人サイト・ポータルサイトは除外（施設自身のサイトを優先）
                    url = item.get("href", "")
                    if self._is_job_portal(url):
                        logger.debug(f"求人ポータルのためスキップ: {url}")
                        continue

                    facility = {
                        "name": self._extract_name_from_title(
                            item.get("title", ""), facility_type
                        ),
                        "url": url,
                        "snippet": item.get("body", ""),
                        "area": area,
                        "facility_type": facility_type,
                    }
                    results.append(facility)
                    logger.debug(f"  発見: {facility['name']} — {url}")

        except Exception as e:
            logger.warning(f"DuckDuckGo検索エラー ({query}): {e}")

        # 礼儀正しいクロールのため待機
        time.sleep(wait_seconds)
        return results

    def scrape_facility(self, url: str, timeout: int = 10) -> Optional[dict]:
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
        return data

    # ------------------------------------------------------------------
    # 内部ヘルパーメソッド
    # ------------------------------------------------------------------

    def _is_job_portal(self, url: str) -> bool:
        """求人ポータルサイトか判定する（施設公式サイト以外を除外）"""
        portals = [
            "indeed.com", "doda.jp", "mynavi.jp", "rikunabi.com",
            "hellowork.go.jp", "kaigo-job.net", "care-garden.jp",
            "job-medley.com", "kaigonohimitsu.com", "townwork.net",
            "baitoru.com", "shigoto.jp", "kaigojob.com", "s-kaigo.jp",
        ]
        url_lower = url.lower()
        return any(portal in url_lower for portal in portals)

    def _extract_name_from_title(self, title: str, facility_type: str) -> str:
        """検索結果タイトルから施設名を抽出する"""
        # パイプや全角パイプで区切られた最初の部分を施設名とみなす
        for separator in [" | ", " ｜ ", " - ", " – ", "｜", "|"]:
            if separator in title:
                return title.split(separator)[0].strip()
        return title.strip() or "不明施設"

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
