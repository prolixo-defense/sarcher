from abc import ABC, abstractmethod

from src.domain.entities.campaign import Campaign


class CampaignRepository(ABC):
    @abstractmethod
    def save(self, campaign: Campaign) -> Campaign:
        ...

    @abstractmethod
    def find_by_id(self, campaign_id: str) -> Campaign | None:
        ...

    @abstractmethod
    def find_all(self, filters: dict | None = None) -> list[Campaign]:
        ...

    @abstractmethod
    def delete(self, campaign_id: str) -> bool:
        ...
