"""
form_submitter.py — 問い合わせフォーム自動送信モジュール

注意: 送信前に必ずSalesGuardによる2重チェックを実施する。
     営業禁止サイトへの送信は物理的にブロックされる。

フォームタイプチェック（入居者向けフォームへの誤送信防止）:
  Pass 1: URL選択時に入居者向けキーワードを除外 / 採用・業者向けを優先
  Pass 2: フォームページ取得後に内部ルールでフォームタイプを確認
  Pass 3: CODEXで「入居者向けか？業者・採用向けか？」をダブルチェック
"""

import logging
import subprocess
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sales_guard import SalesGuard

logger = logging.getLogger(__name__)

# 入居希望者向けフォームを示すキーワード（URLおよびページテキストで使用）
RESIDENT_FORM_KEYWORDS = [
    "入居相談", "入居のご相談", "入居を希望", "入居をお考え", "入居申込",
    "入居に関する", "施設への入居", "入居について",
    "見学予約", "見学のご予約", "見学申込",
    "資料請求", "資料のご請求", "資料をご請求",
    "空室確認", "空室状況", "入居費用",
    "ご入居", "ご見学",
]

# 採用・業者向けフォームを優先するキーワード（URLおよびリンクテキスト）
# ★ 汎用的な「お問い合わせ」は含めない（fallbackで拾う）
PREFERRED_FORM_KEYWORDS = [
    "採用", "求人", "saiyo", "recruit", "career",
    "業者", "取引先", "事業者", "法人",
]


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

        優先順位:
          1. 採用・業者・一般お問い合わせ向けのフォーム（最優先）
          2. 一般的なお問い合わせフォーム
          NG: 入居相談・見学予約・資料請求フォームは除外

        Args:
            facility_data: researcher.scrape_facility() が返す辞書

        Returns:
            コンタクトフォームURL文字列、見つからなければ None
        """
        if not facility_data:
            return None

        all_links = facility_data.get("all_links", [])
        base_url = facility_data.get("url", "")

        preferred_url = None   # 採用・業者向け（最優先）
        fallback_url = None    # 一般お問い合わせ（次点）

        for link in all_links:
            href = link.get("href", "")
            text = link.get("text", "") or ""

            href_lower = href.lower()
            combined = f"{href_lower} {text}"

            # ★ 入居者向けフォームは絶対に除外（URLとテキスト両方でチェック）
            if any(kw in combined for kw in RESIDENT_FORM_KEYWORDS):
                logger.debug(f"入居者向けフォームのためスキップ: {href} ({text})")
                continue

            # コンタクト系キーワードが含まれるか
            href_match = any(kw.lower() in href_lower for kw in self.CONTACT_KEYWORDS)
            text_match = any(kw in text for kw in self.CONTACT_KEYWORDS)

            if not (href_match or text_match):
                continue

            absolute_url = urljoin(base_url, href) if href else None
            if not absolute_url:
                continue

            # 採用・業者向けキーワードがあれば最優先
            if any(kw in combined for kw in PREFERRED_FORM_KEYWORDS):
                if preferred_url is None:
                    preferred_url = absolute_url
                    logger.debug(f"採用/業者向けフォームURL発見（優先）: {absolute_url}")
            elif fallback_url is None:
                fallback_url = absolute_url
                logger.debug(f"一般お問い合わせフォームURL発見（次点）: {absolute_url}")

        result = preferred_url or fallback_url
        if result:
            logger.debug(f"使用するフォームURL: {result}")
        else:
            logger.debug(f"コンタクトフォームURLが見つかりませんでした: {base_url}")
        return result

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
            # Pass 2a: 営業禁止フォームチェック（ハードブロック）
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

            # ============================================================
            # Pass 2b: フォームタイプ内部チェック（入居者向けフォーム検出）
            # ============================================================
            resident_check = self._check_form_is_resident_type(
                form_page_data["page_text"], form_page_data.get("forms", [])
            )
            if resident_check["is_resident"]:
                logger.warning(
                    f"  ★ BLOCKED (入居者向けフォーム検出): {contact_form_url}"
                    f" — {resident_check['reason']}"
                )
                return {
                    "success": False,
                    "blocked": True,
                    "reason": f"入居者向けフォームのため送信不可: {resident_check['reason']}",
                }

            # ============================================================
            # Pass 2c: CODEX フォームタイプダブルチェック（グレーな場合）
            # ============================================================
            if resident_check.get("uncertain"):
                codex_ok = self._codex_form_type_check(
                    contact_form_url, form_page_data["page_text"],
                    form_page_data.get("forms", [])
                )
                if not codex_ok:
                    logger.warning(
                        f"  ★ BLOCKED (CODEX: 入居者向けフォームと判定): {contact_form_url}"
                    )
                    return {
                        "success": False,
                        "blocked": True,
                        "reason": "CODEX確認: 入居希望者向けフォームのため送信不可",
                    }

            # 全チェック通過 → 送信実行
            logger.info(f"  フォームタイプ・Pass 2チェック通過。フォーム送信開始...")
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

    def _check_form_is_resident_type(
        self, page_text: str, forms: list[dict]
    ) -> dict:
        """
        フォームページのテキストとフォームフィールドから、
        入居希望者向けフォームかどうかを内部ルールで判定する。

        Returns:
            {
                "is_resident": bool,   # 確実に入居者向け → ブロック
                "uncertain": bool,     # グレー → CODEXに回す
                "reason": str,
            }
        """
        text_lower = page_text.lower()

        # フォームのフィールドラベルも含めてチェック
        field_labels = []
        for form in forms:
            for field in form.get("fields", []):
                label = field.get("label", "")
                placeholder = field.get("placeholder", "")
                if label:
                    field_labels.append(label)
                if placeholder:
                    field_labels.append(placeholder)
        labels_combined = " ".join(field_labels).lower()
        combined = f"{text_lower} {labels_combined}"

        # 確実に入居者向けのキーワードが複数あればブロック
        resident_hits = [kw for kw in RESIDENT_FORM_KEYWORDS if kw in combined]
        if len(resident_hits) >= 2:
            return {
                "is_resident": True,
                "uncertain": False,
                "reason": f"入居者向けキーワード検出: {resident_hits[:3]}",
            }

        # フォームラベルに入居者向けキーワードが1つでもあれば確実にNG
        label_hits = [kw for kw in RESIDENT_FORM_KEYWORDS if kw in labels_combined]
        if label_hits:
            return {
                "is_resident": True,
                "uncertain": False,
                "reason": f"フォームフィールドに入居者向けキーワード: {label_hits[:2]}",
            }

        # 1つだけ該当 → グレー（CODEX確認）
        if len(resident_hits) == 1:
            return {
                "is_resident": False,
                "uncertain": True,
                "reason": f"要確認キーワード: {resident_hits}",
            }

        return {"is_resident": False, "uncertain": False, "reason": "内部チェック通過"}

    def _codex_form_type_check(
        self, form_url: str, page_text: str, forms: list[dict]
    ) -> bool:
        """
        CODEXを使って「このフォームは入居希望者向けか、業者・採用向けか」を確認する。

        Returns:
            True  → 業者・採用向け（送信してよい）
            False → 入居者向けまたは不明（ブロック）
        """
        # フォームのフィールドラベルを収集
        field_labels = []
        for form in forms:
            for field in form.get("fields", []):
                label = field.get("label", "")
                placeholder = field.get("placeholder", "")
                if label:
                    field_labels.append(label)
                if placeholder:
                    field_labels.append(placeholder)

        text_preview = page_text[:600]
        labels_str = " / ".join(field_labels[:10]) or "（取得できず）"

        prompt = (
            f"以下のWebフォームページの情報を見て、このフォームが何のためのものかを判定してください。\n\n"
            f"フォームURL: {form_url}\n"
            f"ページ本文冒頭: {text_preview}\n"
            f"フォームのフィールドラベル: {labels_str}\n\n"
            f"【判定基準】\n"
            f"BUSINESS — 一般的なお問い合わせ・採用・業者向け・事業者向けのフォーム\n"
            f"RESIDENT — 入居希望者・ご家族向けのフォーム（入居相談・見学予約・資料請求等）\n"
            f"UNCLEAR  — 判断できない\n\n"
            f"以下のいずれか1語のみで答えてください: BUSINESS / RESIDENT / UNCLEAR"
        )

        try:
            result = subprocess.run(
                [
                    "codex", "exec",
                    "-c", 'sandbox_permissions=["disk-full-read-access"]',
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
            output = (result.stdout + result.stderr).upper()
            logger.info(f"[CODEXフォームタイプ] {form_url}: {output[:80]}")

            if "BUSINESS" in output:
                return True   # 送信OK
            # RESIDENT / UNCLEAR / エラー → 安全方向へ（ブロック）
            return False

        except subprocess.TimeoutExpired:
            logger.warning(f"[CODEXフォームタイプ] タイムアウト: {form_url} — ブロック")
            return False
        except FileNotFoundError:
            logger.warning("[CODEXフォームタイプ] codexコマンド未インストール — ブロック（安全方向）")
            return False
        except Exception as e:
            logger.warning(f"[CODEXフォームタイプ] エラー: {e} — ブロック（安全方向）")
            return False

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
