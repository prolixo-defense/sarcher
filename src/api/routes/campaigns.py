from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreateRequest(BaseModel):
    name: str
    target_filters: dict[str, Any] = {}
    sequence_steps: list[dict] = []
    settings_override: dict[str, Any] = {}


class CampaignResponse(BaseModel):
    id: str
    name: str
    status: str
    step_count: int
    stats: dict
    created_at: str


def _campaign_to_response(campaign) -> dict:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status.value if hasattr(campaign.status, "value") else campaign.status,
        "step_count": len(campaign.sequence_steps),
        "stats": {
            "sent": campaign.stats.sent,
            "opened": campaign.stats.opened,
            "replied": campaign.stats.replied,
            "bounced": campaign.stats.bounced,
            "opted_out": campaign.stats.opted_out,
        },
        "created_at": campaign.created_at.isoformat() if campaign.created_at else "",
    }


def _get_repos():
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_campaign_repository import SqlCampaignRepository

    session = SessionLocal()
    repo = SqlCampaignRepository(session)
    return session, repo


@router.post("", response_model=CampaignResponse)
def create_campaign(req: CampaignCreateRequest):
    """Create a new outreach campaign."""
    from src.application.use_cases.create_campaign import CreateCampaign
    from src.application.schemas.campaign_schemas import CampaignCreateDTO, SequenceStepCreateDTO

    session, repo = _get_repos()
    try:
        step_dtos = [
            SequenceStepCreateDTO(**s) for s in req.sequence_steps
        ]
        dto = CampaignCreateDTO(
            name=req.name,
            target_filters=req.target_filters,
            sequence_steps=step_dtos,
            settings_override=req.settings_override,
        )
        campaign = CreateCampaign(repo).execute(dto)
        session.commit()
        return _campaign_to_response(campaign)
    finally:
        session.close()


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(status: Optional[str] = None):
    """List all campaigns."""
    session, repo = _get_repos()
    try:
        filters = {"status": status} if status else None
        campaigns = repo.find_all(filters)
        return [_campaign_to_response(c) for c in campaigns]
    finally:
        session.close()


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: str):
    """Get campaign details."""
    session, repo = _get_repos()
    try:
        campaign = repo.find_by_id(campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return _campaign_to_response(campaign)
    finally:
        session.close()


@router.put("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(campaign_id: str, req: dict):
    """Update campaign status or settings."""
    session, repo = _get_repos()
    try:
        campaign = repo.find_by_id(campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if "name" in req:
            campaign.name = req["name"]
        if "status" in req:
            from src.domain.enums import CampaignStatus
            campaign.status = CampaignStatus(req["status"])
        repo.save(campaign)
        session.commit()
        return _campaign_to_response(campaign)
    finally:
        session.close()


@router.post("/{campaign_id}/activate", response_model=CampaignResponse)
def activate_campaign(campaign_id: str):
    """Activate a campaign (start sending)."""
    session, repo = _get_repos()
    try:
        campaign = repo.find_by_id(campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        from src.domain.enums import CampaignStatus
        campaign.status = CampaignStatus.ACTIVE
        repo.save(campaign)
        session.commit()
        return _campaign_to_response(campaign)
    finally:
        session.close()


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
def pause_campaign(campaign_id: str):
    """Pause a campaign."""
    session, repo = _get_repos()
    try:
        campaign = repo.find_by_id(campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        from src.domain.enums import CampaignStatus
        campaign.status = CampaignStatus.PAUSED
        repo.save(campaign)
        session.commit()
        return _campaign_to_response(campaign)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Message / Draft endpoints
# ---------------------------------------------------------------------------


@router.get("/messages/drafts", response_model=list[dict])
def list_drafts():
    """List all AI-generated draft responses awaiting human review."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository

    session = SessionLocal()
    try:
        repo = SqlMessageRepository(session)
        drafts = repo.find_drafts()
        return [
            {
                "id": d.id,
                "lead_id": d.lead_id,
                "campaign_id": d.campaign_id,
                "channel": d.channel.value if hasattr(d.channel, "value") else d.channel,
                "subject": d.subject,
                "body": d.body,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in drafts
        ]
    finally:
        session.close()


@router.post("/messages/drafts/{message_id}/approve")
def approve_draft(message_id: str, edited_body: Optional[str] = None):
    """Approve (and optionally edit) a draft before sending."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
    from src.domain.enums import MessageStatus

    session = SessionLocal()
    try:
        repo = SqlMessageRepository(session)
        message = repo.find_by_id(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if edited_body:
            message.body = edited_body
        message.status = MessageStatus.QUEUED
        repo.save(message)
        session.commit()
        return {"status": "approved", "message_id": message_id}
    finally:
        session.close()


@router.delete("/messages/drafts/{message_id}")
def discard_draft(message_id: str):
    """Discard a draft response."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
    from src.domain.enums import MessageStatus

    session = SessionLocal()
    try:
        repo = SqlMessageRepository(session)
        message = repo.find_by_id(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        message.status = MessageStatus.DISCARDED
        repo.save(message)
        session.commit()
        return {"status": "discarded", "message_id": message_id}
    finally:
        session.close()
