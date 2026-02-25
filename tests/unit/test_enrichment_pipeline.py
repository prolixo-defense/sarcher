"""
Tests for EnrichmentPipeline — waterfall enrichment logic.

All external adapters (Apollo, Hunter) and CreditManager are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource
from src.infrastructure.enrichment.enrichment_pipeline import EnrichmentPipeline


def _make_lead(
    first_name="Alice",
    last_name="Smith",
    domain="acme.com",
    email=None,
    company_name=None,
):
    return Lead(
        first_name=first_name,
        last_name=last_name,
        source=DataSource.CORPORATE_WEBSITE,
        company_domain=domain,
        email=email,
        company_name=company_name,
    )


def _make_pipeline(
    apollo_person_result=None,
    apollo_org_result=None,
    hunter_result=None,
    apollo_budget=100,
    hunter_budget=25,
    enrich_phone=False,
):
    apollo = AsyncMock()
    apollo.match_person = AsyncMock(return_value=apollo_person_result)
    apollo.enrich_organization = AsyncMock(return_value=apollo_org_result)

    hunter = AsyncMock()
    hunter.find_email = AsyncMock(return_value=hunter_result)

    # CreditManager: can_spend returns True when budget > 0
    credit_mgr = AsyncMock()
    credit_mgr.can_spend = AsyncMock(
        side_effect=lambda provider, credits=1: (
            apollo_budget > 0 if provider == "apollo" else hunter_budget > 0
        )
    )
    credit_mgr.record_spend = AsyncMock()

    settings = MagicMock()
    settings.enrich_phone = enrich_phone

    return EnrichmentPipeline(apollo, hunter, credit_mgr, settings=settings)


# ---------------------------------------------------------------------------
# Apollo path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_populates_email_from_apollo():
    pipeline = _make_pipeline(
        apollo_person_result={
            "email": "alice@acme.com",
            "job_title": "CEO",
            "phone": None,
            "linkedin_url": None,
        }
    )
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    assert enriched.email == "alice@acme.com"


@pytest.mark.asyncio
async def test_enrich_sets_job_title_from_apollo():
    pipeline = _make_pipeline(
        apollo_person_result={
            "email": "a@b.com",
            "job_title": "CTO",
            "phone": None,
            "linkedin_url": None,
        }
    )
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    assert enriched.job_title == "CTO"


@pytest.mark.asyncio
async def test_enrich_does_not_overwrite_existing_email():
    pipeline = _make_pipeline(
        apollo_person_result={
            "email": "new@acme.com",
            "job_title": None,
            "phone": None,
            "linkedin_url": None,
        }
    )
    lead = _make_lead(email="existing@acme.com")
    enriched = await pipeline.enrich(lead)
    assert enriched.email == "existing@acme.com"


@pytest.mark.asyncio
async def test_enrich_populates_company_name_from_apollo_org():
    pipeline = _make_pipeline(
        apollo_org_result={
            "name": "Acme Corp",
            "industry": "Tech",
            "employee_count": 100,
            "annual_revenue": None,
            "technologies": [],
            "location": "SF",
        }
    )
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    assert enriched.company_name == "Acme Corp"


@pytest.mark.asyncio
async def test_enrich_skips_apollo_when_budget_zero():
    pipeline = _make_pipeline(apollo_budget=0)
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    # Apollo should never have been called
    pipeline._apollo.match_person.assert_not_called()
    # No crash — enriched lead returned
    assert enriched is not None


# ---------------------------------------------------------------------------
# Hunter fallback path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_falls_back_to_hunter_when_apollo_returns_none():
    pipeline = _make_pipeline(
        apollo_person_result=None,
        hunter_result={"email": "alice@acme.com", "confidence": 90},
    )
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    assert enriched.email == "alice@acme.com"


@pytest.mark.asyncio
async def test_enrich_skips_hunter_when_apollo_found_email():
    """If Apollo already found an email, Hunter should not be called."""
    pipeline = _make_pipeline(
        apollo_person_result={
            "email": "apollo@acme.com",
            "job_title": None,
            "phone": None,
            "linkedin_url": None,
        },
        hunter_result={"email": "hunter@acme.com"},
    )
    lead = _make_lead()
    enriched = await pipeline.enrich(lead)
    assert enriched.email == "apollo@acme.com"
    pipeline._hunter.find_email.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_skips_hunter_when_budget_zero():
    pipeline = _make_pipeline(apollo_person_result=None, hunter_budget=0)
    lead = _make_lead()
    await pipeline.enrich(lead)
    pipeline._hunter.find_email.assert_not_called()


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_batch_returns_all_leads():
    pipeline = _make_pipeline()
    leads = [_make_lead(first_name=f"Person{i}", last_name=f"Last{i}") for i in range(5)]
    results = await pipeline.enrich_batch(leads)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_enrich_batch_handles_individual_failure():
    """A failure for one lead should not prevent others from being enriched."""
    pipeline = _make_pipeline()
    pipeline._apollo.match_person = AsyncMock(side_effect=Exception("API error"))

    leads = [_make_lead(first_name=f"P{i}") for i in range(3)]
    # Should not raise, just return leads unchanged
    results = await pipeline.enrich_batch(leads)
    assert len(results) == 3
