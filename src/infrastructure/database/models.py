import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
)
from sqlalchemy.types import TypeDecorator

from src.infrastructure.database.connection import Base


class JSONEncodedList(TypeDecorator):
    """Stores a Python list as a JSON string."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return "[]"
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return json.loads(value)


class JSONEncodedDict(TypeDecorator):
    """Stores a Python dict as a JSON string."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class LeadModel(Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True)
    first_name = Column(String(255), nullable=False, default="")
    last_name = Column(String(255), nullable=False, default="")
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(50), nullable=True)
    job_title = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    company_domain = Column(String(255), nullable=True, index=True)
    linkedin_url = Column(String(500), nullable=True)
    location = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="raw", index=True)
    source = Column(String(50), nullable=False, default="manual")
    enrichment_status = Column(String(50), nullable=False, default="pending")
    confidence_score = Column(Float, nullable=False, default=1.0)
    raw_data = Column(JSONEncodedDict, nullable=True)
    tags = Column(JSONEncodedList, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_leads_email_company", "email", "company_domain"),
    )


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    domain = Column(String(255), nullable=True, index=True, unique=True)
    industry = Column(String(255), nullable=True)
    employee_count = Column(Integer, nullable=True)
    annual_revenue = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    technologies = Column(JSONEncodedList, nullable=False, default=list)
    source = Column(String(50), nullable=False, default="manual")
    raw_data = Column(JSONEncodedDict, nullable=True)
    cage_code = Column(String(10), nullable=True, index=True)
    uei = Column(String(12), nullable=True, index=True)
    naics_codes = Column(JSONEncodedList, nullable=True)
    size_band = Column(String(20), nullable=True)
    segment = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())


class CampaignModel(Base):
    """Outreach campaign."""

    __tablename__ = "campaigns"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="draft", index=True)
    target_filters = Column(JSONEncodedDict, nullable=True)
    settings = Column(JSONEncodedDict, nullable=True)
    stats = Column(JSONEncodedDict, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SequenceStepModel(Base):
    """A step in a campaign outreach sequence."""

    __tablename__ = "sequence_steps"

    id = Column(String(36), primary_key=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    channel = Column(String(50), nullable=False)
    template_id = Column(String(255), nullable=True)
    delay_days = Column(Integer, nullable=False, default=1)
    condition = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class MessageModel(Base):
    """A sent or received outreach message."""

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id"), nullable=False, index=True)
    direction = Column(String(20), nullable=False)  # outbound / inbound
    channel = Column(String(50), nullable=False)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="queued", index=True)
    sentiment = Column(String(100), nullable=True)
    objection_type = Column(String(100), nullable=True)
    draft_response = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SuppressionListModel(Base):
    """Permanent suppression list — emails/domains never to contact."""

    __tablename__ = "suppression_list"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    reason = Column(String(500), nullable=True)
    source = Column(String(50), nullable=True)  # opt_out, bounce, manual, dsar
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ComplianceRequestModel(Base):
    """GDPR/CCPA data subject requests (DSAR, opt-out, etc.)."""

    __tablename__ = "compliance_requests"

    id = Column(String(36), primary_key=True)
    request_type = Column(String(50), nullable=False)  # dsar_export, dsar_delete, opt_out
    email = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    result = Column(JSONEncodedDict, nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CreditUsageModel(Base):
    """Tracks enrichment API credit usage per provider per month."""

    __tablename__ = "credit_usage"

    id = Column(String(36), primary_key=True)
    provider = Column(String(50), nullable=False)       # "apollo", "hunter"
    credits_used = Column(Integer, nullable=False)
    lead_id = Column(String(36), nullable=True)         # which lead this was for
    endpoint = Column(String(100), nullable=True)       # which API endpoint
    month = Column(String(7), nullable=False)           # "2026-02" for monthly tracking
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_credit_usage_provider_month", "provider", "month"),
    )
