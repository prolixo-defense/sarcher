"""Use case: create an outreach campaign with sequence steps."""
from dataclasses import asdict

from src.domain.entities.campaign import Campaign, CampaignSettings
from src.domain.entities.sequence_step import SequenceStep
from src.domain.enums import CampaignStatus, Channel
from src.application.schemas.campaign_schemas import CampaignCreateDTO


class CreateCampaign:
    """Creates and persists a new outreach campaign."""

    def __init__(self, campaign_repository):
        self._repo = campaign_repository

    def execute(self, dto: CampaignCreateDTO) -> Campaign:
        settings_override = dto.settings_override or {}
        campaign_settings = CampaignSettings(
            daily_email_limit=settings_override.get("daily_email_limit", 50),
            daily_linkedin_limit=settings_override.get("daily_linkedin_limit", 25),
            timezone=settings_override.get("timezone", "America/New_York"),
            business_hours_start=settings_override.get("business_hours_start", 9),
            business_hours_end=settings_override.get("business_hours_end", 18),
        )

        # Build sequence steps as dicts (stored embedded in campaign)
        import uuid
        steps = []
        for step_dto in dto.sequence_steps:
            steps.append({
                "id": str(uuid.uuid4()),
                "campaign_id": "",  # filled after campaign created
                "step_number": step_dto.step_number,
                "channel": step_dto.channel,
                "template_id": step_dto.template_id,
                "delay_days": step_dto.delay_days,
                "condition": step_dto.condition,
                "is_active": step_dto.is_active,
            })

        campaign = Campaign(
            name=dto.name,
            target_filters=dto.target_filters or {},
            sequence_steps=steps,
            settings=campaign_settings,
        )

        # Update campaign_id in steps
        for step in campaign.sequence_steps:
            step["campaign_id"] = campaign.id

        return self._repo.save(campaign)
