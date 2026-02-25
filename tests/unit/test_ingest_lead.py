import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from src.application.dtos.lead_dto import LeadCreateDTO
from src.application.services.deduplication import DeduplicationService, DeduplicationResult
from src.application.use_cases.ingest_lead import IngestLead
from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, LeadStatus


def make_dto(**kwargs):
    defaults = dict(
        first_name="Alice",
        last_name="Wonder",
        email="alice@example.com",
        company_name="Acme Corp",
        company_domain="acme.com",
        source=DataSource.MANUAL,
    )
    defaults.update(kwargs)
    return LeadCreateDTO(**defaults)


class TestIngestLeadHappyPath:
    def test_creates_new_lead(self):
        repo = MagicMock()
        dedup = MagicMock()
        dedup.find_duplicate.return_value = DeduplicationResult(
            is_duplicate=False, matched_lead=None, score=0, match_reason=""
        )
        repo.upsert.side_effect = lambda lead: lead

        use_case = IngestLead(repo, dedup)
        result = use_case.execute(make_dto())

        assert result.first_name == "Alice"
        assert result.email == "alice@example.com"
        assert result.expires_at is not None
        repo.upsert.assert_called_once()

    def test_email_normalized_to_lowercase(self):
        repo = MagicMock()
        dedup = MagicMock()
        dedup.find_duplicate.return_value = DeduplicationResult(
            is_duplicate=False, matched_lead=None, score=0, match_reason=""
        )
        repo.upsert.side_effect = lambda lead: lead

        use_case = IngestLead(repo, dedup)
        result = use_case.execute(make_dto(email="ALICE@EXAMPLE.COM"))
        assert result.email == "alice@example.com"

    def test_expires_at_set(self):
        repo = MagicMock()
        dedup = MagicMock()
        dedup.find_duplicate.return_value = DeduplicationResult(
            is_duplicate=False, matched_lead=None, score=0, match_reason=""
        )
        repo.upsert.side_effect = lambda lead: lead

        use_case = IngestLead(repo, dedup)
        result = use_case.execute(make_dto())
        assert result.expires_at is not None
        delta = result.expires_at - datetime.now(timezone.utc)
        assert 170 < delta.days < 185  # ~180 days


class TestIngestLeadDuplicateDetection:
    def test_merges_duplicate(self):
        existing_lead = Lead(
            first_name="Alice",
            last_name="Wonder",
            email="alice@example.com",
            source=DataSource.MANUAL,
            confidence_score=0.7,
        )
        repo = MagicMock()
        dedup = MagicMock()
        dedup.find_duplicate.return_value = DeduplicationResult(
            is_duplicate=True,
            matched_lead=existing_lead,
            score=100,
            match_reason="exact_email",
        )
        dedup.merge.return_value = existing_lead
        repo.save.return_value = existing_lead

        use_case = IngestLead(repo, dedup)
        result = use_case.execute(make_dto())

        dedup.merge.assert_called_once()
        repo.save.assert_called_once()
        assert result is existing_lead


class TestIngestLeadValidation:
    def test_raises_on_no_name_or_email(self):
        repo = MagicMock()
        dedup = MagicMock()
        use_case = IngestLead(repo, dedup)
        with pytest.raises(Exception):
            use_case.execute(LeadCreateDTO(first_name="", last_name="", email=None,
                                           source=DataSource.MANUAL))
