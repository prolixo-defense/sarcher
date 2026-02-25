"""
Integration tests for Phase 4 campaign, compliance, and outreach system.

Uses a real in-memory SQLite database.
All external calls (SMTP, LinkedIn, LLM) are mocked.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, CampaignStatus, Channel, MessageDirection, MessageStatus
from src.infrastructure.database.connection import Base
from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
from src.infrastructure.database.repositories.sql_campaign_repository import SqlCampaignRepository
from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
from src.infrastructure.compliance.gdpr_manager import GDPRManager
from src.application.use_cases.ingest_lead import IngestLead
from src.application.use_cases.create_campaign import CreateCampaign
from src.application.dtos.lead_dto import LeadCreateDTO
from src.application.services.deduplication import DeduplicationService
from src.application.schemas.campaign_schemas import CampaignCreateDTO, SequenceStepCreateDTO


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _ingest_lead(db_session, email="alice@acme.com", first_name="Alice", last_name="Smith"):
    repo = SqlLeadRepository(db_session)
    dedup = DeduplicationService(repo)
    use_case = IngestLead(repo, dedup)
    dto = LeadCreateDTO(
        first_name=first_name,
        last_name=last_name,
        email=email,
        company_domain="acme.com",
        source=DataSource.CORPORATE_WEBSITE,
        confidence_score=0.9,
    )
    lead = use_case.execute(dto)
    db_session.commit()
    return lead


# ---------------------------------------------------------------------------
# Campaign creation tests
# ---------------------------------------------------------------------------


def test_create_campaign_persists_to_db(db_session):
    repo = SqlCampaignRepository(db_session)
    dto = CampaignCreateDTO(
        name="Q1 Outreach",
        sequence_steps=[
            SequenceStepCreateDTO(step_number=1, channel="email", template_id="initial_outreach", delay_days=0),
        ],
    )
    campaign = CreateCampaign(repo).execute(dto)
    db_session.commit()

    assert campaign.id is not None
    assert campaign.name == "Q1 Outreach"
    assert len(campaign.sequence_steps) == 1


def test_find_campaign_by_id(db_session):
    repo = SqlCampaignRepository(db_session)
    dto = CampaignCreateDTO(name="Test Campaign")
    campaign = CreateCampaign(repo).execute(dto)
    db_session.commit()

    found = repo.find_by_id(campaign.id)
    assert found is not None
    assert found.name == "Test Campaign"


def test_campaign_default_status_is_draft(db_session):
    repo = SqlCampaignRepository(db_session)
    campaign = CreateCampaign(repo).execute(CampaignCreateDTO(name="Draft Campaign"))
    db_session.commit()
    assert campaign.status == CampaignStatus.DRAFT


def test_activate_campaign(db_session):
    repo = SqlCampaignRepository(db_session)
    campaign = CreateCampaign(repo).execute(CampaignCreateDTO(name="Activatable"))
    db_session.commit()

    campaign.status = CampaignStatus.ACTIVE
    repo.save(campaign)
    db_session.commit()

    found = repo.find_by_id(campaign.id)
    assert found.status == CampaignStatus.ACTIVE


def test_list_campaigns_by_status(db_session):
    repo = SqlCampaignRepository(db_session)
    c1 = CreateCampaign(repo).execute(CampaignCreateDTO(name="Draft 1"))
    c2 = CreateCampaign(repo).execute(CampaignCreateDTO(name="Draft 2"))
    c2.status = CampaignStatus.ACTIVE
    repo.save(c2)
    db_session.commit()

    drafts = repo.find_all({"status": "draft"})
    assert len(drafts) == 1
    assert drafts[0].name == "Draft 1"


# ---------------------------------------------------------------------------
# Message repository tests
# ---------------------------------------------------------------------------


def test_save_and_find_message(db_session):
    lead = _ingest_lead(db_session)
    msg_repo = SqlMessageRepository(db_session)

    from src.domain.entities.message import Message
    msg = Message(
        lead_id=lead.id,
        channel=Channel.EMAIL,
        direction=MessageDirection.OUTBOUND,
        body="Hello Alice",
        status=MessageStatus.SENT,
    )
    saved = msg_repo.save(msg)
    db_session.commit()

    found = msg_repo.find_by_id(saved.id)
    assert found is not None
    assert found.body == "Hello Alice"
    assert found.channel == Channel.EMAIL


def test_find_drafts_returns_only_drafts(db_session):
    lead = _ingest_lead(db_session)
    msg_repo = SqlMessageRepository(db_session)

    from src.domain.entities.message import Message
    draft = Message(
        lead_id=lead.id,
        channel=Channel.EMAIL,
        direction=MessageDirection.OUTBOUND,
        body="Draft body",
        status=MessageStatus.DRAFT,
    )
    sent = Message(
        lead_id=lead.id,
        channel=Channel.EMAIL,
        direction=MessageDirection.OUTBOUND,
        body="Sent body",
        status=MessageStatus.SENT,
    )
    msg_repo.save(draft)
    msg_repo.save(sent)
    db_session.commit()

    drafts = msg_repo.find_drafts()
    assert len(drafts) == 1
    assert drafts[0].body == "Draft body"


# ---------------------------------------------------------------------------
# Compliance (GDPR) integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opt_out_flow_end_to_end(db_session):
    lead = _ingest_lead(db_session)
    gdpr = GDPRManager(db_session)

    result = await gdpr.process_opt_out(lead.id)
    db_session.commit()

    assert result["success"] is True
    # Lead status updated
    from src.infrastructure.database.models import LeadModel
    refreshed = db_session.query(LeadModel).filter(LeadModel.id == lead.id).first()
    assert refreshed.status == "opted_out"
    # Email suppressed
    assert await gdpr.check_suppression("alice@acme.com") is True


@pytest.mark.asyncio
async def test_dsar_delete_anonymizes_across_tables(db_session):
    lead = _ingest_lead(db_session)
    msg_repo = SqlMessageRepository(db_session)

    from src.domain.entities.message import Message
    msg = Message(
        lead_id=lead.id,
        channel=Channel.EMAIL,
        direction=MessageDirection.OUTBOUND,
        body="Sensitive content",
        status=MessageStatus.SENT,
    )
    msg_repo.save(msg)
    db_session.commit()

    gdpr = GDPRManager(db_session)
    result = await gdpr.handle_dsar_delete("alice@acme.com")
    db_session.commit()

    assert result["success"] is True
    # Lead anonymized
    from src.infrastructure.database.models import LeadModel, MessageModel
    lead_model = db_session.query(LeadModel).filter(LeadModel.id == lead.id).first()
    assert lead_model.email is None
    # Message anonymized
    messages = db_session.query(MessageModel).filter(MessageModel.lead_id == lead.id).all()
    assert all("[REDACTED" in m.body for m in messages)


@pytest.mark.asyncio
async def test_suppression_list_prevents_future_entries(db_session):
    gdpr = GDPRManager(db_session)
    await gdpr.add_to_suppression("blocked@example.com", reason="test")
    await gdpr.add_to_suppression("blocked@example.com", reason="test")  # duplicate
    db_session.commit()

    from src.infrastructure.database.models import SuppressionListModel
    count = db_session.query(SuppressionListModel).filter(
        SuppressionListModel.email == "blocked@example.com"
    ).count()
    assert count == 1
