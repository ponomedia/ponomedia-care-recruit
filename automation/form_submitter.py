"""
form_submitter.py — 問い合わせフォーム自動送信モジュール

注意: 送信前に必ずSalesGuardによる2重チェックを実施する。
     営業禁止サイトへの送信は物理的にブロックされる。
"""

import logging
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sales_guard import SalesGuard

logger = logging.getLogger(__name__)


class FormSubmitter:
    """
    問い合わせフォームの自動検出・送信クラス。

    処理フロー:
      1. facility_data["all_links"] からコンタクトフォームURLを探す
      2. フォームページをスクレイピングしてフィールドを解析
      3. SalesGuard Pass 2 チェック（フォームページ再検査）
      4. フィールドを分類して送信データを組み立て
      5. POSTリクエストを送信
    """

    # コンタクトフォームURLを示すキーワード（href・テキスト両方で検索）
    CONTACT_KEYWORDS = [
        "お問い合わせ", "問合せ", "お問合せ", "問い合わせ",
        "contact", "inquiry", "form",
    ]

    # ブラウザに偽装するためのUser-Agent
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, sales_guard: SalesGuard, wait_seconds: int = 3):
        """
        Args:
            sales_guard: SalesGuardインスタンス（Pass 2チェックに使用）
            wait_seconds: フォーム送信前後の待機秒数（礼儀的クロール）
        """
        self.sales_guard = sales_guard
        self.wait_seconds = wait_seconds

    # ------------------------------------------------------------------
    # Public Methods
    # ------------------------------------------------------------------

    def find_contact_form_url(self, facility_data: dict) -> Optional[str]:
        """
        スクレイピング済みデータからコンタクトフォームURLを探す。

        facility_data["all_links"] を走査し、hrefまたはリンクテキストに
        コンタクト系キーワードが含まれるリンクを返す。

        Args:
            facility_data: researcher.scrape_facility() が返す辞書

        Returns:
            コンタクトフォームURL文字列、見つからなければ None
        """
        if not facility_data:
            return None

        all_links = facility_data.get("all_links", [])
        base_url = facility_data.get("url", "")

        for link in all_links:
            href = link.get("href", "")
            text = link.get("text", "")

            href_lower = href.lower()
            text_str = text if text else ""

            # hrefまたはリンクテキストにキーワードが含まれるか確認
            href_match = any(kw.lower() in href_lower for kw in self.CONTACT_KEYWORDS)
            text_match = any(kw in text_str for kw in self.CONTACT_KEYWORDS)

            if href_match or text_match:
                # 相対URLを絶対URLに変換
                absolute_url = urljoin(base_url, href) if href else None
                if absolute_url:
                    logger.debug(f"コンタクトフォームURL発見: {absolute_url}")
                    return absolute_url

        logger.debug(f"コンタクトフォームURLが見つかりませんでした: {base_url}")
        return None

    def scrape_form_page(self, url: str, timeout: int = 10) -> Optional[dict]:
        """
        フォームページをスクレイピングし、フォーム構造を解析して返す。

        Args:
            url: フォームページのURL
            timeout: HTTPリクエストタイムアウト秒数

        Returns:
            {
                "page_text": str,       # ページ全テキスト
                "forms": list[dict],    # 検出されたフォームリスト
                "url": str,             # リクエストした実際のURL（リダイレクト後）
            }
            エラー時は None
        """
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
        except requests.exceptions.RequestException as e:
            logger.warning(f"フォームページ取得失敗 ({url}): {e}")
            return None

        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.text, "html.parser")

        # ページ全テキスト（Pass 2チェック用）
        page_text = " ".join(soup.get_text(separator=" ").split())

        # フォームを解析
        forms = self._parse_forms(soup, url)

        return {
            "page_text": page_text,
            "forms": forms,
            "url": resp.url,  # リダイレクト後の実URL
        }

    def submit_form(
        self,
        form_page_data: dict,
        message_subject: str,
        message_body: str,
        sender_name: str,
        sender_email: str,
    ) -> dict:
        """
        解析済みフォームデータを使って送信を実行する。

        最も適切なフォーム（テキストフィールドが多いもの）を選択し、
        フィールドを分類してPOSTデータを組み立てて送信する。

        Args:
            form_page_data: scrape_form_page() の返り値
            message_subject: メッセージ件名
            message_body: メッセージ本文
            sender_name: 送信者名
            sender_email: 送信者メールアドレス

        Returns:
            {"success": bool, "method": str, "reason": str}
        """
        forms = form_page_data.get("forms", [])
        page_url = form_page_data.get("url", "")

        if not forms:
            return {
                "success": False,
                "method": "form",
                "reason": "フォームが見つかりませんでした",
            }

        # 最も適切なフォームを選択（テキストフィールドが多いもの優先）
        best_form = self._select_best_form(forms)
        if not best_form:
            return {
                "success": False,
                "method": "form",
                "reason": "有効なフォーム（2フィールド以上）が見つかりませんでした",
            }

        # フィールドを分類してPOSTデータを構築
        post_data = {}
        for field in best_form.get("fields", []):
            value = self._classify_field(
                field_info=field,
                message=message_body,
                message_subject=message_subject,
                sender_name=sender_name,
                sender_email=sender_email,
            )
            if value is not None and field.get("name"):
                post_data[field["name"]] = value

        if not post_data:
            return {
                "success": False,
                "method": "form",
                "reason": "分類できるフィールドがありませんでした",
            }

        # フォームのアクションURL（絶対URL化）
        action_url = best_form.get("action", "")
        if not action_url:
            action_url = page_url
        else:
            action_url = urljoin(page_url, action_url)

        method = best_form.get("method", "POST").upper()

        logger.debug(f"フォーム送信先: {action_url} [{method}]")
        logger.debug(f"送信フィールド数: {len(post_data)}")

        # 送信前に少し待機（礼儀的クロール）
        time.sleep(self.wait_seconds)

        try:
            send_headers = {
                **self.HEADERS,
                "Referer": page_url,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            if method == "GET":
                resp = requests.get(
                    action_url,
                    params=post_data,
                    headers=send_headers,
                    timeout=15,
                    allow_redirects=True,
                )
            else:
                resp = requests.post(
                    action_url,
                    data=post_data,
                    headers=send_headers,
                    timeout=15,
                    allow_redirects=True,
                )

            # ステータスコード200〜399なら成功とみなす
            success = 200 <= resp.status_code < 400
            reason = f"HTTPステータス {resp.status_code}"

            return {
                "success": success,
                "method": method,
                "reason": reason,
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "method": method,
                "reason": f"送信中にネットワークエラー: {e}",
            }

    def submit_to_facility(
        self,
        facility_data: dict,
        contact_form_url: str,
        message_subject: str,
        message_body: str,
        sender_name: str,
        sender_email: str,
    ) -> dict:
        """
        施設へのフォーム送信のメインエントリーポイント。

        Pass 2（フォームページ再スキャン）を必ず実施し、
        営業禁止が検出された場合は物理的にブロックする。

        Args:
            facility_data: researcher.scrape_facility() の返り値
            contact_form_url: コンタクトフォームURL
            message_subject: 件名
            message_body: 本文
            sender_name: 送信者名
            sender_email: 送信者メールアドレス

        Returns:
            {
                "success": bool,
                "blocked": bool,    # 営業禁止によるブロック
                "reason": str,
            }
        """
        try:
            # フォームページをスクレイピング
            logger.info(f"  フォームページ取得中: {contact_form_url}")
            form_page_data = self.scrape_form_page(contact_form_url)

            if not form_page_data:
                result = {
                    "success": False,
                    "blocked": False,
                    "reason": "フォームページの取得に失敗しました",
                }
                logger.warning(f"  フォーム取得失敗: {contact_form_url}")
                return result

            # ============================================================
            # Pass 2チェック: フォームページを再スキャン（ハードブロック）
            # ============================================================
            pass2_result = self.sales_guard.check_form_page(form_page_data["page_text"])

            if pass2_result["is_prohibited"]:
                matched = pass2_result["matched_patterns"][:2]
                reason = f"営業禁止フォーム検出（Pass 2）: {matched}"
                logger.warning(f"  ★ BLOCKED (Pass 2): {contact_form_url} — {matched}")
                return {
                    "success": False,
                    "blocked": True,
                    "reason": reason,
                }

            # Pass 2 クリア → 送信実行
            logger.info(f"  Pass 2チェック通過。フォーム送信開始...")
            result = self.submit_form(
                form_page_data=form_page_data,
                message_subject=message_subject,
                message_body=message_body,
                sender_name=sender_name,
                sender_email=sender_email,
            )
            result["blocked"] = False

            if result["success"]:
                logger.info(f"  フォーム送信成功: {contact_form_url} ({result['reason']})")
            else:
                logger.warning(f"  フォーム送信失敗: {contact_form_url} ({result['reason']})")

            return result

        except Exception as e:
            # 予期しない例外をキャッチしてフォールバック（ブロックは解除しない）
            logger.error(f"  フォーム送信中に予期しないエラー ({contact_form_url}): {e}", exc_info=True)
            return {
                "success": False,
                "blocked": False,
                "reason": f"予期しないエラー: {e}",
            }

    # ------------------------------------------------------------------
    # 内部ヘルパーメソッド
    # ------------------------------------------------------------------

    def _parse_forms(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """
        BeautifulSoupオブジェクトから全フォームを解析してリストで返す。

        各フォームについて action/method とフィールド情報を抽出する。
        """
        forms = []
        for form_tag in soup.find_all("form"):
            action = form_tag.get("action", "")
            method = form_tag.get("method", "POST")

            fields = []
            # input・textarea・selectを収集
            for elem in form_tag.find_all(["input", "textarea", "select"]):
                field = self._extract_field_info(elem, form_tag)
                if field:
                    fields.append(field)

            forms.append({
                "action": action,
                "method": method.upper(),
                "fields": fields,
            })

        return forms

    def _extract_field_info(self, elem, form_tag: BeautifulSoup) -> Optional[dict]:
        """
        フォーム要素からフィールド情報を辞書で返す。

        label要素との対応付け（for属性またはラップ関係）も行う。
        """
        tag_name = elem.name
        field_type = elem.get("type", "text").lower() if tag_name == "input" else tag_name
        field_name = elem.get("name", "")
        field_id = elem.get("id", "")
        placeholder = elem.get("placeholder", "")
        value = elem.get("value", "")

        # submitボタンのvalueは変更しない
        if field_type in ("image", "button") and not field_name:
            return None

        # 対応するlabelテキストを探す
        label_text = ""
        if field_id:
            label_tag = form_tag.find("label", attrs={"for": field_id})
            if label_tag:
                label_text = label_tag.get_text(strip=True)

        # labelがfor属性で紐付けられていない場合、親labelを確認
        if not label_text:
            parent_label = elem.find_parent("label")
            if parent_label:
                label_text = parent_label.get_text(strip=True)

        return {
            "name": field_name,
            "type": field_type,
            "id": field_id,
            "placeholder": placeholder,
            "value": value,
            "label": label_text,
        }

    def _classify_field(
        self,
        field_info: dict,
        message: str,
        message_subject: str = "",
        sender_name: str = "",
        sender_email: str = "",
    ) -> Optional[str]:
        """
        フィールド情報（name・placeholder・label）からフィールドの用途を推定し、
        入力すべき値を返す。

        Args:
            field_info: _extract_field_info() が返す辞書
            message: 送信するメッセージ本文
            message_subject: 件名
            sender_name: 送信者名
            sender_email: 送信者メールアドレス

        Returns:
            フィールドに入力する値（str）、スキップすべき場合は None
        """
        field_type = field_info.get("type", "text").lower()
        name = (field_info.get("name") or "").lower()
        placeholder = (field_info.get("placeholder") or "").lower()
        label = (field_info.get("label") or "").lower()

        # hiddenフィールドは既存値をそのまま保持
        if field_type == "hidden":
            return field_info.get("value", "")

        # submit・button・imageはスキップ
        if field_type in ("submit", "button", "image", "reset"):
            return None

        # checkboxやradioは無視（デフォルト値のまま）
        if field_type in ("checkbox", "radio"):
            return None

        # 各フィールドで検索対象にするテキスト（name・placeholder・labelを結合）
        combined = f"{name} {placeholder} {label}"

        # --- 名前フィールド ---
        if any(kw in combined for kw in ["名前", "お名前", "氏名", "name", "担当者", "ご担当"]):
            return sender_name

        # --- 会社・施設・法人名フィールド ---
        if any(kw in combined for kw in ["会社", "施設", "法人", "organization", "company", "貴社", "御社"]):
            return "PonoMedia"

        # --- メールアドレスフィールド ---
        if any(kw in combined for kw in ["メール", "mail", "email", "e-mail", "メアド"]):
            return sender_email

        # --- 電話番号フィールド（コールドアウトリーチでは空欄） ---
        if any(kw in combined for kw in ["電話", "tel", "phone", "fax", "ファックス", "携帯"]):
            return ""  # 電話番号は入力しない

        # --- 件名フィールド ---
        if any(kw in combined for kw in ["件名", "subject", "タイトル", "title", "お問い合わせ件名"]):
            return message_subject

        # --- メッセージ本文フィールド ---
        if any(kw in combined for kw in [
            "内容", "メッセージ", "message", "body", "本文", "詳細",
            "お問い合わせ内容", "ご要望", "ご質問", "問い合わせ内容",
            "お問合せ内容", "textarea",
        ]):
            return message

        # フィールドタイプがtextareaの場合はデフォルトで本文を入れる
        if field_type == "textarea":
            return message

        # 分類できないフィールドはスキップ
        return None

    def _select_best_form(self, forms: list[dict]) -> Optional[dict]:
        """
        複数フォームから最も適切なものを選択する。

        - フィールド数が2未満のフォームは除外（検索・ログインフォーム等）
        - テキスト系フィールド数が最も多いフォームを選択
        """
        TEXT_TYPES = {"text", "email", "tel", "textarea", "select-one"}

        candidates = []
        for form in forms:
            fields = form.get("fields", [])
            # 有効なフィールド（submit/hidden/ボタン以外）をカウント
            fillable = [
                f for f in fields
                if f.get("type") not in ("submit", "button", "image", "reset", "hidden")
                and f.get("name")
            ]
            if len(fillable) < 2:
                # 入力フィールドが2つ未満はスキップ
                continue
            text_count = sum(
                1 for f in fields if f.get("type", "text") in TEXT_TYPES
            )
            candidates.append((text_count, form))

        if not candidates:
            return None

        # テキストフィールドが最も多いフォームを返す
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
