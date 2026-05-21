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
        "has_hiring_page": 10,          # 採用専用ページへのリンクあり（存在するだけ）
        "has_hiring_page_content": 15,  # 採用ページの中身が充実している（実際に読んだ）
        "has_form": 15,                 # 応募フォームあり（採用ページ上のもの優先）
        "has_job_details": 10,          # 給与・勤務条件の明示あり
        "has_mobile_support": 5,        # スマホ対応（viewportメタタグ）あり ← 基本的なので配点を下げる
        "has_faq": 10,                  # FAQ / よくある質問あり
        "has_experience_info": 10,      # 未経験歓迎・資格不問の記載あり
        "has_daily_schedule": 10,       # 1日の流れ・タイムラインあり
        "has_staff_voice": 10,          # スタッフの声・職員インタビューあり
        "has_multiple_positions": 5,    # 複数職種・複数募集あり
    }

    # 採用ページの弱点を説明する日本語メッセージ
    WEAKNESS_MESSAGES = {
        "has_hiring_page": "採用専用ページが見当たりません",
        "has_hiring_page_content": "採用ページの内容が薄い（詳細情報なし）",
        "has_form": "応募フォームが設置されていません",
        "has_job_details": "給与・勤務条件の明示がありません",
        "has_mobile_support": "スマホ対応が確認できません",
        "has_faq": "よくある質問（FAQ）が設置されていません",
        "has_experience_info": "未経験者・資格不問の説明がありません",
        "has_daily_schedule": "1日の流れ・タイムラインの掲載がありません",
        "has_staff_voice": "スタッフの声・職員インタビューがありません",
        "has_multiple_positions": "募集職種が1種類のみ（または不明）",
    }

    # 充実している場合の強み説明メッセージ
    STRENGTH_MESSAGES = {
        "has_hiring_page": "採用専用ページが存在する",
        "has_hiring_page_content": "採用ページの内容が充実している",
        "has_form": "応募フォームが設置済み",
        "has_job_details": "給与・勤務条件を明示済み",
        "has_mobile_support": "スマホ対応済み",
        "has_faq": "FAQページが設置済み",
        "has_experience_info": "未経験者向け説明が充実",
        "has_daily_schedule": "1日の流れを掲載済み",
        "has_staff_voice": "スタッフの声・インタビューあり",
        "has_multiple_positions": "複数職種・求人あり",
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
        hiring_links = facility_data.get("hiring_links", [])

        # 採用ページ本文（researcher が follow_hiring_page=True で取得した場合に存在）
        hiring_page_text = facility_data.get("hiring_page_text", "").lower()
        # トップ + 採用ページを合わせた評価テキスト
        combined_text = f"{full_text} {hiring_page_text}"

        # --- 各項目の有無を判定 ---

        # 採用専用ページリンクの有無（リンクが存在するだけ）
        has_hiring_page = len(hiring_links) > 0

        # 採用ページ本文の充実度（実際に採用ページを読めた場合のみ評価）
        # 充実した採用ページに特徴的な要素が3つ以上あれば「充実」と判定
        hiring_content_signals = [
            any(kw in hiring_page_text for kw in ["募集要項", "応募資格", "給与", "時給", "月給"]),
            any(kw in hiring_page_text for kw in ["未経験", "資格不問", "資格取得支援", "研修"]),
            any(kw in hiring_page_text for kw in ["スタッフの声", "職員インタビュー", "先輩の声", "インタビュー"]),
            any(kw in hiring_page_text for kw in ["1日の流れ", "一日の流れ", "タイムライン", "スケジュール"]),
            any(kw in hiring_page_text for kw in ["faq", "よくある質問", "q&a", "q＆a"]),
            len(hiring_page_text) > 1000,  # 1000文字以上の採用ページテキストがある
        ]
        has_hiring_page_content = hiring_page_text and sum(hiring_content_signals) >= 3

        # 応募フォームの有無（採用ページ上のものを優先）
        has_form = (
            facility_data.get("hiring_page_has_form", False)
            or facility_data.get("has_form", False)
        )

        # 給与・勤務条件キーワードの有無（採用ページ優先）
        job_keywords = ["給与", "時給", "月給", "勤務時間", "シフト", "手当", "賞与", "交通費"]
        has_job_details = any(kw in combined_text for kw in job_keywords)

        # スマホ対応（viewportメタタグ）の有無 — 基本的なので単独では重視しない
        has_mobile_support = facility_data.get("has_viewport", False)

        # FAQ / よくある質問の有無
        faq_keywords = ["faq", "よくある質問", "q&a", "q＆a", "よくある"]
        has_faq = any(kw in combined_text for kw in faq_keywords)

        # 未経験者向け情報の有無
        exp_keywords = ["未経験", "資格不問", "初心者", "経験不問", "未経験歓迎", "研修制度", "資格取得支援"]
        has_experience_info = any(kw in combined_text for kw in exp_keywords)

        # 1日の流れ・タイムラインの有無
        schedule_keywords = ["1日の流れ", "一日の流れ", "タイムライン", "スケジュール", "業務の流れ", "day in"]
        has_daily_schedule = any(kw in combined_text for kw in schedule_keywords)

        # スタッフの声・インタビューの有無（充実した採用サイトの特徴）
        voice_keywords = ["スタッフの声", "職員の声", "先輩の声", "スタッフインタビュー",
                          "職員インタビュー", "先輩インタビュー", "働く人の声", "社員の声"]
        has_staff_voice = any(kw in combined_text for kw in voice_keywords)

        # 複数職種・求人の有無（採用サイトが充実しているサイン）
        position_keywords = ["介護職員", "看護師", "ケアマネ", "相談員", "調理師", "事務",
                             "正社員", "パート", "アルバイト", "非常勤", "常勤"]
        position_hits = sum(1 for kw in position_keywords if kw in combined_text)
        has_multiple_positions = position_hits >= 3

        flags = {
            "has_hiring_page": has_hiring_page,
            "has_hiring_page_content": has_hiring_page_content,
            "has_form": has_form,
            "has_job_details": has_job_details,
            "has_mobile_support": has_mobile_support,
            "has_faq": has_faq,
            "has_experience_info": has_experience_info,
            "has_daily_schedule": has_daily_schedule,
            "has_staff_voice": has_staff_voice,
            "has_multiple_positions": has_multiple_positions,
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
            "has_hiring_page_content": flags.get("has_hiring_page_content", False),
            "has_form": flags.get("has_form", False),
            "has_job_details": flags.get("has_job_details", False),
            "has_mobile_support": flags.get("has_mobile_support", False),
            "has_faq": flags.get("has_faq", False),
            "has_experience_info": flags.get("has_experience_info", False),
            "has_daily_schedule": flags.get("has_daily_schedule", False),
            "has_staff_voice": flags.get("has_staff_voice", False),
            "has_multiple_positions": flags.get("has_multiple_positions", False),
            "weakness_reasons": weakness_reasons,
            "strengths": strengths,
            "rank": rank,
        }
