"""
Integration tests for Phase 3 enrichment pipeline.

Uses a real in-memory SQLite database. All external API calls (Apollo, Hunter)
and LLM calls are mocked so no network or Ollama is required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, EnrichmentStatus
from src.infrastructure.database.connection import Base
from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
from src.infrastructure.enrichment.credit_manager import CreditManager
from src.infrastructure.enrichment.enrichment_pipeline import EnrichmentPipeline
from src.application.use_cases.enrich_lead import EnrichLead
from src.application.use_cases.ingest_lead import IngestLead
from src.application.dtos.lead_dto import LeadCreateDTO
from src.application.services.deduplication import DeduplicationService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _settings():
    s = MagicMock()
    s.apollo_monthly_budget = 100
    s.hunter_monthly_budget = 25
    s.enrich_phone = False
    return s


def _ingest(db_session, first_name="Alice", last_name="Smith", domain="acme.com"):
    """Ingest a raw lead and return the Lead entity."""
    repo = SqlLeadRepository(db_session)
    dedup = DeduplicationService(repo)
    use_case = IngestLead(repo, dedup)
    dto = LeadCreateDTO(
        first_name=first_name,
        last_name=last_name,
        company_domain=domain,
        source=DataSource.CORPORATE_WEBSITE,
        confidence_score=0.8,
    )
    lead = use_case.execute(dto)
    db_session.commit()
    return lead


# ---------------------------------------------------------------------------
# EnrichLead use case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_lead_updates_status_to_completed(db_session):
    lead = _ingest(db_session)
    assert lead.enrichment_status == EnrichmentStatus.PENDING

    mock_pipeline = AsyncMock()

    async def _mock_enrich(l):
        l.email = "alice@acme.com"
        return l

    mock_pipeline.enrich = _mock_enrich

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo, enrichment_pipeline=mock_pipeline)
    enriched = await use_case.execute_async(lead.id)
    db_session.commit()

    assert enriched.enrichment_status == EnrichmentStatus.COMPLETED
    assert enriched.email == "alice@acme.com"


@pytest.mark.asyncio
async def test_enrich_lead_skips_already_completed(db_session):
    lead = _ingest(db_session)

    repo = SqlLeadRepository(db_session)
    lead.enrichment_status = EnrichmentStatus.COMPLETED
    repo.save(lead)
    db_session.commit()

    mock_pipeline = AsyncMock()
    use_case = EnrichLead(repo, enrichment_pipeline=mock_pipeline)
    result = await use_case.execute_async(lead.id)

    mock_pipeline.enrich.assert_not_called()
    assert result.enrichment_status == EnrichmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_enrich_lead_marks_failed_on_pipeline_error(db_session):
    lead = _ingest(db_session)

    mock_pipeline = AsyncMock()
    mock_pipeline.enrich = AsyncMock(side_effect=RuntimeError("API timeout"))

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo, enrichment_pipeline=mock_pipeline)

    with pytest.raises(RuntimeError, match="API timeout"):
        await use_case.execute_async(lead.id)

    db_session.commit()
    refreshed = repo.find_by_id(lead.id)
    assert refreshed.enrichment_status == EnrichmentStatus.FAILED


@pytest.mark.asyncio
async def test_enrich_lead_falls_back_to_skipped_when_no_pipeline(db_session):
    """Without pipeline or adapter, lead should be marked SKIPPED."""
    lead = _ingest(db_session)

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo)  # no pipeline, no adapter
    result = use_case.execute(lead.id)
    db_session.commit()

    assert result.enrichment_status == EnrichmentStatus.SKIPPED


# ---------------------------------------------------------------------------
# Full pipeline integration test (mock adapters + real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_enriches_lead_in_db(db_session):
    """End-to-end: ingest → pipeline → DB reflects enriched data."""
    lead = _ingest(db_session, first_name="Bob", last_name="Jones")

    # Mock Apollo returning good data
    apollo = AsyncMock()
    apollo.match_person = AsyncMock(
        return_value={
            "email": "bob@acme.com",
            "job_title": "VP Engineering",
            "phone": None,
            "linkedin_url": "https://linkedin.com/in/bob",
        }
    )
    apollo.enrich_organization = AsyncMock(
        return_value={
            "name": "Acme Corp",
            "industry": "Technology",
            "employee_count": 200,
            "annual_revenue": "$5M",
            "technologies": ["Python"],
            "location": "New York",
        }
    )
    hunter = AsyncMock()
    hunter.find_email = AsyncMock(return_value=None)

    credit_mgr = CreditManager(db_session, _settings())
    pipeline = EnrichmentPipeline(apollo, hunter, credit_mgr, _settings())

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo, enrichment_pipeline=pipeline)
    enriched = await use_case.execute_async(lead.id)
    db_session.commit()

    assert enriched.email == "bob@acme.com"
    assert enriched.job_title == "VP Engineering"
    assert enriched.company_name == "Acme Corp"
    assert enriched.enrichment_status == EnrichmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_uses_hunter_when_apollo_finds_no_email(db_session):
    """Hunter should be tried when Apollo returns no email."""
    lead = _ingest(db_session)

    apollo = AsyncMock()
    apollo.match_person = AsyncMock(return_value=None)
    apollo.enrich_organization = AsyncMock(return_value=None)

    hunter = AsyncMock()
    hunter.find_email = AsyncMock(
        return_value={"email": "alice@acme.com", "confidence": 85}
    )

    credit_mgr = CreditManager(db_session, _settings())
    pipeline = EnrichmentPipeline(apollo, hunter, credit_mgr, _settings())

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo, enrichment_pipeline=pipeline)
    enriched = await use_case.execute_async(lead.id)
    db_session.commit()

    assert enriched.email == "alice@acme.com"
    assert enriched.enrichment_status == EnrichmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_credit_usage_recorded_in_db(db_session):
    """Credit spend records should be persisted after enrichment."""
    from src.infrastructure.database.models import CreditUsageModel

    lead = _ingest(db_session)

    apollo = AsyncMock()
    apollo.match_person = AsyncMock(
        return_value={"email": "a@b.com", "job_title": None, "phone": None, "linkedin_url": None}
    )
    apollo.enrich_organization = AsyncMock(return_value=None)
    hunter = AsyncMock()
    hunter.find_email = AsyncMock(return_value=None)

    credit_mgr = CreditManager(db_session, _settings())
    pipeline = EnrichmentPipeline(apollo, hunter, credit_mgr, _settings())

    repo = SqlLeadRepository(db_session)
    use_case = EnrichLead(repo, enrichment_pipeline=pipeline)
    await use_case.execute_async(lead.id)
    db_session.commit()

    # At least one Apollo credit should have been recorded
    records = db_session.query(CreditUsageModel).filter(
        CreditUsageModel.provider == "apollo"
    ).all()
    assert len(records) >= 1
