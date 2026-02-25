from abc import ABC, abstractmethod

from src.domain.entities.lead import Lead


class EnrichmentAdapter(ABC):
    """Placeholder interface for Phase 3 enrichment implementations."""

    @abstractmethod
    def enrich(self, lead: Lead) -> Lead:
        """Enrich a lead with additional data and return the updated lead."""
        ...
