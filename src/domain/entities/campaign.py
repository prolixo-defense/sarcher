import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.domain.enums import CampaignStatus


@dataclass
class CampaignSettings:
    daily_email_limit: int = 50
    daily_linkedin_limit: int = 25
    timezone: str = "America/New_York"
    business_hours_start: int = 9
    business_hours_end: int = 18
    business_days: list[str] = field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )


@dataclass
class CampaignStats:
    sent: int = 0
    opened: int = 0
    replied: int = 0
    bounced: int = 0
    opted_out: int = 0


@dataclass
class Campaign:
    """An outreach campaign targeting a set of leads."""

    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: CampaignStatus = CampaignStatus.DRAFT
    target_filters: dict[str, Any] = field(default_factory=dict)
    # Sequence steps stored as list[dict] (serialized SequenceStep data)
    sequence_steps: list[dict] = field(default_factory=list)
    settings: CampaignSettings = field(default_factory=CampaignSettings)
    stats: CampaignStats = field(default_factory=CampaignStats)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
