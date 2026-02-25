"""
Pydantic schemas for LLM extraction output.

These models define exactly what the LLM must output.
The instructor library enforces schema compliance via retries.
"""
from typing import Optional
from pydantic import BaseModel, Field


class ExtractedPerson(BaseModel):
    """Schema for a person extracted from a web page."""

    full_name: str = Field(description="Full name of the person")
    first_name: Optional[str] = Field(None, description="First/given name")
    last_name: Optional[str] = Field(None, description="Last/family name")
    job_title: Optional[str] = Field(None, description="Current job title or role")
    email: Optional[str] = Field(None, description="Email address if found")
    phone: Optional[str] = Field(None, description="Phone number if found")
    linkedin_url: Optional[str] = Field(None, description="LinkedIn profile URL if found")
    department: Optional[str] = Field(
        None, description="Department (e.g., Engineering, Sales)"
    )
    seniority: Optional[str] = Field(
        None,
        description="Seniority level (C-suite, VP, Director, Manager, Individual)",
    )


class ExtractedCompany(BaseModel):
    """Schema for company information extracted from a web page."""

    name: str = Field(description="Company name")
    domain: Optional[str] = Field(None, description="Company website domain")
    industry: Optional[str] = Field(None, description="Industry or sector")
    description: Optional[str] = Field(
        None, description="Brief company description, max 200 chars"
    )
    employee_count_estimate: Optional[str] = Field(
        None, description="Estimated employee count or range"
    )
    location: Optional[str] = Field(None, description="Headquarters location")
    technologies: list[str] = Field(
        default_factory=list, description="Technologies/products mentioned"
    )


class PageExtractionResult(BaseModel):
    """Complete extraction result from a single web page."""

    people: list[ExtractedPerson] = Field(default_factory=list)
    company: Optional[ExtractedCompany] = None
    page_type: str = Field(
        description="Type of page: team, about, contact, profile, directory_listing"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Overall extraction confidence"
    )
    extraction_notes: Optional[str] = Field(
        None, description="Any caveats about the extraction"
    )
