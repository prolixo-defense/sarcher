"""
Tests for SequenceManager — step progression, delay logic, conditions.

All repos and email_sender are mocked.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.campaign import Campaign, CampaignSettings, CampaignStats
from src.domain.entities.message import Message
from src.domain.enums import CampaignStatus, Channel, MessageDirection, MessageStatus
from src.infrastructure.outreach.sequence_manager import SequenceManager


def _make_campaign(steps: list[dict], status: str = "active") -> Campaign:
    return Campaign(
        name="Test Campaign",
        status=CampaignStatus(status),
        sequence_steps=steps,
    )


def _make_message(lead_id: str, campaign_id: str, direction: str = "outbound", sent_at=None) -> Message:
    msg = Message(
        lead_id=lead_id,
        campaign_id=campaign_id,
        channel=Channel.EMAIL,
        direction=MessageDirection(direction),
        body="Test",
    )
    if sent_at:
        msg.sent_at = sent_at
        msg.status = MessageStatus.SENT
    return msg


def _make_repos(campaign, messages):
    campaign_repo = MagicMock()
    campaign_repo.find_by_id = MagicMock(return_value=campaign)

    msg_repo = MagicMock()
    msg_repo.find_by_lead = MagicMock(return_value=messages)
    msg_repo.save = MagicMock(side_effect=lambda m: m)

    return campaign_repo, msg_repo


@pytest.mark.asyncio
async def test_get_next_action_returns_first_step_for_new_lead():
    steps = [{"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": True}]
    campaign = _make_campaign(steps)
    campaign_repo, msg_repo = _make_repos(campaign, [])  # No messages sent yet

    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    step = await manager.get_next_action(campaign.id, "lead-1")
    assert step is not None
    assert step["step_number"] == 1


@pytest.mark.asyncio
async def test_get_next_action_returns_none_when_all_steps_sent():
    steps = [{"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": True}]
    campaign = _make_campaign(steps)

    msg = _make_message("lead-1", campaign.id, sent_at=datetime.now(timezone.utc))
    msg.__dict__["step_number"] = 1

    campaign_repo, msg_repo = _make_repos(campaign, [msg])
    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    step = await manager.get_next_action(campaign.id, "lead-1")
    assert step is None


@pytest.mark.asyncio
async def test_get_next_action_respects_delay():
    now = datetime.now(timezone.utc)
    steps = [
        {"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": True},
        {"id": "s2", "step_number": 2, "channel": "email", "template_id": "fu1", "delay_days": 5, "condition": None, "is_active": True},
    ]
    campaign = _make_campaign(steps)

    # Step 1 sent 1 day ago — not enough delay for step 2 (needs 5 days)
    msg = _make_message("lead-1", campaign.id, sent_at=now - timedelta(days=1))
    msg.__dict__["step_number"] = 1

    campaign_repo, msg_repo = _make_repos(campaign, [msg])
    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    step = await manager.get_next_action(campaign.id, "lead-1")
    assert step is None  # Too early for step 2


@pytest.mark.asyncio
async def test_get_next_action_skips_step_when_replied_and_condition_no_reply():
    now = datetime.now(timezone.utc)
    steps = [
        {"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": True},
        {"id": "s2", "step_number": 2, "channel": "email", "template_id": "fu1", "delay_days": 3, "condition": "no_reply", "is_active": True},
    ]
    campaign = _make_campaign(steps)

    # Step 1 sent, and a reply was received
    sent_msg = _make_message("lead-1", campaign.id, "outbound", sent_at=now - timedelta(days=4))
    sent_msg.__dict__["step_number"] = 1
    reply_msg = _make_message("lead-1", campaign.id, "inbound")

    campaign_repo, msg_repo = _make_repos(campaign, [sent_msg, reply_msg])
    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    step = await manager.get_next_action(campaign.id, "lead-1")
    assert step is None  # Condition "no_reply" not met


@pytest.mark.asyncio
async def test_get_next_action_returns_none_when_campaign_not_active():
    steps = [{"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": True}]
    campaign = _make_campaign(steps, status="paused")

    campaign_repo = MagicMock()
    campaign_repo.find_by_id = MagicMock(return_value=campaign)
    msg_repo = MagicMock()
    msg_repo.find_by_lead = MagicMock(return_value=[])

    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    # process_campaign should skip paused campaigns
    result = await manager.process_campaign(campaign.id)
    assert result["processed"] == 0


@pytest.mark.asyncio
async def test_get_next_action_returns_none_when_step_inactive():
    steps = [{"id": "s1", "step_number": 1, "channel": "email", "template_id": "init", "delay_days": 0, "condition": None, "is_active": False}]
    campaign = _make_campaign(steps)
    campaign_repo, msg_repo = _make_repos(campaign, [])

    manager = SequenceManager(campaign_repo, msg_repo, AsyncMock())
    step = await manager.get_next_action(campaign.id, "lead-1")
    assert step is None
