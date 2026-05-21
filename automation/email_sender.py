"""
email_sender.py — Gmail SMTP メール送信モジュール

Gmailアプリパスワードを使用してSMTP_SSL（ポート465）で送信する。
2段階認証 + アプリパスワードが事前設定済みであること。
"""

import re
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

# RFC5322 準拠のメールアドレス検証パターン
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

logger = logging.getLogger(__name__)


class GmailSender:
    """Gmail SMTPを使ってメールを送信するクラス"""

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 465  # SSL接続

    def __init__(
        self,
        gmail_address: str,
        app_password: str,
        sender_name: str = "PonoMedia 介護採用支援",
    ):
        """
        Args:
            gmail_address: 送信元Gmailアドレス
            app_password: Gmailアプリパスワード（16桁、ハイフンなしでもOK）
            sender_name: 送信者表示名
        """
        self.gmail_address = gmail_address
        self.app_password = app_password.replace("-", "").replace(" ", "")  # ハイフン・スペース除去
        self.sender_name = sender_name

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_name: str = None,
    ) -> bool:
        """
        メールを送信する。

        Args:
            to_email: 宛先メールアドレス
            subject: 件名
            body: 本文（プレーンテキスト）
            from_name: 送信者表示名（Noneの場合はself.sender_nameを使用）

        Returns:
            True: 送信成功 / False: 送信失敗
        """
        if not self.gmail_address or not self.app_password:
            logger.error("Gmailアドレスまたはアプリパスワードが未設定です。.envを確認してください。")
            return False

        # メールアドレス形式を厳密に検証
        if not to_email or not _EMAIL_RE.match(to_email.strip()):
            logger.warning(f"無効な宛先アドレス（形式不正）: {to_email}")
            return False

        # 自分自身への送信を絶対にブロック（テストループ防止）
        if to_email.strip().lower() == self.gmail_address.strip().lower():
            logger.error(f"★ 自分自身への送信をブロック: {to_email}")
            return False

        display_name = from_name or self.sender_name

        try:
            # MIMEメッセージを構築
            msg = MIMEMultipart("alternative")

            # 件名（日本語対応: UTF-8エンコード）
            msg["Subject"] = Header(subject, "utf-8")

            # 送信者（表示名 <アドレス> 形式）
            msg["From"] = formataddr(
                (str(Header(display_name, "utf-8")), self.gmail_address)
            )

            # 宛先
            msg["To"] = to_email

            # 本文をUTF-8プレーンテキストで添付
            text_part = MIMEText(body, "plain", "utf-8")
            msg.attach(text_part)

            # SMTP_SSL接続で送信
            with smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.login(self.gmail_address, self.app_password)
                server.sendmail(
                    self.gmail_address,
                    [to_email],
                    msg.as_bytes(linesep=b"\r\n"),
                )

            logger.info(f"[送信成功] TO: {to_email} | 件名: {subject[:30]}...")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error(
                "Gmail認証エラー: アプリパスワードまたはアドレスを確認してください。"
                "（2段階認証が有効か、アプリパスワードが正しいか）"
            )
            return False

        except smtplib.SMTPRecipientsRefused:
            logger.warning(f"宛先拒否: {to_email}")
            return False

        except smtplib.SMTPException as e:
            logger.error(f"SMTP送信エラー ({to_email}): {e}")
            return False

        except Exception as e:
            logger.error(f"予期しないエラー ({to_email}): {e}")
            return False

    def test_connection(self) -> bool:
        """
        SMTP接続とログインをテストする（メールは送信しない）。

        Returns:
            True: 接続成功 / False: 失敗
        """
        try:
            with smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.login(self.gmail_address, self.app_password)
            logger.info("Gmail SMTP接続テスト: 成功")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("Gmail SMTP接続テスト: 認証失敗")
            return False
        except Exception as e:
            logger.error(f"Gmail SMTP接続テスト: エラー — {e}")
            return False
