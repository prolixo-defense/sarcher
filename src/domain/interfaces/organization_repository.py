from abc import ABC, abstractmethod

from src.domain.entities.organization import Organization


class OrganizationRepository(ABC):

    @abstractmethod
    def save(self, org: Organization) -> Organization:
        ...

    @abstractmethod
    def find_by_id(self, id: str) -> Organization | None:
        ...

    @abstractmethod
    def find_by_domain(self, domain: str) -> Organization | None:
        ...

    @abstractmethod
    def find_by_name(self, name: str) -> list[Organization]:
        ...

    @abstractmethod
    def search(self, filters: dict, limit: int, offset: int) -> list[Organization]:
        ...

    @abstractmethod
    def count(self, filters: dict) -> int:
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        ...

    @abstractmethod
    def find_by_cage_code(self, cage_code: str) -> Organization | None:
        ...

    @abstractmethod
    def upsert(self, org: Organization) -> Organization:
        """Insert or update based on domain match."""
        ...
