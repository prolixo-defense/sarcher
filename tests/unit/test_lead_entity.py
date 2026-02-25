import pytest
from datetime import datetime, timedelta, timezone

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, EnrichmentStatus, LeadStatus


def make_lead(**kwargs):
    defaults = dict(first_name="Jane", last_name="Doe", source=DataSource.MANUAL)
    defaults.update(kwargs)
    return Lead(**defaults)


class TestLeadCreation:
    def test_creates_lead_with_defaults(self):
        lead = make_lead()
        assert lead.first_name == "Jane"
        assert lead.last_name == "Doe"
        assert lead.status == LeadStatus.RAW
        assert lead.enrichment_status == EnrichmentStatus.PENDING
        assert lead.confidence_score == 1.0
        assert lead.tags == []
        assert lead.id is not None

    def test_full_name(self):
        lead = make_lead(first_name="John", last_name="Smith")
        assert lead.full_name() == "John Smith"

    def test_full_name_only_first(self):
        lead = make_lead(first_name="Madonna", last_name="")
        assert lead.full_name() == "Madonna"


class TestLeadValidation:
    def test_valid_lead_with_name(self):
        lead = make_lead(first_name="Jane", last_name="")
        lead.validate()  # should not raise

    def test_valid_lead_with_email_only(self):
        lead = make_lead(first_name="", last_name="", email="test@example.com")
        lead.validate()  # should not raise

    def test_invalid_lead_no_name_or_email(self):
        lead = make_lead(first_name="", last_name="", email=None)
        with pytest.raises(ValueError, match="at least a name or an email"):
            lead.validate()

    def test_invalid_confidence_score_too_high(self):
        lead = make_lead(confidence_score=1.5)
        with pytest.raises(ValueError, match="confidence_score"):
            lead.validate()

    def test_invalid_confidence_score_negative(self):
        lead = make_lead(confidence_score=-0.1)
        with pytest.raises(ValueError, match="confidence_score"):
            lead.validate()


class TestLeadExpiry:
    def test_not_expired_without_expires_at(self):
        lead = make_lead()
        assert lead.is_expired() is False

    def test_not_expired_with_future_date(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        lead = make_lead(expires_at=future)
        assert lead.is_expired() is False

    def test_expired_with_past_date(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        lead = make_lead(expires_at=past)
        assert lead.is_expired() is True

    def test_expired_with_naive_datetime(self):
        past = datetime.utcnow() - timedelta(days=1)
        lead = make_lead(expires_at=past)
        assert lead.is_expired() is True
