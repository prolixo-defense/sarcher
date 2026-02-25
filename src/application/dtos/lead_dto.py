from datetime import datetime
from typing import Any
from pydantic import BaseModel, model_validator, Field

from src.domain.enums import DataSource, EnrichmentStatus, LeadStatus


class LeadCreateDTO(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    source: DataSource = DataSource.MANUAL
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_data: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_name_or_email(self) -> "LeadCreateDTO":
        has_name = bool(self.first_name.strip() or self.last_name.strip())
        has_email = bool((self.email or "").strip())
        if not has_name and not has_email:
            raise ValueError("At least a name (first_name/last_name) or email is required.")
        return self


class LeadUpdateDTO(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    status: LeadStatus | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = None


class LeadResponseDTO(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    job_title: str | None
    company_name: str | None
    company_domain: str | None
    linkedin_url: str | None
    location: str | None
    status: LeadStatus
    source: DataSource
    enrichment_status: EnrichmentStatus
    confidence_score: float
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class LeadSearchDTO(BaseModel):
    status: LeadStatus | None = None
    source: DataSource | None = None
    enrichment_status: EnrichmentStatus | None = None
    keyword: str | None = None
    company_domain: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class LeadExportDTO(BaseModel):
    format: str = Field(default="csv", pattern="^(csv|json)$")
    filters: LeadSearchDTO = Field(default_factory=LeadSearchDTO)
