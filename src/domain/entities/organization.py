import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.domain.enums import DataSource


@dataclass
class Organization:
    name: str
    source: DataSource
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: str | None = None
    location: str | None = None
    description: str | None = None
    technologies: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Organization must have a name.")
