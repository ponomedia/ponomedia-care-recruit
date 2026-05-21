"""
email_generator.py — パーソナライズ営業メール生成モジュール

【重要ルール】
- 相手施設のWebサイトの欠点を直接指摘しない
- 診断スコア・ランク・不足項目はメール本文に入れない
- 提案型・低姿勢・押し売りしない文体を維持する
- 採用保証の表現は絶対に含めない
"""

import logging

logger = logging.getLogger(__name__)

# 施設種別ごとのメール内で使う自然な表現
FACILITY_TYPE_CONTEXT = {
    "デイサービス": "デイサービスの採用では、職場の雰囲気、1日の流れ、未経験者へのサポート、見学希望への対応などを採用ページ上で整理しておくことで、応募前の不安を減らしやすくなります。",
    "訪問介護": "訪問介護の採用では、担当エリアの範囲、移動手段、未経験者へのフォロー体制などを事前に伝えることが、求職者の安心につながりやすいと考えております。",
    "グループホーム": "グループホームの採用では、夜勤の実態、利用者様との関わり方、未経験者向けのOJT体制などを採用ページ上でわかりやすく整理しておくことが重要です。",
    "住宅型有料老人ホーム": "有料老人ホームの採用では、施設の雰囲気、勤務シフト、職員の定着率や職場環境について事前に伝えることで、求職者が応募を検討しやすくなります。",
    "障害福祉サービス": "障害福祉サービスの採用では、支援内容の具体例、未経験からのキャリアパス、職場の雰囲気などを採用ページで整理しておくことが大切です。",
}

# 施設種別ごとの件名表現
FACILITY_TYPE_SUBJECT = {
    "デイサービス": "デイサービス職員採用ページの整備について",
    "訪問介護": "訪問介護職員採用ページの整備について",
    "グループホーム": "グループホーム職員採用ページの整備について",
    "住宅型有料老人ホーム": "介護職員採用ページの整備について",
    "障害福祉サービス": "福祉支援員採用ページの整備について",
}


class EmailGenerator:
    """施設ごとにパーソナライズされた営業メールを生成するクラス"""

    def generate_outreach_email(
        self,
        facility_name: str,
        facility_type: str,
        area: str,
        score_result: dict,
        service_lp_url: str = "",
        sample_site_url: str = "",
    ) -> dict:
        """
        初回アプローチメールを生成する。

        【禁止】メール本文に以下を入れない:
        - 施設サイトの欠点指摘（「〇〇がありません」「〇〇が見当たりません」）
        - スコア・ランク・診断結果の数値
        - 「課題があるかと存じます」「採用に困っているかと」等の決めつけ表現

        Args:
            facility_name: 施設名
            facility_type: 施設種別
            area: エリア名
            score_result: スコアリング結果（件名生成のみに使用、本文には反映しない）
            service_lp_url: サービスLPのURL（空の場合は省略）
            sample_site_url: サンプルサイトURL（空の場合は省略）

        Returns:
            {"subject": str, "body": str}
        """
        # 件名：施設名を入れて全施設で異なる件名にする（スパム判定防止）
        base_subject = FACILITY_TYPE_SUBJECT.get(facility_type, "介護職採用ページまわりの整備について")
        # 施設名の最初の8文字を件名に含める（長すぎる場合は省略）
        name_prefix = facility_name[:8] if facility_name and facility_name != "不明施設" else ""
        subject = f"{name_prefix}様 {base_subject}" if name_prefix else base_subject

        # 施設種別ごとの本文コンテキスト
        facility_context = FACILITY_TYPE_CONTEXT.get(
            facility_type,
            "介護職採用では、求人票だけでは職場の雰囲気や働き方が伝わりにくいことがあります。"
        )

        # URL行（設定済みの場合のみ表示）
        url_lines = []
        if service_lp_url:
            url_lines.append(f"▶ サービス詳細：{service_lp_url}")
        if sample_site_url:
            url_lines.append(f"▶ サンプルサイト：{sample_site_url}")
        url_section = ("\n" + "\n".join(url_lines)) if url_lines else ""

        body = f"""\
{facility_name}
採用ご担当者様

突然のご連絡失礼いたします。

介護・福祉事業所様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 介護採用支援と申します。

介護職採用では、求人票に給与や勤務時間を掲載するだけでは、求職者に「どんな職場なのか」「未経験でも働けそうか」「見学だけでも相談できるのか」が伝わりにくいことがあります。

{facility_context}

弊社では現在、導入事例づくりにご協力いただける事業所様限定で、

・採用専用ページ
・求人掲載用テキスト
・応募/見学フォーム
・SNS用採用画像
・応募後の返信テンプレート

をまとめて50,000円（税込55,000円）で制作しております。

採用人数や応募数を保証するものではありませんが、求人票だけでは伝わりにくい情報を整理し、自社で応募・見学希望を受けられる状態を整えるサービスです。{url_section}

もし採用ページまわりを見直す機会がございましたら、現在の求人ページや応募導線について、無料で簡単に確認いたします。

突然のご連絡で恐縮ですが、ご関心がございましたらご返信いただけますと幸いです。

何卒よろしくお願いいたします。

--
PonoMedia 介護採用支援
〒（連絡先はご返信メールにて対応いたします）
※ご不要の場合は本メールにご返信いただければ、以後ご連絡を差し上げません。"""

        logger.debug(f"メール生成完了: {facility_name} ({facility_type})")

        return {
            "subject": subject,
            "body": body,
        }

    def generate_followup_email(self, facility_name: str, facility_type: str = "") -> dict:
        """1週間後の追いメール（フォローアップ）を生成する。"""
        subject = FACILITY_TYPE_SUBJECT.get(facility_type, "介護職採用ページまわりの整備について") + "（再送）"

        body = f"""\
{facility_name}
採用ご担当者様

先日ご連絡差し上げました、PonoMedia 介護採用支援です。

先般のご案内メールはご覧いただけましたでしょうか。
ご多用のところ大変恐れ入ります。

採用ページや応募フォームまわりの整備について、ご関心がございましたら引き続き無料で確認いたします。お気軽にご返信いただけますと幸いです。

何卒よろしくお願いいたします。

--
PonoMedia 介護採用支援"""

        return {
            "subject": subject,
            "body": body,
        }
