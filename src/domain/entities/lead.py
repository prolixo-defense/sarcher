import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.domain.enums import DataSource, EnrichmentStatus, LeadStatus


@dataclass
class Lead:
    first_name: str
    last_name: str
    source: DataSource
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    status: LeadStatus = LeadStatus.RAW
    enrichment_status: EnrichmentStatus = EnrichmentStatus.PENDING
    confidence_score: float = 1.0
    raw_data: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def validate(self) -> None:
        """Check basic integrity — at least a name or email must exist."""
        has_name = bool((self.first_name or "").strip() or (self.last_name or "").strip())
        has_email = bool((self.email or "").strip())
        if not has_name and not has_email:
            raise ValueError("Lead must have at least a name or an email address.")
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError(f"confidence_score must be between 0.0 and 1.0, got {self.confidence_score}")

    def is_expired(self) -> bool:
        """Return True if this lead's TTL has passed."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
