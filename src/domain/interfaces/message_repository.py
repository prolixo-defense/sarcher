from abc import ABC, abstractmethod

from src.domain.entities.message import Message


class MessageRepository(ABC):
    @abstractmethod
    def save(self, message: Message) -> Message:
        ...

    @abstractmethod
    def find_by_id(self, message_id: str) -> Message | None:
        ...

    @abstractmethod
    def find_by_lead(self, lead_id: str) -> list[Message]:
        ...

    @abstractmethod
    def find_by_campaign(self, campaign_id: str) -> list[Message]:
        ...

    @abstractmethod
    def find_drafts(self) -> list[Message]:
        ...
