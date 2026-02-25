"""
GDPR/CCPA compliance automation.

Mechanisms:
1. OPT-OUT: Immediate lead status change + suppression list entry
2. SUPPRESSION LIST: Never contact suppressed emails
3. DSAR EXPORT: Export all data held for a person
4. DSAR DELETE: Anonymize/delete all data for a person
5. DATA RETENTION: Purge leads past their expires_at TTL
"""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class GDPRManager:
    """Automates GDPR and CCPA compliance requirements."""

    def __init__(self, session):
        self._session = session

    async def check_suppression(self, email: str) -> bool:
        """Returns True if email is on the suppression list."""
        from src.infrastructure.database.models import SuppressionListModel

        email = email.lower().strip()
        record = (
            self._session.query(SuppressionListModel)
            .filter(SuppressionListModel.email == email)
            .first()
        )
        return record is not None

    async def add_to_suppression(
        self, email: str, reason: str = "manual", source: str = "manual"
    ) -> None:
        """Add an email to the suppression list. Idempotent."""
        from src.infrastructure.database.models import SuppressionListModel

        email = email.lower().strip()
        existing = (
            self._session.query(SuppressionListModel)
            .filter(SuppressionListModel.email == email)
            .first()
        )
        if existing:
            return  # Already suppressed

        record = SuppressionListModel(
            id=str(uuid.uuid4()),
            email=email,
            reason=reason,
            source=source,
        )
        self._session.add(record)
        self._session.flush()
        logger.info("[GDPR] Added %s to suppression list (reason=%s)", email, reason)

    async def process_opt_out(self, lead_id: str) -> dict:
        """
        Full opt-out flow:
        1. Update lead status to OPTED_OUT
        2. Add email to suppression list
        3. Cancel any pending messages for this lead
        """
        from src.infrastructure.database.models import LeadModel, MessageModel
        from src.domain.enums import LeadStatus, MessageStatus

        lead = self._session.query(LeadModel).filter(LeadModel.id == lead_id).first()
        if lead is None:
            return {"success": False, "error": "Lead not found"}

        # Update lead status
        lead.status = LeadStatus.OPTED_OUT.value
        self._session.flush()

        # Add to suppression list
        if lead.email:
            await self.add_to_suppression(lead.email, reason="opt_out", source="opt_out")

        # Cancel pending/queued messages
        cancelled = (
            self._session.query(MessageModel)
            .filter(
                MessageModel.lead_id == lead_id,
                MessageModel.status.in_(["queued", "draft"]),
            )
            .all()
        )
        for msg in cancelled:
            msg.status = MessageStatus.DISCARDED.value
        self._session.flush()

        logger.info(
            "[GDPR] Opt-out processed for lead %s (%s). %d messages cancelled.",
            lead_id,
            lead.email or "no email",
            len(cancelled),
        )
        return {
            "success": True,
            "lead_id": lead_id,
            "email": lead.email,
            "messages_cancelled": len(cancelled),
        }

    async def handle_dsar_export(self, email: str) -> dict:
        """Export all data held for this email address (GDPR Article 15)."""
        from src.infrastructure.database.models import (
            LeadModel, MessageModel, CreditUsageModel, SuppressionListModel, ComplianceRequestModel
        )

        email = email.lower().strip()
        lead = self._session.query(LeadModel).filter(LeadModel.email == email).first()
        if lead is None:
            return {"email": email, "found": False, "data": {}}

        messages = self._session.query(MessageModel).filter(MessageModel.lead_id == lead.id).all()
        credits = self._session.query(CreditUsageModel).filter(CreditUsageModel.lead_id == lead.id).all()
        suppressed = self._session.query(SuppressionListModel).filter(SuppressionListModel.email == email).first()

        export_data = {
            "lead": {
                "id": lead.id,
                "name": f"{lead.first_name} {lead.last_name}".strip(),
                "email": lead.email,
                "phone": lead.phone,
                "company": lead.company_name,
                "status": lead.status,
                "source": lead.source,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            },
            "messages": [
                {
                    "id": m.id,
                    "direction": m.direction,
                    "channel": m.channel,
                    "subject": m.subject,
                    "status": m.status,
                    "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                }
                for m in messages
            ],
            "credit_usage": [
                {"provider": c.provider, "credits": c.credits_used, "month": c.month}
                for c in credits
            ],
            "suppression": {
                "suppressed": suppressed is not None,
                "reason": suppressed.reason if suppressed else None,
                "added_at": suppressed.created_at.isoformat() if suppressed else None,
            },
        }

        # Log DSAR request
        request = ComplianceRequestModel(
            id=str(uuid.uuid4()),
            request_type="dsar_export",
            email=email,
            status="completed",
            result={"exported_at": datetime.now(timezone.utc).isoformat()},
            completed_at=datetime.now(timezone.utc),
        )
        self._session.add(request)
        self._session.flush()

        return {"email": email, "found": True, "data": export_data}

    async def handle_dsar_delete(self, email: str) -> dict:
        """
        Delete all data for this email (GDPR Article 17 — Right to Erasure).
        Anonymizes lead record; keeps suppression entry to prevent re-contact.
        """
        from src.infrastructure.database.models import (
            LeadModel, MessageModel, CreditUsageModel, ComplianceRequestModel
        )

        email = email.lower().strip()
        lead = self._session.query(LeadModel).filter(LeadModel.email == email).first()
        if lead is None:
            return {"success": False, "email": email, "error": "Not found"}

        lead_id = lead.id

        # Anonymize messages (keep record, remove PII)
        messages = self._session.query(MessageModel).filter(MessageModel.lead_id == lead_id).all()
        for msg in messages:
            msg.body = "[REDACTED - DSAR DELETE]"
            msg.subject = "[REDACTED]"
            msg.draft_response = None
        self._session.flush()

        # Delete credit usage records
        self._session.query(CreditUsageModel).filter(CreditUsageModel.lead_id == lead_id).delete()

        # Anonymize lead
        lead.first_name = "[DELETED]"
        lead.last_name = ""
        lead.email = None
        lead.phone = None
        lead.linkedin_url = None
        lead.raw_data = None
        lead.status = "deleted"
        self._session.flush()

        # Ensure suppression (to prevent future re-contact)
        await self.add_to_suppression(email, reason="dsar_delete", source="dsar")

        # Log DSAR request
        request = ComplianceRequestModel(
            id=str(uuid.uuid4()),
            request_type="dsar_delete",
            email=email,
            status="completed",
            result={
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "messages_anonymized": len(messages),
            },
            completed_at=datetime.now(timezone.utc),
        )
        self._session.add(request)
        self._session.flush()

        logger.info("[GDPR] DSAR delete completed for %s", email)
        return {
            "success": True,
            "email": email,
            "lead_id": lead_id,
            "messages_anonymized": len(messages),
        }

    async def cleanup_expired(self) -> int:
        """Anonymize/delete leads past their retention period."""
        from src.infrastructure.database.models import LeadModel

        now = datetime.now(timezone.utc)
        expired = (
            self._session.query(LeadModel)
            .filter(LeadModel.expires_at.isnot(None))
            .filter(LeadModel.expires_at < now)
            .filter(LeadModel.status != "deleted")
            .all()
        )
        count = 0
        for lead in expired:
            if lead.email:
                try:
                    await self.handle_dsar_delete(lead.email)
                    count += 1
                except Exception as exc:
                    logger.warning("[GDPR] cleanup_expired failed for lead %s: %s", lead.id, exc)
            else:
                lead.first_name = "[EXPIRED]"
                lead.last_name = ""
                lead.status = "deleted"
                count += 1
        self._session.flush()
        logger.info("[GDPR] Cleaned up %d expired leads", count)
        return count

    def get_suppression_list(self, limit: int = 100) -> list[dict]:
        """Return the suppression list."""
        from src.infrastructure.database.models import SuppressionListModel

        records = (
            self._session.query(SuppressionListModel)
            .order_by(SuppressionListModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "email": r.email,
                "reason": r.reason,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
