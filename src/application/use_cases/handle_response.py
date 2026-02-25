"""Use case: process an incoming reply from a prospect."""
import logging

logger = logging.getLogger(__name__)


class HandleResponse:
    """Processes an incoming reply through the SDR agent pipeline."""

    def __init__(self, sdr_agent, message_repo):
        self._sdr = sdr_agent
        self._messages = message_repo

    async def execute(self, message) -> dict:
        """
        Process an incoming message.

        Args:
            message: Message entity (direction=inbound, already saved to DB)

        Returns {action, draft_id, sentiment}.
        """
        return await self._sdr.process_reply(message)

    async def execute_from_raw(
        self,
        lead_id: str,
        body: str,
        channel: str = "email",
        campaign_id: str | None = None,
        subject: str | None = None,
    ) -> dict:
        """
        Create an inbound message record and process it.
        Convenience method for API/CLI use.
        """
        from src.domain.entities.message import Message
        from src.domain.enums import Channel, MessageDirection, MessageStatus
        from datetime import datetime, timezone

        try:
            channel_enum = Channel(channel)
        except ValueError:
            channel_enum = Channel.EMAIL

        msg = Message(
            lead_id=lead_id,
            campaign_id=campaign_id,
            channel=channel_enum,
            direction=MessageDirection.INBOUND,
            subject=subject,
            body=body,
            status=MessageStatus.DELIVERED,
            received_at=datetime.now(timezone.utc),
        )
        self._messages.save(msg)
        return await self.execute(msg)
