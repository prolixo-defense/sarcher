import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.domain.enums import Channel, MessageDirection, MessageStatus


@dataclass
class Message:
    """A sent or received message."""

    lead_id: str
    channel: Channel
    direction: MessageDirection
    body: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str | None = None
    subject: str | None = None
    status: MessageStatus = MessageStatus.QUEUED
    sentiment: str | None = None
    objection_type: str | None = None
    draft_response: str | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
