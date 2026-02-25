"""
Tests for GDPRManager — opt-out, DSAR, suppression list, retention cleanup.

Uses an in-memory SQLite database so each test starts clean.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.infrastructure.database.connection import Base
from src.infrastructure.database.models import LeadModel, MessageModel, SuppressionListModel
from src.infrastructure.compliance.gdpr_manager import GDPRManager


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _add_lead(session, email="alice@acme.com", status="raw") -> LeadModel:
    lead = LeadModel(
        id=str(uuid.uuid4()),
        first_name="Alice",
        last_name="Smith",
        email=email,
        status=status,
        source="corporate_website",
        enrichment_status="pending",
        confidence_score=0.8,
    )
    session.add(lead)
    session.commit()
    return lead


# ---------------------------------------------------------------------------
# Suppression list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_to_suppression_creates_record(db_session):
    gdpr = GDPRManager(db_session)
    await gdpr.add_to_suppression("alice@acme.com", reason="manual")
    db_session.commit()

    records = db_session.query(SuppressionListModel).all()
    assert len(records) == 1
    assert records[0].email == "alice@acme.com"
    assert records[0].reason == "manual"


@pytest.mark.asyncio
async def test_add_to_suppression_is_idempotent(db_session):
    gdpr = GDPRManager(db_session)
    await gdpr.add_to_suppression("alice@acme.com", reason="manual")
    await gdpr.add_to_suppression("alice@acme.com", reason="manual")  # again
    db_session.commit()

    records = db_session.query(SuppressionListModel).all()
    assert len(records) == 1  # Not duplicated


@pytest.mark.asyncio
async def test_check_suppression_returns_true_for_suppressed(db_session):
    gdpr = GDPRManager(db_session)
    await gdpr.add_to_suppression("blocked@example.com")
    db_session.commit()
    assert await gdpr.check_suppression("blocked@example.com") is True


@pytest.mark.asyncio
async def test_check_suppression_returns_false_for_unknown(db_session):
    gdpr = GDPRManager(db_session)
    assert await gdpr.check_suppression("unknown@example.com") is False


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_opt_out_updates_lead_status(db_session):
    lead = _add_lead(db_session)
    gdpr = GDPRManager(db_session)
    result = await gdpr.process_opt_out(lead.id)
    db_session.commit()

    assert result["success"] is True
    refreshed = db_session.query(LeadModel).filter(LeadModel.id == lead.id).first()
    assert refreshed.status == "opted_out"


@pytest.mark.asyncio
async def test_process_opt_out_adds_to_suppression(db_session):
    lead = _add_lead(db_session, email="test@example.com")
    gdpr = GDPRManager(db_session)
    await gdpr.process_opt_out(lead.id)
    db_session.commit()

    assert await gdpr.check_suppression("test@example.com") is True


@pytest.mark.asyncio
async def test_process_opt_out_returns_error_for_missing_lead(db_session):
    gdpr = GDPRManager(db_session)
    result = await gdpr.process_opt_out("nonexistent-id")
    assert result["success"] is False


# ---------------------------------------------------------------------------
# DSAR export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsar_export_returns_lead_data(db_session):
    lead = _add_lead(db_session, email="alice@acme.com")
    gdpr = GDPRManager(db_session)
    result = await gdpr.handle_dsar_export("alice@acme.com")
    db_session.commit()

    assert result["found"] is True
    assert result["data"]["lead"]["email"] == "alice@acme.com"


@pytest.mark.asyncio
async def test_dsar_export_returns_not_found_for_unknown(db_session):
    gdpr = GDPRManager(db_session)
    result = await gdpr.handle_dsar_export("nobody@nowhere.com")
    assert result["found"] is False


# ---------------------------------------------------------------------------
# DSAR delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsar_delete_anonymizes_lead(db_session):
    lead = _add_lead(db_session, email="delete@example.com")
    gdpr = GDPRManager(db_session)
    result = await gdpr.handle_dsar_delete("delete@example.com")
    db_session.commit()

    assert result["success"] is True
    refreshed = db_session.query(LeadModel).filter(LeadModel.id == lead.id).first()
    assert refreshed.email is None
    assert refreshed.first_name == "[DELETED]"


@pytest.mark.asyncio
async def test_dsar_delete_adds_to_suppression(db_session):
    lead = _add_lead(db_session, email="delete2@example.com")
    gdpr = GDPRManager(db_session)
    await gdpr.handle_dsar_delete("delete2@example.com")
    db_session.commit()

    assert await gdpr.check_suppression("delete2@example.com") is True
