"""
quality_checker.py — 営業先リサーチ品質 2重チェックモジュール

Pass 1: 内部ルールベースチェック（高速・全件実行）
         → 確実NG / 確実OK はここで完結
Pass 2: CODEX CLIチェック（詳細・Pass1がグレーの場合のみ実行）
         → 誤判定リスクを最小化する第三者目線の確認
"""

import logging
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 介護・福祉施設の公式サイトらしいキーワード
CARE_KEYWORDS = [
    "介護", "デイ", "訪問", "グループホーム", "老人ホーム", "福祉",
    "ケア", "care", "kaigo", "welfare", "サービス", "通所",
    "採用", "求人", "スタッフ", "職員", "募集", "障害",
]

# 明らかにNGなドメイン（ポータル・求人サイト）
NG_DOMAINS = [
    "homes.co.jp", "kaigokensaku", "minnanokaigo", "caresapo",
    "kaigojob", "job-medley", "indeed", "townwork", "hellowork",
    "hotpepper", "tabelog", "navitime", "mapion", "ekiten",
    "heartpage", "caretree", "kaigo114", "ansinkaigo", "kiracare",
    "machbaito", "telnavi", "woman-type", "caremanagement",
    "wam.go.jp", "mhlw.go.jp", "pref.", ".lg.jp",
]

# 許容する非.jpドメイン（日本のサービス）
SAFE_NON_JP = [
    "fc2.com", "wix.com", "jimdo.com", "wordpress.com",
    "ameblo.jp", "goope.jp", "localplace.jp", "blogspot.com",
    "jimdofree.com", "studio.site", "amebaownd.com",
]


class QualityChecker:
    """
    営業先候補の品質を2段階で検証するクラス。

    verdict の意味:
        "pass"        → キューに pending として追加
        "fail"        → スキップ（送信しない）
        "needs_review"→ キューに needs_review として追加（スマホで手動確認）
    """

    def check(
        self,
        facility_name: str,
        url: str,
        facility_data: dict,
        contact_email: str,
    ) -> dict:
        """
        2重チェックを実行する。

        Returns:
            {
                "verdict": "pass" | "fail" | "needs_review",
                "reason": str,
                "codex_used": bool,
            }
        """
        # ──────────────────────────────
        # Pass 1: 内部ルールベース（高速）
        # ──────────────────────────────
        p1 = self._internal_check(facility_name, url, facility_data)

        if p1["verdict"] == "fail":
            logger.warning(f"[品質 Pass1-NG] {facility_name}: {p1['reason']}")
            return {**p1, "codex_used": False}

        if p1["verdict"] == "pass":
            logger.info(f"[品質 Pass1-OK] {facility_name}")
            return {**p1, "codex_used": False}

        # "uncertain" → Pass 2: CODEX
        logger.info(f"[品質 Pass1-グレー] {facility_name} ({p1['reason']}) → CODEX精査へ")
        p2 = self._codex_check(facility_name, url, facility_data, contact_email)
        logger.info(f"[品質 CODEX] {facility_name}: {p2['verdict']} — {p2['reason']}")
        return {**p2, "codex_used": True}

    # ──────────────────────────────────────────────────────
    # Pass 1: 内部チェック
    # ──────────────────────────────────────────────────────

    def _internal_check(
        self, facility_name: str, url: str, facility_data: dict
    ) -> dict:
        """ルールベースの高速チェック。"""

        # [1] URL存在チェック
        if not url:
            return {"verdict": "fail", "reason": "URLなし"}

        # [2] URLパース
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().replace("www.", "")
        except Exception:
            return {"verdict": "fail", "reason": "URL解析失敗"}

        # [3] NGドメイン（ポータルサイト等）
        for ng in NG_DOMAINS:
            if ng in host:
                return {"verdict": "fail", "reason": f"ポータル/求人サイト: {host}"}

        # [4] ドメインチェック（.jp 以外は要確認）
        is_jp = host.endswith(".jp")
        is_safe_non_jp = any(s in host for s in SAFE_NON_JP)
        if not is_jp and not is_safe_non_jp:
            return {"verdict": "uncertain", "reason": f"非.jpドメイン: {host}"}

        # [5] サイトテキストに介護キーワードがあるか
        fd = facility_data or {}
        combined = " ".join([
            fd.get("full_text", ""),
            fd.get("title", ""),
            fd.get("meta_description", ""),
        ]).lower()

        has_care_kw = any(kw in combined for kw in CARE_KEYWORDS)
        if not has_care_kw:
            return {
                "verdict": "uncertain",
                "reason": "介護・福祉関連キーワードがサイト上で確認できない",
            }

        # [6] 施設名の一部がページに含まれるか（前4文字で緩くチェック）
        name_key = facility_name[:4] if len(facility_name) >= 4 else facility_name
        if name_key not in combined and name_key.lower() not in host:
            return {
                "verdict": "uncertain",
                "reason": f"施設名「{name_key}」がサイト上で確認できない",
            }

        # [7] スクレイピング失敗（空ページ）
        if not fd.get("full_text", "").strip():
            return {"verdict": "uncertain", "reason": "ページテキスト取得ゼロ（アクセス失敗の可能性）"}

        return {"verdict": "pass", "reason": "内部チェック通過"}

    # ──────────────────────────────────────────────────────
    # Pass 2: CODEX CLI チェック
    # ──────────────────────────────────────────────────────

    def _codex_check(
        self,
        facility_name: str,
        url: str,
        facility_data: dict,
        contact_email: str,
    ) -> dict:
        """CODEX CLIを使った第三者目線の詳細確認。"""

        fd = facility_data or {}
        title = fd.get("title", "（不明）")
        meta = fd.get("meta_description", "（不明）")
        text_preview = fd.get("full_text", "")[:400]

        prompt = (
            f"以下の情報を見て、このURLが「{facility_name}」という"
            f"介護・福祉施設の公式サイトとして適切かどうか判定してください。\n\n"
            f"施設名: {facility_name}\n"
            f"URL: {url}\n"
            f"ページタイトル: {title}\n"
            f"メタ説明: {meta}\n"
            f"本文冒頭: {text_preview}\n"
            f"取得メール: {contact_email or 'なし'}\n\n"
            f"以下のいずれか1語のみで判定し、2行目に短い理由を書いてください:\n"
            f"PASS   — 公式サイトとして適切\n"
            f"FAIL   — 明らかに不適切（ポータル・無関係サイト等）\n"
            f"REVIEW — 判断が難しい（要人間確認）"
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

            if "PASS" in output:
                return {"verdict": "pass", "reason": f"CODEX承認"}
            elif "FAIL" in output:
                return {"verdict": "fail", "reason": "CODEX拒否: 不適切サイト"}
            elif "REVIEW" in output:
                return {"verdict": "needs_review", "reason": "CODEX: 要人間確認"}
            else:
                logger.warning(f"[CODEX] 判定不明 ({facility_name}): {output[:100]}")
                return {"verdict": "needs_review", "reason": "CODEX応答不明 — 安全のため要確認"}

        except subprocess.TimeoutExpired:
            logger.warning(f"[CODEX] タイムアウト: {facility_name}")
            return {"verdict": "needs_review", "reason": "CODEXタイムアウト — 要確認"}
        except FileNotFoundError:
            logger.warning("[CODEX] codexコマンドが見つかりません — needs_reviewとして処理")
            return {"verdict": "needs_review", "reason": "CODEX未インストール — 要確認"}
        except Exception as e:
            logger.warning(f"[CODEX] 予期せぬエラー: {e}")
            return {"verdict": "needs_review", "reason": f"CODEXエラー — 要確認"}
