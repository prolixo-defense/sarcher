"""
Autonomous SDR (Sales Development Representative) agent.

Orchestrates the full reply handling pipeline:
1. Classify intent with SentimentAnalyzer
2. If OPT_OUT → immediate compliance action
3. If AUTO_REPLY / BOUNCE → note and pause
4. If POSITIVE → generate personalized follow-up draft
5. If NEGATIVE (objection) → RAG rebuttal → generate draft
6. If REFERRAL → create new lead from referral info

All AI-generated responses are saved as DRAFTS.
Human approval is required before sending (human-in-the-loop).
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SDRAgent:
    """Autonomous SDR response handler with human-in-the-loop."""

    def __init__(
        self,
        sentiment_analyzer,
        objection_handler,
        message_repo,
        lead_repo,
        gdpr_manager,
        settings=None,
    ):
        self._sentiment = sentiment_analyzer
        self._objection = objection_handler
        self._messages = message_repo
        self._leads = lead_repo
        self._gdpr = gdpr_manager
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings

    async def process_reply(self, message) -> dict:
        """
        Process an incoming reply message.
        Returns {action: str, draft_id: str | None, sentiment: str}.
        """
        # Get conversation history for this lead
        history = [
            m.body for m in self._messages.find_by_lead(message.lead_id)
            if m.id != message.id
        ]

        # 1. Classify sentiment
        sentiment = await self._sentiment.analyze(
            message_body=message.body,
            conversation_history=history,
        )
        sentiment_type = sentiment.get("sentiment", "NEUTRAL_QUESTION")

        # Update message with sentiment
        message.sentiment = sentiment_type
        self._messages.save(message)

        logger.info(
            "[SDRAgent] Reply from lead %s: %s (confidence=%.2f)",
            message.lead_id,
            sentiment_type,
            sentiment.get("confidence", 0),
        )

        # 2. Handle OPT_OUT immediately (legal requirement)
        if sentiment_type == "OPT_OUT":
            await self._gdpr.process_opt_out(message.lead_id)
            return {"action": "opt_out", "draft_id": None, "sentiment": sentiment_type}

        # 3. Handle BOUNCE
        if sentiment_type == "BOUNCE":
            lead = self._leads.find_by_id(message.lead_id)
            if lead:
                from src.domain.enums import LeadStatus
                lead.status = LeadStatus.DISQUALIFIED
                self._leads.save(lead)
            return {"action": "bounce_recorded", "draft_id": None, "sentiment": sentiment_type}

        # 4. AUTO_REPLY — note and wait
        if sentiment_type == "AUTO_REPLY":
            return {"action": "auto_reply_noted", "draft_id": None, "sentiment": sentiment_type}

        # 5. Generate draft response for all other cases
        lead = self._leads.find_by_id(message.lead_id)
        if lead is None:
            return {"action": "lead_not_found", "draft_id": None, "sentiment": sentiment_type}

        draft_result = await self._objection.generate_response(
            incoming_message=message.body,
            sentiment=sentiment,
            lead=lead,
            conversation_history=history,
        )

        # 6. Save draft as a message record
        from src.domain.entities.message import Message
        from src.domain.enums import Channel, MessageDirection, MessageStatus

        draft_msg = Message(
            lead_id=message.lead_id,
            campaign_id=message.campaign_id,
            channel=message.channel,
            direction=MessageDirection.OUTBOUND,
            subject=f"Re: {getattr(message, 'subject', '') or ''}".strip(),
            body=draft_result["draft_response"],
            status=MessageStatus.DRAFT,
        )
        draft_msg.draft_response = draft_result["draft_response"]
        saved_draft = self._messages.save(draft_msg)

        # 7. Update lead status to RESPONDED
        from src.domain.enums import LeadStatus
        lead.status = LeadStatus.RESPONDED
        self._leads.save(lead)

        return {
            "action": "draft_created",
            "draft_id": saved_draft.id,
            "sentiment": sentiment_type,
            "requires_review": True,
        }

    async def generate_personalization(self, lead) -> str:
        """Generate a personalization hook based on lead context."""
        try:
            from pydantic import BaseModel

            class PersonalizationHook(BaseModel):
                hook: str

            from src.infrastructure.llm.llm_client import LLMClient
            client = LLMClient(settings=self._settings)
            prompt = (
                f"Generate a single, specific, relevant personalization sentence for an "
                f"outreach email to {lead.full_name()}, {lead.job_title or 'professional'} "
                f"at {lead.company_name or 'their company'}. "
                f"Reference something specific about their role or company. "
                f"Max 20 words. Do not use generic flattery."
            )
            result = await client.extract_structured(
                content=prompt,
                response_model=PersonalizationHook,
                system_prompt="You write concise, specific personalization hooks for sales emails.",
            )
            return result.hook
        except Exception as exc:
            logger.warning("[SDRAgent] Personalization LLM failed: %s", exc)
            company = lead.company_name or "your company"
            return f"I came across {company} and was impressed by your team's work"

    async def get_pending_drafts(self) -> list[dict]:
        """Return all draft responses awaiting human review."""
        from src.domain.enums import MessageStatus

        drafts = self._messages.find_drafts()
        result = []
        for draft in drafts:
            lead = self._leads.find_by_id(draft.lead_id)
            result.append({
                "draft_id": draft.id,
                "lead_name": lead.full_name() if lead else "Unknown",
                "lead_email": lead.email if lead else None,
                "channel": draft.channel.value if hasattr(draft.channel, "value") else str(draft.channel),
                "subject": draft.subject,
                "body": draft.body,
                "created_at": draft.created_at.isoformat() if draft.created_at else None,
            })
        return result
