"""
Async email sender via SMTP (aiosmtplib).

Compliance requirements enforced:
- List-Unsubscribe header (RFC 8058)
- Unsubscribe link in body
- Physical address in footer
- HTML + plain text multipart
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailSender:
    """
    Sends emails via SMTP with compliance headers and rate limiting.
    Uses aiosmtplib for async sending.
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        self._sent_this_hour: list[datetime] = []
        self._lock = asyncio.Lock()

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        plain_body: str,
        unsubscribe_token: str | None = None,
    ) -> dict:
        """
        Send a single email.
        Returns {success: bool, message_id: str | None, error: str | None}.
        """
        if not self._settings.smtp_username or not self._settings.smtp_password:
            logger.warning("SMTP credentials not configured — email not sent.")
            return {"success": False, "message_id": None, "error": "SMTP not configured"}

        if not self._check_rate_limit():
            return {"success": False, "message_id": None, "error": "Daily email limit reached"}

        try:
            import aiosmtplib

            unsubscribe_url = self._build_unsubscribe_url(to, unsubscribe_token)

            # Inject unsubscribe footer into body
            plain_footer = f"\n\n---\nTo unsubscribe: {unsubscribe_url}\n{self._settings.physical_address}"
            html_footer = (
                f"<br><hr><small>To <a href='{unsubscribe_url}'>unsubscribe</a> | "
                f"{self._settings.physical_address}</small>"
            )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self._settings.sender_name} <{self._settings.sender_email}>"
            msg["To"] = to
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            msg.attach(MIMEText(plain_body + plain_footer, "plain"))
            msg.attach(MIMEText(html_body + html_footer, "html"))

            await aiosmtplib.send(
                msg,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_username,
                password=self._settings.smtp_password,
                start_tls=True,
            )

            async with self._lock:
                self._sent_this_hour.append(datetime.now(timezone.utc))

            logger.info("Email sent to %s: %s", to, subject)
            return {"success": True, "message_id": msg.get("Message-ID"), "error": None}

        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return {"success": False, "message_id": None, "error": str(exc)}

    async def send_with_template(
        self, to: str, template_id: str, context: dict
    ) -> dict:
        """Render a template and send the email."""
        from src.infrastructure.outreach.template_engine import TemplateEngine

        engine = TemplateEngine()
        rendered = engine.render(template_id, context)
        return await self.send(
            to=to,
            subject=rendered["subject"],
            html_body=rendered["html_body"],
            plain_body=rendered["plain_body"],
        )

    def _check_rate_limit(self) -> bool:
        """Return False if daily email limit has been hit."""
        now = datetime.now(timezone.utc)
        # Prune records older than 24 hours
        self._sent_this_hour = [
            t for t in self._sent_this_hour
            if (now - t).total_seconds() < 86400
        ]
        return len(self._sent_this_hour) < self._settings.daily_email_limit

    def _build_unsubscribe_url(self, email: str, token: str | None) -> str:
        """Build a simple unsubscribe URL."""
        base = self._settings.privacy_notice_url or "https://example.com"
        safe_email = re.sub(r"[^a-zA-Z0-9@._-]", "", email)
        return f"{base}/unsubscribe?email={safe_email}"

    def is_business_hours(self) -> bool:
        """Check if current time is within configured business hours."""
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(self._settings.timezone)
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)
        day = now.strftime("%a").lower()[:3]  # "mon", "tue", etc.
        allowed_days = [d.strip().lower()[:3] for d in self._settings.business_days.split(",")]
        if day not in allowed_days:
            return False
        return self._settings.business_hours_start <= now.hour < self._settings.business_hours_end
