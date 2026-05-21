"""
sales_guard.py — 営業禁止サイト検出・ブロックモジュール

2重チェック構造：
  Pass 1: スクレイピング時にサイト全体をスキャン（researcher.pyから呼ばれる）
  Pass 2: フォーム送信直前に再スキャン（form_submitter.pyから呼ばれる）

どちらか1つでも引っかかれば送信を物理的にブロックする。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SalesGuard:
    """
    営業禁止検出クラス。

    正規表現パターンによる2段階チェックで、
    「営業お断り」サイトへの誤送信を物理的に防止する。
    """

    # 営業禁止を示す日本語正規表現パターン一覧
    PROHIBITED_PATTERNS: list[str] = [
        r"営業(目的|活動|行為|連絡|メール|電話|訪問).*?(お断り|禁止|ご遠慮|受け付け?ません|お控え)",
        r"(お断り|禁止|ご遠慮|受け付け?ません).*?営業(目的|活動|行為|連絡|メール)",
        r"営業(お断り|禁止)",
        r"セールス.{0,10}(お断り|禁止|ご遠慮)",
        r"勧誘.{0,10}(お断り|禁止|ご遠慮)",
        r"業者.{0,10}(お断り|ご遠慮|お控え)",
        r"求人広告.{0,20}(お断り|禁止|ご遠慮)",
        r"広告(掲載|営業).{0,10}(お断り|禁止)",
        r"採用.{0,10}営業.{0,10}(お断り|禁止|ご遠慮)",
        r"(取材|広告|営業|勧誘).{0,5}目的.*?お断り",
        r"フォームは.{0,20}(営業|勧誘|セールス).{0,10}(使用|利用).{0,10}(お断り|禁止|ご遠慮)",
        r"このフォーム.{0,30}(営業|勧誘|セールス)",
        # 追加: 変種・省略表現
        r"営業.{0,20}(一切|絶対).{0,10}(受け付け?ません|お断り|禁止)",
        r"営業目的以外",
        r"(営業|セールス|勧誘).{0,5}(電話|メール|訪問).{0,10}(固く|一切|絶対).{0,10}(お断り|禁止)",
        r"no\s+solicitation",
        r"sales?\s+(inquiry|contact|call).{0,20}(prohibited|not accepted|declined)",
        r"お問い合わせフォームは.{0,30}(営業|セールス|勧誘).{0,10}(使用|利用).{0,10}(できません|禁止|お断り)",
        r"営業(メール|電話).{0,10}(受け付けておりません|お断りしております)",
    ]

    # コンパイル済みパターンをクラス変数としてキャッシュ
    _compiled_patterns: Optional[list[re.Pattern]] = None

    def __init__(self):
        # 初回インスタンス生成時にパターンをコンパイルしてキャッシュ
        if SalesGuard._compiled_patterns is None:
            SalesGuard._compiled_patterns = [
                re.compile(p, re.IGNORECASE | re.DOTALL)
                for p in self.PROHIBITED_PATTERNS
            ]

    def check(self, text: str) -> dict:
        """
        テキスト（ページ全文、フォーム文言など）に営業禁止パターンが含まれるか検査する。

        Args:
            text: 検査対象テキスト（任意の長さ）

        Returns:
            {
                "is_prohibited": bool,
                "matched_patterns": list[str],  # マッチした実際のテキストスニペット
                "confidence": str,              # "HIGH" / "MEDIUM" / "LOW"
            }
        """
        if not text:
            return {
                "is_prohibited": False,
                "matched_patterns": [],
                "confidence": "LOW",
            }

        matched_snippets: list[str] = []

        for pattern in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                # マッチ前後を含む最大80文字のスニペットを記録（ログ確認用）
                start = max(0, match.start() - 10)
                end = min(len(text), match.end() + 10)
                snippet = text[start:end].strip()
                matched_snippets.append(snippet)

        is_prohibited = len(matched_snippets) > 0

        # マッチ数に応じた信頼度判定
        if len(matched_snippets) >= 3:
            confidence = "HIGH"
        elif len(matched_snippets) >= 1:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return {
            "is_prohibited": is_prohibited,
            "matched_patterns": matched_snippets,
            "confidence": confidence,
        }

    def check_page(self, facility_data: dict) -> dict:
        """
        スクレイピング済み施設データ全体を検査する（Pass 1用）。

        full_text・meta_description・titleを結合して包括的にチェックする。

        Args:
            facility_data: researcher.scrape_facility() が返す辞書

        Returns:
            check() と同じ構造の辞書
        """
        if not facility_data:
            return {
                "is_prohibited": False,
                "matched_patterns": [],
                "confidence": "LOW",
            }

        # 複数フィールドを結合して一括検査
        combined_text_parts = []

        full_text = facility_data.get("full_text", "")
        if full_text:
            combined_text_parts.append(full_text)

        meta_desc = facility_data.get("meta_description", "")
        if meta_desc:
            combined_text_parts.append(meta_desc)

        title = facility_data.get("title", "")
        if title:
            combined_text_parts.append(title)

        combined = " ".join(combined_text_parts)
        return self.check(combined)

    def check_form_page(self, form_page_text: str) -> dict:
        """
        問い合わせ・コンタクトフォームページのテキストを検査する（Pass 2用）。

        フォームページには「このフォームでの営業はご遠慮ください」のような
        文言が入ることがあるため、専用メソッドとして分離している。

        Args:
            form_page_text: フォームページの全テキスト

        Returns:
            check() と同じ構造の辞書
        """
        return self.check(form_page_text)

    @staticmethod
    def is_safe_to_contact(pass1_result: dict, pass2_result: dict) -> bool:
        """
        Pass 1・Pass 2 両方の結果を受け取り、送信可否を最終判定する。

        どちらか一方でも営業禁止を検出していれば False を返す。
        この関数が唯一の「送信ゲート」であり、例外なく遵守すること。

        Args:
            pass1_result: check_page() の返り値（スクレイピング時のチェック）
            pass2_result: check_form_page() の返り値（送信直前のチェック）

        Returns:
            True: 送信安全 / False: 送信禁止
        """
        pass1_prohibited = pass1_result.get("is_prohibited", False)
        pass2_prohibited = pass2_result.get("is_prohibited", False)

        if pass1_prohibited:
            logger.warning(
                f"[SalesGuard] ★ BLOCKED by Pass 1: {pass1_result.get('matched_patterns', [])[:2]}"
            )
        if pass2_prohibited:
            logger.warning(
                f"[SalesGuard] ★ BLOCKED by Pass 2: {pass2_result.get('matched_patterns', [])[:2]}"
            )

        # 両方ともFalseの場合のみ送信許可
        return not pass1_prohibited and not pass2_prohibited
