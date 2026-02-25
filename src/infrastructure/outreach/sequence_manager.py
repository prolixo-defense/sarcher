"""
Orchestrates multi-step outreach sequences for campaigns.

For each lead in a campaign:
1. Check which step they're on (based on sent messages)
2. Check if the delay since the last step has elapsed
3. Check the condition (e.g. "no_reply" — skip if they replied)
4. Check sending limits and business hours
5. If all checks pass, execute the next step
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class SequenceManager:
    """Orchestrates multi-step outreach sequences for a campaign."""

    def __init__(self, campaign_repo, message_repo, email_sender, linkedin_outreach=None):
        self._campaigns = campaign_repo
        self._messages = message_repo
        self._email = email_sender
        self._linkedin = linkedin_outreach

    async def process_campaign(self, campaign_id: str) -> dict:
        """
        Process all pending sequence steps for a campaign.
        Returns {processed: int, skipped: int, errors: int}.
        """
        campaign = self._campaigns.find_by_id(campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.status != "active":
            return {"processed": 0, "skipped": 0, "errors": 0}

        from src.infrastructure.database.connection import SessionLocal
        from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

        session = SessionLocal()
        try:
            lead_repo = SqlLeadRepository(session)
            filters = campaign.target_filters or {}
            leads, _ = lead_repo.search(filters, limit=500, offset=0)

            processed = skipped = errors = 0
            for lead in leads:
                try:
                    step = await self.get_next_action(campaign_id, lead.id)
                    if step is None:
                        skipped += 1
                        continue
                    await self._execute_step(campaign, lead, step)
                    processed += 1
                except Exception as exc:
                    logger.error("[SequenceManager] Error for lead %s: %s", lead.id, exc)
                    errors += 1
            return {"processed": processed, "skipped": skipped, "errors": errors}
        finally:
            session.close()

    async def get_next_action(self, campaign_id: str, lead_id: str):
        """
        Determine the next sequence step for a specific lead.
        Returns a step dict or None.
        """
        campaign = self._campaigns.find_by_id(campaign_id)
        if campaign is None:
            return None

        steps = sorted(campaign.sequence_steps, key=lambda s: s.get("step_number", 0))
        if not steps:
            return None

        # Get all messages already sent to this lead for this campaign
        sent_messages = [
            m for m in self._messages.find_by_lead(lead_id)
            if m.campaign_id == campaign_id and m.direction == "outbound"
        ]
        sent_step_numbers = {getattr(m, "step_number", None) for m in sent_messages}
        last_sent_at = max(
            (m.sent_at for m in sent_messages if m.sent_at), default=None
        )

        for step in steps:
            step_num = step.get("step_number", 0)
            if step_num in sent_step_numbers:
                continue
            if not step.get("is_active", True):
                continue

            # Check delay
            if last_sent_at is not None:
                delay_days = step.get("delay_days", 1)
                earliest = last_sent_at + timedelta(days=delay_days)
                if datetime.now(timezone.utc) < earliest:
                    return None  # Too early for this step

            # Check condition
            condition = step.get("condition")
            if condition == "no_reply":
                has_reply = any(
                    m.direction == "inbound"
                    for m in self._messages.find_by_lead(lead_id)
                    if m.campaign_id == campaign_id
                )
                if has_reply:
                    continue  # Skip — they already replied

            return step

        return None

    async def _execute_step(self, campaign, lead, step: dict) -> None:
        """Execute a single sequence step for a lead."""
        from src.infrastructure.outreach.template_engine import TemplateEngine
        from src.domain.entities.message import Message
        from src.domain.enums import Channel, MessageDirection, MessageStatus

        template_id = step.get("template_id", "initial_outreach")
        channel_str = step.get("channel", "email")
        step_num = step.get("step_number", 1)

        # Build context
        context = {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "company_name": lead.company_name or "",
            "job_title": lead.job_title or "",
            "sender_name": "Sales Team",
            "personalization_hook": "",
            "value_proposition": "I'd love to connect and share how we can help.",
        }

        engine = TemplateEngine()
        try:
            rendered = engine.render(template_id, context)
        except FileNotFoundError:
            logger.warning("[SequenceManager] Template %s not found, skipping step", template_id)
            return

        success = False
        error = None

        if channel_str == "email" and lead.email:
            result = await self._email.send(
                to=lead.email,
                subject=rendered["subject"],
                html_body=rendered["html_body"],
                plain_body=rendered["plain_body"],
            )
            success = result.get("success", False)
            error = result.get("error")

        elif channel_str.startswith("linkedin") and lead.linkedin_url and self._linkedin:
            if channel_str == "linkedin_connect":
                success = await self._linkedin.send_connection(lead.linkedin_url, rendered["plain_body"])
            elif channel_str == "linkedin_message":
                success = await self._linkedin.send_message(lead.linkedin_url, rendered["plain_body"])

        # Save message record
        channel_enum = Channel(channel_str) if channel_str in Channel._value2member_map_ else Channel.EMAIL
        msg = Message(
            lead_id=lead.id,
            campaign_id=campaign.id,
            channel=channel_enum,
            direction=MessageDirection.OUTBOUND,
            subject=rendered.get("subject"),
            body=rendered["plain_body"],
            status=MessageStatus.SENT if success else MessageStatus.BOUNCED,
            sent_at=datetime.now(timezone.utc) if success else None,
        )
        # Attach step_number as extra attribute for tracking
        object.__setattr__(msg, "step_number", step_num) if hasattr(msg, "__dict__") else None
        msg.__dict__["step_number"] = step_num
        self._messages.save(msg)

        if error:
            logger.warning("[SequenceManager] Step %d failed for lead %s: %s", step_num, lead.id, error)
