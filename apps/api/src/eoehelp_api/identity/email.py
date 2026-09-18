"""Transactional email.

Magic-link delivery is the only way into the product, so a send failure is an
outage rather than a degraded feature. Sends are logged without the recipient
address; delivery is monitored on bounce and complaint metrics at the provider.
"""

from email.message import EmailMessage

import aiosmtplib

from eoehelp_api.config import Settings, get_settings
from eoehelp_api.observability import get_logger

logger = get_logger(__name__)


class EmailSender:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, *, to: str, subject: str, text_body: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text_body)

        await aiosmtplib.send(
            message,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username,
            password=(
                self._settings.smtp_password.get_secret_value()
                if self._settings.smtp_password
                else None
            ),
            start_tls=self._settings.smtp_use_tls,
        )
        logger.info("email.sent", subject=subject)

    async def send_magic_link(self, *, to: str, link: str, ttl_minutes: int) -> None:
        body = (
            "Sign in to eoehelp\n\n"
            f"Use the link below within {ttl_minutes} minutes:\n\n"
            f"{link}\n\n"
            "The link works once. If you did not request it, you can ignore this "
            "email and no change will be made to your account.\n"
        )
        await self.send(to=to, subject="Your eoehelp sign-in link", text_body=body)
