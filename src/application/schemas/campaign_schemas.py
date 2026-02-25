from typing import Any, Optional
from pydantic import BaseModel, Field


class SequenceStepCreateDTO(BaseModel):
    step_number: int
    channel: str  # email, linkedin_connect, linkedin_message, linkedin_inmail
    template_id: str
    delay_days: int = 1
    condition: Optional[str] = None  # "no_reply", etc.
    is_active: bool = True


class CampaignCreateDTO(BaseModel):
    name: str
    target_filters: dict[str, Any] = Field(default_factory=dict)
    sequence_steps: list[SequenceStepCreateDTO] = Field(default_factory=list)
    settings_override: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdateDTO(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    target_filters: Optional[dict[str, Any]] = None
    settings_override: Optional[dict[str, Any]] = None


class MessageCreateDTO(BaseModel):
    lead_id: str
    campaign_id: Optional[str] = None
    channel: str
    direction: str = "outbound"
    subject: Optional[str] = None
    body: str
    status: str = "queued"


class DraftApproveDTO(BaseModel):
    message_id: str
    edited_body: Optional[str] = None  # If None, send the existing draft_response unchanged


class CampaignResponseDTO(BaseModel):
    id: str
    name: str
    status: str
    stats: dict[str, int]
    step_count: int
    created_at: str
