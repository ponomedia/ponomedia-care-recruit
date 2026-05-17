"""
email_generator.py — パーソナライズ営業メール生成モジュール

施設ごとのスコアリング結果をもとに、弱点に刺さる個別営業メールを生成する。
採用保証の表現は絶対に含めない。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmailGenerator:
    """施設ごとにパーソナライズされた営業メールを生成するクラス"""

    # 施設種別ごとの採用課題（メール本文の自然な文章に使用）
    FACILITY_CHALLENGES = {
        "デイサービス": "日中帯のスタッフ確保",
        "訪問介護": "ヘルパーの新規採用",
        "グループホーム": "夜勤対応スタッフの確保",
        "住宅型有料老人ホーム": "介護職員の定着・採用",
        "障害福祉サービス": "支援員・指導員の採用",
    }

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

        Args:
            facility_name: 施設名
            facility_type: 施設種別
            area: エリア名
            score_result: HiringPageScorerが返したスコアリング結果dict
            service_lp_url: サービスLPのURL（空の場合は省略）
            sample_site_url: サンプルサイトURL（空の場合は省略）

        Returns:
            {"subject": str, "body": str}
        """
        weakness_reasons = score_result.get("weakness_reasons", [])
        rank = score_result.get("rank", "B")

        # 弱点を最大2件選んで本文に組み込む（ピンポイント感を演出）
        top_weaknesses = weakness_reasons[:2]

        # 施設種別ごとの課題ワード
        challenge = self.FACILITY_CHALLENGES.get(facility_type, "スタッフ採用")

        # 件名
        subject = (
            f"【{facility_name}様】採用サイト診断レポートをご用意しました"
        )

        # 弱点の言及部分を動的に生成
        weakness_text = self._build_weakness_text(top_weaknesses)

        # URL行を動的に生成（設定済みの場合のみ表示）
        url_lines = []
        if service_lp_url:
            url_lines.append(f"▶ サービス詳細：{service_lp_url}")
        if sample_site_url:
            url_lines.append(f"▶ サンプルサイト：{sample_site_url}")
        url_section = "\n".join(url_lines)

        # 本文を組み立て（400字程度、ビジネスメール調）
        body = f"""\
{facility_name} 採用ご担当者様

突然のご連絡、失礼いたします。
介護施設様の採用サイト制作を支援しております、PonoMedia 介護採用支援と申します。

貴施設のWebサイトを拝見したところ、
{weakness_text}

{challenge}のご課題があるかと存じ、
ご参考までに無料の採用ページ診断をご用意できればと思いご連絡差し上げました。

【サービス概要】
介護施設専門の採用サイト制作サービスです。
現在、実績づくりのモニター価格として 50,000円（税込）でご提供しております。
※採用人数の保証はございません。あくまで求職者が応募しやすい環境づくりのご支援です。
{url_section}

ご興味がございましたら、まずは無料診断レポートをお送りいたします。
お気軽にご返信ください。

--
PonoMedia 介護採用支援
"""

        logger.debug(f"メール生成完了: {facility_name} | ランク: {rank}")

        return {
            "subject": subject,
            "body": body.strip(),
        }

    def generate_followup_email(self, facility_name: str) -> dict:
        """
        1週間後の追いメール（フォローアップ）を生成する。

        Args:
            facility_name: 施設名

        Returns:
            {"subject": str, "body": str}
        """
        subject = f"【再送】{facility_name}様 採用サイト診断のご提案"

        body = f"""\
{facility_name} 採用ご担当者様

先日ご連絡差し上げました、PonoMedia 介護採用支援です。

先般のご提案メールはご覧いただけましたでしょうか。
もしご多用の折でしたら大変恐れ入ります。

ご関心があれば、引き続き無料診断レポートのご提供が可能でございます。
ご都合のよいタイミングでご返信いただけますと幸いです。

今後ともよろしくお願いいたします。

--
PonoMedia 介護採用支援
"""

        return {
            "subject": subject,
            "body": body.strip(),
        }

    # ------------------------------------------------------------------
    # 内部ヘルパーメソッド
    # ------------------------------------------------------------------

    def _build_weakness_text(self, weaknesses: list) -> str:
        """弱点リストを自然な日本語文章に変換する"""
        if not weaknesses:
            return "採用に関する情報の充実度に改善の余地があると感じました。"

        if len(weaknesses) == 1:
            return f"・{weaknesses[0]}\nという点が見受けられました。"

        lines = "\n".join(f"・{w}" for w in weaknesses)
        return f"{lines}\nという点が見受けられました。"
