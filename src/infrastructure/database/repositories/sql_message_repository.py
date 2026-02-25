"""SQLAlchemy repository for Message entities."""
import uuid
from datetime import datetime, timezone

from src.domain.entities.message import Message
from src.domain.enums import Channel, MessageDirection, MessageStatus
from src.domain.interfaces.message_repository import MessageRepository
from src.infrastructure.database.models import MessageModel


class SqlMessageRepository(MessageRepository):
    """SQLAlchemy-backed message repository."""

    def __init__(self, session):
        self._session = session

    def save(self, message: Message) -> Message:
        existing = self._session.query(MessageModel).filter(
            MessageModel.id == message.id
        ).first()

        def _val(enum_or_str):
            return enum_or_str.value if hasattr(enum_or_str, "value") else str(enum_or_str)

        if existing:
            existing.status = _val(message.status)
            existing.sentiment = message.sentiment
            existing.objection_type = message.objection_type
            existing.draft_response = message.draft_response
            existing.sent_at = message.sent_at
            existing.received_at = message.received_at
            existing.body = message.body
            existing.subject = message.subject
        else:
            model = MessageModel(
                id=message.id,
                campaign_id=message.campaign_id,
                lead_id=message.lead_id,
                direction=_val(message.direction),
                channel=_val(message.channel),
                subject=message.subject,
                body=message.body,
                status=_val(message.status),
                sentiment=message.sentiment,
                objection_type=message.objection_type,
                draft_response=message.draft_response,
                sent_at=message.sent_at,
                received_at=message.received_at,
                created_at=message.created_at,
            )
            self._session.add(model)

        self._session.flush()
        return message

    def find_by_id(self, message_id: str) -> Message | None:
        model = self._session.query(MessageModel).filter(
            MessageModel.id == message_id
        ).first()
        return self._to_entity(model) if model else None

    def find_by_lead(self, lead_id: str) -> list[Message]:
        models = (
            self._session.query(MessageModel)
            .filter(MessageModel.lead_id == lead_id)
            .order_by(MessageModel.created_at)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def find_by_campaign(self, campaign_id: str) -> list[Message]:
        models = (
            self._session.query(MessageModel)
            .filter(MessageModel.campaign_id == campaign_id)
            .order_by(MessageModel.created_at)
            .all()
        )
        return [self._to_entity(m) for m in models]

    def find_drafts(self) -> list[Message]:
        models = (
            self._session.query(MessageModel)
            .filter(MessageModel.status == "draft")
            .order_by(MessageModel.created_at.desc())
            .all()
        )
        return [self._to_entity(m) for m in models]

    def _to_entity(self, model: MessageModel) -> Message:
        try:
            channel = Channel(model.channel)
        except ValueError:
            channel = Channel.EMAIL

        try:
            direction = MessageDirection(model.direction)
        except ValueError:
            direction = MessageDirection.OUTBOUND

        try:
            status = MessageStatus(model.status)
        except ValueError:
            status = MessageStatus.QUEUED

        msg = Message(
            id=model.id,
            campaign_id=model.campaign_id,
            lead_id=model.lead_id,
            channel=channel,
            direction=direction,
            subject=model.subject,
            body=model.body,
            status=status,
            sentiment=model.sentiment,
            objection_type=model.objection_type,
            draft_response=model.draft_response,
            sent_at=model.sent_at,
            received_at=model.received_at,
            created_at=model.created_at or datetime.now(timezone.utc),
        )
        return msg
