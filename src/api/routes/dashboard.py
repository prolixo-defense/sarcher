from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def dashboard_stats():
    """Overall stats: leads, campaigns, messages, credit usage."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.models import (
        LeadModel, CampaignModel, MessageModel, SuppressionListModel
    )
    import asyncio
    from src.infrastructure.enrichment.credit_manager import CreditManager

    session = SessionLocal()
    try:
        lead_count = session.query(LeadModel).count()
        campaign_count = session.query(CampaignModel).count()
        active_campaigns = session.query(CampaignModel).filter(CampaignModel.status == "active").count()
        message_count = session.query(MessageModel).count()
        draft_count = session.query(MessageModel).filter(MessageModel.status == "draft").count()
        sent_count = session.query(MessageModel).filter(MessageModel.status == "sent").count()
        suppression_count = session.query(SuppressionListModel).count()

        credit_mgr = CreditManager(session)
        credits = asyncio.run(credit_mgr.get_usage_summary())

        return {
            "leads": {
                "total": lead_count,
            },
            "campaigns": {
                "total": campaign_count,
                "active": active_campaigns,
            },
            "messages": {
                "total": message_count,
                "sent": sent_count,
                "drafts_pending_review": draft_count,
            },
            "suppression": {
                "total": suppression_count,
            },
            "credits": credits,
        }
    finally:
        session.close()


@router.get("/pipeline")
def pipeline_funnel():
    """Pipeline funnel data for visualization."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.models import LeadModel

    session = SessionLocal()
    try:
        stages = {}
        for status in ["raw", "enriched", "verified", "contacted", "responded", "qualified", "opted_out"]:
            stages[status] = session.query(LeadModel).filter(LeadModel.status == status).count()
        return {"funnel": stages}
    finally:
        session.close()
