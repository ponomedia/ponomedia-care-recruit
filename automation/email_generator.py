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

# 業種別 送信者名・件名・本文コンテキスト
INDUSTRY_CONFIG = {
    "hoiku": {
        "sender_name": "PonoMedia 保育採用支援",
        "intro": "保育所・認定こども園様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 保育採用支援と申します。",
        "problem": "保育士採用では、求人票に給与や勤務時間を掲載するだけでは、求職者に「どんな園の雰囲気か」「未経験でも働けるか」「見学だけでも相談できるか」が伝わりにくいことがあります。",
        "default_subject": "保育士採用ページの整備について",
    },
    "kensetsu": {
        "sender_name": "PonoMedia 建設採用支援",
        "intro": "工務店・建設会社様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 建設採用支援と申します。",
        "problem": "建設業の採用では、求人票に給与や勤務条件を掲載するだけでは、求職者に「どんな現場・会社か」「未経験から育ててもらえるか」「働き方改革への取組み」が伝わりにくいことがあります。",
        "default_subject": "現場スタッフ採用ページの整備について",
    },
    "yakkyoku": {
        "sender_name": "PonoMedia 薬局採用支援",
        "intro": "調剤薬局様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 薬局採用支援と申します。",
        "problem": "薬局の採用では、求人票に給与や勤務時間を掲載するだけでは、求職者に「どんな薬局の雰囲気か」「調剤件数や業務量は」「スタッフの働きやすさ」が伝わりにくいことがあります。",
        "default_subject": "薬剤師・薬局スタッフ採用ページの整備について",
    },
    "inshoku": {
        "sender_name": "PonoMedia 飲食採用支援",
        "intro": "飲食店様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 飲食採用支援と申します。",
        "problem": "飲食店の採用では、求人票に時給や勤務時間を掲載するだけでは、求職者に「どんなお店の雰囲気か」「シフトの融通は利くか」「未経験でも大丈夫か」が伝わりにくいことがあります。",
        "default_subject": "飲食スタッフ採用ページの整備について",
    },
}

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
        # 業種設定を取得（industryキーがあれば業種別、なければ介護デフォルト）
        industry = getattr(self, "_industry", None)
        ind_cfg = INDUSTRY_CONFIG.get(industry, {}) if industry else {}
        sender_name = ind_cfg.get("sender_name", "PonoMedia 介護採用支援")
        intro_text  = ind_cfg.get("intro", "介護・福祉事業所様向けに、採用ページや求人文、応募フォームの整備を行っております、PonoMedia 介護採用支援と申します。")
        problem_text = ind_cfg.get("problem", "介護職採用では、求人票に給与や勤務時間を掲載するだけでは、求職者に「どんな職場なのか」「未経験でも働けそうか」「見学だけでも相談できるのか」が伝わりにくいことがあります。")

        # 件名：施設名を入れて全施設で異なる件名にする（スパム判定防止）
        default_subject = ind_cfg.get("default_subject") or FACILITY_TYPE_SUBJECT.get(facility_type, "採用ページまわりの整備について")
        name_prefix = facility_name[:8] if facility_name and facility_name != "不明施設" else ""
        subject = f"{name_prefix}様 {default_subject}" if name_prefix else default_subject

        # 施設種別ごとの本文コンテキスト（介護のみ詳細あり、他業種は汎用）
        facility_context = FACILITY_TYPE_CONTEXT.get(facility_type, "")

        # URL行（設定済みの場合のみ表示）
        url_lines = []
        if service_lp_url:
            url_lines.append(f"▶ サービス詳細：{service_lp_url}")
        if sample_site_url:
            url_lines.append(f"▶ サンプルサイト：{sample_site_url}")
        url_section = ("\n" + "\n".join(url_lines)) if url_lines else ""

        context_block = f"\n{facility_context}\n" if facility_context else "\n"

        body = f"""\
{facility_name}
採用ご担当者様

突然のご連絡失礼いたします。

{intro_text}

{problem_text}
{context_block}
弊社では現在、導入事例づくりにご協力いただける事業者様限定で、

・採用専用ページ
・求人掲載用テキスト
・応募/見学フォーム
・SNS用採用画像
・応募後の返信テンプレート

をまとめて50,000円（税込55,000円）で制作しております。

採用人数や応募数を保証するものではありませんが、求人票だけでは伝わりにくい情報を整理し、自社で応募・見学希望を受けられる状態を整えるサービスです。{url_section}

もし採用ページまわりを見直す機会がございましたら、現在の求人ページや応募導線について無料でご確認いたします（ご返信いただくだけで結構です）。

突然のご連絡で大変恐縮ですが、ご関心がございましたらご返信いただけますと幸いです。

何卒よろしくお願いいたします。

--
{sender_name}
担当：岡原（おかはら）
千葉県（詳細住所はご要望があればお知らせします）
oka.ponomedia@gmail.com
※ご不要の場合は件名に「配信停止」とご記入のうえ本メールにご返信ください。以後ご連絡いたしません。"""

        # 禁止表現が混入していないか最終チェック
        FORBIDDEN = [
            "スコア", "ランク", "点", "見当たりません", "ありません",
            "課題があるかと", "採用に困って", "応募が増えます",
            "採用できます", "保証", "必ず",
        ]
        for word in FORBIDDEN:
            if word in body:
                logger.error(f"[email_generator] 禁止表現「{word}」が本文に混入しています。送信を中止します。")
                raise ValueError(f"禁止表現「{word}」がメール本文に含まれています")

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

先日ご案内を差し上げました、PonoMedia 介護採用支援の岡原です。

ご多用のところ恐縮ですが、先日のご案内がご参考になれば幸いです。
引き続き採用ページまわりのご確認を無料で承っておりますので、よろしければお気軽にご返信ください。

何卒よろしくお願いいたします。

--
PonoMedia 介護採用支援
担当：岡原（おかはら）
千葉県（詳細住所はご要望があればお知らせします）
oka.ponomedia@gmail.com
※ご不要の場合は件名に「配信停止」とご記入のうえご返信ください。以後ご連絡いたしません。"""

        return {
            "subject": subject,
            "body": body,
        }
