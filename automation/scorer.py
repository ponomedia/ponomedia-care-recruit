"""
scorer.py — 介護施設採用ページの弱点スコアリングモジュール

スコアが低い（0に近い）ほど採用ページが貧弱 = 支援の余地が大きい見込み客
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HiringPageScorer:
    """
    施設Webサイトの採用ページ充実度を0〜100点でスコアリングする。

    低スコア = 採用ページが弱い = PonoMediaのサービスが刺さる見込み客
    高スコア = 採用ページが充実 = 優先度低
    """

    # スコアリング配点
    SCORE_WEIGHTS = {
        "has_hiring_page": 15,      # 採用専用ページへのリンクあり
        "has_form": 15,             # 応募フォームあり
        "has_phone": 10,            # 電話番号の記載あり
        "has_email_contact": 10,    # メールアドレスの記載あり
        "has_job_details": 10,      # 給与・勤務条件の明示あり
        "has_mobile_support": 10,   # スマホ対応（viewportメタタグ）あり
        "has_faq": 10,              # FAQ / よくある質問あり
        "has_experience_info": 10,  # 未経験歓迎・資格不問の記載あり
        "has_daily_schedule": 10,   # 1日の流れ・タイムラインあり
    }

    # 採用ページの弱点を説明する日本語メッセージ
    WEAKNESS_MESSAGES = {
        "has_hiring_page": "採用専用ページが見当たりません",
        "has_form": "応募フォームが設置されていません",
        "has_phone": "採用用の電話番号が確認できません",
        "has_email_contact": "問い合わせメールアドレスが見当たりません",
        "has_job_details": "給与・勤務条件の明示がありません",
        "has_mobile_support": "スマホ対応が確認できません",
        "has_faq": "よくある質問（FAQ）が設置されていません",
        "has_experience_info": "未経験者・資格不問の説明がありません",
        "has_daily_schedule": "1日の流れ・タイムラインの掲載がありません",
    }

    # 充実している場合の強み説明メッセージ
    STRENGTH_MESSAGES = {
        "has_hiring_page": "採用専用ページが存在する",
        "has_form": "応募フォームが設置済み",
        "has_phone": "採用用電話番号を掲載済み",
        "has_email_contact": "問い合わせメールを掲載済み",
        "has_job_details": "給与・勤務条件を明示済み",
        "has_mobile_support": "スマホ対応済み",
        "has_faq": "FAQページが設置済み",
        "has_experience_info": "未経験者向け説明が充実",
        "has_daily_schedule": "1日の流れを掲載済み",
    }

    def score(self, facility_data: Optional[dict]) -> dict:
        """
        スクレイピングデータをもとに採用ページの充実度をスコアリングする。

        Args:
            facility_data: researcher.pyのscrape_facility()が返すdict（Noneの場合は最低スコア）

        Returns:
            スコアリング結果のdict
        """
        # スクレイピング失敗時は最低スコアを返す
        if facility_data is None:
            return self._make_result(
                flags={k: False for k in self.SCORE_WEIGHTS},
                extra_notes=["サイトの取得に失敗しました"],
            )

        full_text = facility_data.get("full_text", "").lower()
        links = facility_data.get("all_links", [])
        hiring_links = facility_data.get("hiring_links", [])

        # --- 各項目の有無を判定 ---

        # 採用専用ページリンクの有無
        has_hiring_page = len(hiring_links) > 0

        # 応募フォームの有無
        has_form = facility_data.get("has_form", False)

        # 電話番号の有無
        has_phone = len(facility_data.get("phones", [])) > 0

        # メールアドレスの有無
        has_email_contact = len(facility_data.get("emails", [])) > 0

        # 給与・勤務条件キーワードの有無
        job_keywords = ["給与", "時給", "月給", "勤務", "勤務時間", "時間帯", "シフト"]
        has_job_details = any(kw in full_text for kw in job_keywords)

        # スマホ対応（viewportメタタグ）の有無
        has_mobile_support = facility_data.get("has_viewport", False)

        # FAQ / よくある質問の有無
        faq_keywords = ["faq", "よくある質問", "q&a", "q＆a", "よくある"]
        has_faq = any(kw in full_text for kw in faq_keywords)

        # 未経験者向け情報の有無
        exp_keywords = ["未経験", "資格不問", "初心者", "経験不問", "未経験歓迎", "研修制度", "資格取得支援"]
        has_experience_info = any(kw in full_text for kw in exp_keywords)

        # 1日の流れ・タイムラインの有無
        schedule_keywords = ["1日の流れ", "一日の流れ", "タイムライン", "スケジュール", "業務の流れ", "day in"]
        has_daily_schedule = any(kw in full_text for kw in schedule_keywords)

        flags = {
            "has_hiring_page": has_hiring_page,
            "has_form": has_form,
            "has_phone": has_phone,
            "has_email_contact": has_email_contact,
            "has_job_details": has_job_details,
            "has_mobile_support": has_mobile_support,
            "has_faq": has_faq,
            "has_experience_info": has_experience_info,
            "has_daily_schedule": has_daily_schedule,
        }

        return self._make_result(flags)

    # ------------------------------------------------------------------
    # 内部ヘルパーメソッド
    # ------------------------------------------------------------------

    def _make_result(self, flags: dict, extra_notes: list = None) -> dict:
        """スコア計算とランク判定をまとめて行う"""

        # スコア計算（各項目のフラグが True なら加点）
        total_score = sum(
            self.SCORE_WEIGHTS[key]
            for key, present in flags.items()
            if present
        )

        # 弱点リスト（フラグがFalseの項目を弱点として列挙）
        weakness_reasons = [
            self.WEAKNESS_MESSAGES[key]
            for key, present in flags.items()
            if not present
        ]
        if extra_notes:
            weakness_reasons.extend(extra_notes)

        # 強みリスト（フラグがTrueの項目）
        strengths = [
            self.STRENGTH_MESSAGES[key]
            for key, present in flags.items()
            if present
        ]

        # ランク判定
        if total_score < 40:
            rank = "A"  # 採用ページが非常に弱い = 最優先アプローチ
        elif total_score < 70:
            rank = "B"  # 一部あるが不完全 = アプローチ対象
        else:
            rank = "C"  # 充実している = スキップ

        logger.debug(
            f"スコア: {total_score}/100 | ランク: {rank} | "
            f"弱点数: {len(weakness_reasons)}"
        )

        return {
            "total_score": total_score,
            "has_hiring_page": flags.get("has_hiring_page", False),
            "has_form": flags.get("has_form", False),
            "has_phone": flags.get("has_phone", False),
            "has_email_contact": flags.get("has_email_contact", False),
            "has_job_details": flags.get("has_job_details", False),
            "has_mobile_support": flags.get("has_mobile_support", False),
            "has_faq": flags.get("has_faq", False),
            "has_experience_info": flags.get("has_experience_info", False),
            "has_daily_schedule": flags.get("has_daily_schedule", False),
            "weakness_reasons": weakness_reasons,
            "strengths": strengths,
            "rank": rank,
        }
