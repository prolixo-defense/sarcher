"""
Tests for CreditManager — budget enforcement and credit tracking.

Uses an in-memory SQLite database so every test starts clean.
"""
import uuid
import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.infrastructure.database.connection import Base
from src.infrastructure.database.models import CreditUsageModel
from src.infrastructure.enrichment.credit_manager import CreditManager


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _settings(apollo_budget=100, hunter_budget=25):
    s = MagicMock()
    s.apollo_monthly_budget = apollo_budget
    s.hunter_monthly_budget = hunter_budget
    return s


# ---------------------------------------------------------------------------
# can_spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_spend_true_when_budget_available(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=100))
    assert await mgr.can_spend("apollo") is True


@pytest.mark.asyncio
async def test_can_spend_false_when_zero_budget(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=0))
    assert await mgr.can_spend("apollo") is False


@pytest.mark.asyncio
async def test_can_spend_false_when_exact_budget_consumed(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=2))
    await mgr.record_spend("apollo", 1, "lead-1")
    await mgr.record_spend("apollo", 1, "lead-2")
    db_session.commit()
    # Budget exactly consumed — one more credit should be blocked
    assert await mgr.can_spend("apollo") is False


@pytest.mark.asyncio
async def test_can_spend_true_if_partial_budget_used(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=10))
    await mgr.record_spend("apollo", 3, "lead-1")
    db_session.commit()
    assert await mgr.can_spend("apollo", 5) is True


@pytest.mark.asyncio
async def test_can_spend_unknown_provider_returns_false(db_session):
    mgr = CreditManager(db_session, _settings())
    assert await mgr.can_spend("unknown_provider") is False


# ---------------------------------------------------------------------------
# record_spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_spend_persists_record(db_session):
    mgr = CreditManager(db_session, _settings())
    await mgr.record_spend("apollo", 1, "lead-123", "people/match")
    db_session.commit()

    records = db_session.query(CreditUsageModel).all()
    assert len(records) == 1
    assert records[0].provider == "apollo"
    assert records[0].credits_used == 1
    assert records[0].lead_id == "lead-123"
    assert records[0].endpoint == "people/match"


@pytest.mark.asyncio
async def test_record_spend_sets_current_month(db_session):
    from datetime import datetime

    mgr = CreditManager(db_session, _settings())
    await mgr.record_spend("hunter", 1, "lead-999")
    db_session.commit()

    record = db_session.query(CreditUsageModel).first()
    expected_month = datetime.now().strftime("%Y-%m")
    assert record.month == expected_month


# ---------------------------------------------------------------------------
# get_usage_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_summary_returns_dict(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=100, hunter_budget=25))
    summary = await mgr.get_usage_summary()

    assert "apollo" in summary
    assert "hunter" in summary
    assert summary["apollo"]["budget"] == 100
    assert summary["hunter"]["budget"] == 25


@pytest.mark.asyncio
async def test_get_usage_summary_reflects_spend(db_session):
    mgr = CreditManager(db_session, _settings(apollo_budget=100))
    await mgr.record_spend("apollo", 3, "lead-1")
    db_session.commit()

    summary = await mgr.get_usage_summary()
    assert summary["apollo"]["used"] == 3
    assert summary["apollo"]["remaining"] == 97


@pytest.mark.asyncio
async def test_monthly_isolation(db_session):
    """Credits from a past month should not count against this month's budget."""
    old = CreditUsageModel(
        id=str(uuid.uuid4()),
        provider="apollo",
        credits_used=99,
        lead_id="old-lead",
        endpoint="test",
        month="2024-01",  # clearly in the past
    )
    db_session.add(old)
    db_session.commit()

    mgr = CreditManager(db_session, _settings(apollo_budget=100))
    # Current month should still have full budget
    assert await mgr.can_spend("apollo", 5) is True
