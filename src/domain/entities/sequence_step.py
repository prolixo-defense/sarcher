import uuid
from dataclasses import dataclass, field

from src.domain.enums import Channel


@dataclass
class SequenceStep:
    """A single step in an outreach sequence."""

    campaign_id: str
    step_number: int
    channel: Channel
    template_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    delay_days: int = 1
    condition: str | None = None  # e.g. "no_reply" — only run if no reply to previous
    is_active: bool = True
