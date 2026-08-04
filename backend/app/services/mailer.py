from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings
from app.schemas.auth import EmailCodePurpose


class EmailDeliveryError(RuntimeError):
    pass


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_verification_code(
        self,
        *,
        recipient: str,
        code: str,
        purpose: EmailCodePurpose,
    ) -> None:
        if not self.settings.smtp_configured:
            raise EmailDeliveryError("SMTP is not configured")

        purpose_labels = {
            EmailCodePurpose.REGISTER: "注册账号",
            EmailCodePurpose.RESET_PASSWORD: "重置密码",
            EmailCodePurpose.BIND_EMAIL: "绑定邮箱",
        }
        purpose_label = purpose_labels[purpose]
        expire_minutes = max(1, self.settings.email_code_expire_seconds // 60)
        site_name = self.settings.site_name
        sender_name = self.settings.smtp_from_name.strip() or site_name

        message = EmailMessage()
        message["Subject"] = f"【{site_name}】{purpose_label}验证码"
        message["From"] = formataddr((sender_name, self.settings.smtp_from_email.strip()))
        message["To"] = recipient
        message.set_content(
            f"你正在{purpose_label}。\n\n验证码：{code}\n\n"
            f"验证码将在 {expire_minutes} 分钟后失效，请勿转发给他人。\n"
            "如果这不是你的操作，可以忽略这封邮件。"
        )
        message.add_alternative(
            f"""
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;color:#2c2518">
              <h2 style="margin:0 0 16px">{site_name}</h2>
              <p>你正在{purpose_label}，验证码为：</p>
              <p style="font:700 28px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:6px;color:#a87d28">{code}</p>
              <p>验证码将在 {expire_minutes} 分钟后失效，请勿转发给他人。</p>
              <p style="color:#6b5d4a">如果这不是你的操作，可以忽略这封邮件。</p>
            </div>
            """,
            subtype="html",
        )

        try:
            if self.settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                ) as client:
                    self._authenticate_and_send(client, message)
                return

            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as client:
                client.ehlo()
                if self.settings.smtp_use_tls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                self._authenticate_and_send(client, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("SMTP delivery failed") from exc

    def _authenticate_and_send(self, client: smtplib.SMTP, message: EmailMessage) -> None:
        if self.settings.smtp_username:
            client.login(self.settings.smtp_username, self.settings.smtp_password)
        client.send_message(message)
