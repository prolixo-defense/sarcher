from abc import ABC, abstractmethod


class OutreachAdapter(ABC):
    """Abstract interface for outreach channels (email, LinkedIn, etc.)."""

    @abstractmethod
    async def send(self, to: str, subject: str | None, body: str, **kwargs) -> dict:
        """Send a message. Returns {success: bool, message_id: str | None, error: str | None}."""
        ...
