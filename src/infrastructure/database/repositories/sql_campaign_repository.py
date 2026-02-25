"""SQLAlchemy repository for Campaign entities."""
import json
import uuid
from datetime import datetime, timezone

from src.domain.entities.campaign import Campaign, CampaignSettings, CampaignStats
from src.domain.entities.sequence_step import SequenceStep
from src.domain.enums import CampaignStatus, Channel
from src.domain.interfaces.campaign_repository import CampaignRepository
from src.infrastructure.database.models import CampaignModel, SequenceStepModel


class SqlCampaignRepository(CampaignRepository):
    """SQLAlchemy-backed campaign repository."""

    def __init__(self, session):
        self._session = session

    def save(self, campaign: Campaign) -> Campaign:
        existing = self._session.query(CampaignModel).filter(
            CampaignModel.id == campaign.id
        ).first()

        settings_dict = {
            "daily_email_limit": campaign.settings.daily_email_limit,
            "daily_linkedin_limit": campaign.settings.daily_linkedin_limit,
            "timezone": campaign.settings.timezone,
            "business_hours_start": campaign.settings.business_hours_start,
            "business_hours_end": campaign.settings.business_hours_end,
            "business_days": campaign.settings.business_days,
        }
        stats_dict = {
            "sent": campaign.stats.sent,
            "opened": campaign.stats.opened,
            "replied": campaign.stats.replied,
            "bounced": campaign.stats.bounced,
            "opted_out": campaign.stats.opted_out,
        }

        if existing:
            existing.name = campaign.name
            existing.status = campaign.status.value if hasattr(campaign.status, "value") else campaign.status
            existing.target_filters = campaign.target_filters
            existing.settings = settings_dict
            existing.stats = stats_dict
            existing.updated_at = datetime.now(timezone.utc)
        else:
            model = CampaignModel(
                id=campaign.id,
                name=campaign.name,
                status=campaign.status.value if hasattr(campaign.status, "value") else campaign.status,
                target_filters=campaign.target_filters,
                settings=settings_dict,
                stats=stats_dict,
            )
            self._session.add(model)

        # Upsert sequence steps
        self._session.query(SequenceStepModel).filter(
            SequenceStepModel.campaign_id == campaign.id
        ).delete()
        for step in campaign.sequence_steps:
            step_model = SequenceStepModel(
                id=step.get("id") if isinstance(step, dict) else step.id,
                campaign_id=campaign.id,
                step_number=step.get("step_number") if isinstance(step, dict) else step.step_number,
                channel=step.get("channel") if isinstance(step, dict) else (step.channel.value if hasattr(step.channel, "value") else step.channel),
                template_id=step.get("template_id") if isinstance(step, dict) else step.template_id,
                delay_days=step.get("delay_days", 1) if isinstance(step, dict) else step.delay_days,
                condition=step.get("condition") if isinstance(step, dict) else step.condition,
                is_active=step.get("is_active", True) if isinstance(step, dict) else step.is_active,
            )
            self._session.add(step_model)

        self._session.flush()
        return campaign

    def find_by_id(self, campaign_id: str) -> Campaign | None:
        model = self._session.query(CampaignModel).filter(
            CampaignModel.id == campaign_id
        ).first()
        if model is None:
            return None
        return self._to_entity(model)

    def find_all(self, filters: dict | None = None) -> list[Campaign]:
        query = self._session.query(CampaignModel)
        if filters:
            status = filters.get("status")
            if status:
                query = query.filter(CampaignModel.status == status)
        models = query.order_by(CampaignModel.created_at.desc()).all()
        return [self._to_entity(m) for m in models]

    def delete(self, campaign_id: str) -> bool:
        model = self._session.query(CampaignModel).filter(
            CampaignModel.id == campaign_id
        ).first()
        if model is None:
            return False
        self._session.query(SequenceStepModel).filter(
            SequenceStepModel.campaign_id == campaign_id
        ).delete()
        self._session.delete(model)
        self._session.flush()
        return True

    def _to_entity(self, model: CampaignModel) -> Campaign:
        settings_data = model.settings or {}
        stats_data = model.stats or {}

        settings = CampaignSettings(
            daily_email_limit=settings_data.get("daily_email_limit", 50),
            daily_linkedin_limit=settings_data.get("daily_linkedin_limit", 25),
            timezone=settings_data.get("timezone", "America/New_York"),
            business_hours_start=settings_data.get("business_hours_start", 9),
            business_hours_end=settings_data.get("business_hours_end", 18),
            business_days=settings_data.get("business_days", ["mon", "tue", "wed", "thu", "fri"]),
        )
        stats = CampaignStats(
            sent=stats_data.get("sent", 0),
            opened=stats_data.get("opened", 0),
            replied=stats_data.get("replied", 0),
            bounced=stats_data.get("bounced", 0),
            opted_out=stats_data.get("opted_out", 0),
        )

        # Load sequence steps
        step_models = self._session.query(SequenceStepModel).filter(
            SequenceStepModel.campaign_id == model.id
        ).order_by(SequenceStepModel.step_number).all()
        steps = [
            {
                "id": s.id,
                "campaign_id": s.campaign_id,
                "step_number": s.step_number,
                "channel": s.channel,
                "template_id": s.template_id,
                "delay_days": s.delay_days,
                "condition": s.condition,
                "is_active": s.is_active,
            }
            for s in step_models
        ]

        return Campaign(
            id=model.id,
            name=model.name,
            status=CampaignStatus(model.status),
            target_filters=model.target_filters or {},
            sequence_steps=steps,
            settings=settings,
            stats=stats,
            created_at=model.created_at or datetime.now(timezone.utc),
            updated_at=model.updated_at or datetime.now(timezone.utc),
        )
