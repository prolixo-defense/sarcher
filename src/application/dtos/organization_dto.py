from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

from src.domain.enums import DataSource


class OrganizationCreateDTO(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: str | None = None
    location: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    source: DataSource = DataSource.MANUAL
    raw_data: dict[str, Any] | None = None


class OrganizationResponseDTO(BaseModel):
    id: str
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    annual_revenue: str | None
    location: str | None
    description: str | None
    technologies: list[str]
    source: DataSource
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
