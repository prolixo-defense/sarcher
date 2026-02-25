from abc import ABC, abstractmethod

from src.domain.entities.lead import Lead


class LeadRepository(ABC):

    @abstractmethod
    def save(self, lead: Lead) -> Lead:
        ...

    @abstractmethod
    def find_by_id(self, id: str) -> Lead | None:
        ...

    @abstractmethod
    def find_by_email(self, email: str) -> Lead | None:
        ...

    @abstractmethod
    def find_by_domain(self, domain: str) -> list[Lead]:
        ...

    @abstractmethod
    def search(self, filters: dict, limit: int, offset: int) -> list[Lead]:
        ...

    @abstractmethod
    def count(self, filters: dict) -> int:
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        ...

    @abstractmethod
    def delete_expired(self) -> int:
        """Delete all leads whose expires_at is in the past. Returns count deleted."""
        ...

    @abstractmethod
    def upsert(self, lead: Lead) -> Lead:
        """Insert or update based on email + company_domain match."""
        ...
