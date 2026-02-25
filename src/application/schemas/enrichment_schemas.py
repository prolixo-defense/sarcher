"""
Pydantic schemas for enrichment API responses (Apollo, Hunter).
Used for validation and type safety when processing API results.
"""
from typing import Optional
from pydantic import BaseModel, Field


class ApolloPersonResult(BaseModel):
    """Schema for Apollo.io person match response."""

    email: Optional[str] = None
    job_title: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    confidence_score: float = 0.0


class ApolloOrganizationResult(BaseModel):
    """Schema for Apollo.io organization enrich response."""

    name: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    location: Optional[str] = None


class HunterEmailResult(BaseModel):
    """Schema for Hunter.io email finder response."""

    email: Optional[str] = None
    confidence: int = 0
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class HunterVerificationResult(BaseModel):
    """Schema for Hunter.io email verification response."""

    status: str = "unknown"
    score: int = 0
    is_valid: bool = False
