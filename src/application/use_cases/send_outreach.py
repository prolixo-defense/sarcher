"""Use case: send a single outreach message in a sequence."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SendOutreach:
    """Sends a single outreach message to a lead (email or LinkedIn)."""

    def __init__(
        self,
        message_repo,
        lead_repo,
        email_sender,
        gdpr_manager,
        linkedin_outreach=None,
        template_engine=None,
    ):
        self._messages = message_repo
        self._leads = lead_repo
        self._email = email_sender
        self._gdpr = gdpr_manager
        self._linkedin = linkedin_outreach
        self._templates = template_engine

    async def execute(
        self,
        lead_id: str,
        channel: str,
        template_id: str,
        campaign_id: str | None = None,
        context_overrides: dict | None = None,
    ) -> dict:
        """
        Send an outreach message to a lead.

        Returns {success: bool, message_id: str | None, error: str | None}.
        """
        from src.domain.entities.message import Message
        from src.domain.enums import Channel, MessageDirection, MessageStatus

        # 1. Get lead
        lead = self._leads.find_by_id(lead_id)
        if lead is None:
            return {"success": False, "message_id": None, "error": "Lead not found"}

        # 2. Check suppression
        if lead.email and await self._gdpr.check_suppression(lead.email):
            return {"success": False, "message_id": None, "error": "Email is suppressed"}

        # 3. Build template context
        context = {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "company_name": lead.company_name or "",
            "job_title": lead.job_title or "",
            "sender_name": "Sales Team",
            "unsubscribe_link": "#unsubscribe",
            "personalization_hook": "",
            "value_proposition": "I'd love to connect.",
        }
        if context_overrides:
            context.update(context_overrides)

        # 4. Render template
        try:
            from src.infrastructure.outreach.template_engine import TemplateEngine
            engine = self._templates or TemplateEngine()
            rendered = engine.render(template_id, context)
        except FileNotFoundError:
            rendered = {
                "subject": f"Reaching out — {lead.company_name or 'your company'}",
                "html_body": f"Hi {lead.first_name}, I'd love to connect.",
                "plain_body": f"Hi {lead.first_name}, I'd love to connect.",
            }

        # 5. Send
        success = False
        error = None

        try:
            channel_enum = Channel(channel)
        except ValueError:
            channel_enum = Channel.EMAIL

        if channel_enum == Channel.EMAIL and lead.email:
            result = await self._email.send(
                to=lead.email,
                subject=rendered["subject"],
                html_body=rendered["html_body"],
                plain_body=rendered["plain_body"],
            )
            success = result.get("success", False)
            error = result.get("error")

        elif channel_enum in (Channel.LINKEDIN_CONNECT, Channel.LINKEDIN_MESSAGE) and lead.linkedin_url and self._linkedin:
            if channel_enum == Channel.LINKEDIN_CONNECT:
                success = await self._linkedin.send_connection(lead.linkedin_url, rendered["plain_body"])
            else:
                success = await self._linkedin.send_message(lead.linkedin_url, rendered["plain_body"])
        else:
            error = f"Cannot send via {channel} — no {channel} address for this lead"

        # 6. Record message
        msg = Message(
            lead_id=lead_id,
            campaign_id=campaign_id,
            channel=channel_enum,
            direction=MessageDirection.OUTBOUND,
            subject=rendered.get("subject"),
            body=rendered["plain_body"],
            status=MessageStatus.SENT if success else MessageStatus.BOUNCED,
            sent_at=datetime.now(timezone.utc) if success else None,
        )
        saved = self._messages.save(msg)

        # 7. Update lead status
        if success:
            from src.domain.enums import LeadStatus
            lead.status = LeadStatus.CONTACTED
            self._leads.save(lead)

        return {
            "success": success,
            "message_id": saved.id,
            "error": error,
        }
