import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ComplianceRequest:
    """A GDPR/CCPA data subject request."""

    request_type: str  # "dsar_export", "dsar_delete", "opt_out"
    email: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"  # pending, processing, completed
    result: dict[str, Any] | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
