"""
EnrichLead use case.

Phase 1: synchronous execute() using the legacy EnrichmentAdapter interface.
Phase 3: async execute_async() using the EnrichmentPipeline (Apollo → Hunter waterfall).

Both paths are preserved for backward compatibility.
"""
from datetime import datetime, timezone

from src.domain.entities.lead import Lead
from src.domain.enums import EnrichmentStatus
from src.domain.interfaces.enrichment_adapter import EnrichmentAdapter
from src.domain.interfaces.lead_repository import LeadRepository


class EnrichLead:
    """Use case: enrich a lead with data from external APIs."""

    def __init__(
        self,
        lead_repository: LeadRepository,
        enrichment_adapter: EnrichmentAdapter | None = None,
        enrichment_pipeline=None,  # EnrichmentPipeline (async, Phase 3)
    ) -> None:
        self._repo = lead_repository
        self._adapter = enrichment_adapter
        self._pipeline = enrichment_pipeline

    # ------------------------------------------------------------------
    # Synchronous path (Phase 1 / placeholder)
    # ------------------------------------------------------------------

    def execute(self, lead_id: str) -> Lead:
        """Synchronous enrichment using the legacy EnrichmentAdapter."""
        lead = self._repo.find_by_id(lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id!r} not found.")

        if lead.enrichment_status == EnrichmentStatus.COMPLETED:
            return lead

        if self._adapter is None:
            # No adapter configured — mark as skipped
            lead.enrichment_status = EnrichmentStatus.SKIPPED
            lead.updated_at = datetime.now(timezone.utc)
            return self._repo.save(lead)

        lead.enrichment_status = EnrichmentStatus.IN_PROGRESS
        lead.updated_at = datetime.now(timezone.utc)
        self._repo.save(lead)

        try:
            enriched = self._adapter.enrich(lead)
            enriched.enrichment_status = EnrichmentStatus.COMPLETED
            enriched.updated_at = datetime.now(timezone.utc)
            return self._repo.save(enriched)
        except Exception:
            lead.enrichment_status = EnrichmentStatus.FAILED
            lead.updated_at = datetime.now(timezone.utc)
            self._repo.save(lead)
            raise

    # ------------------------------------------------------------------
    # Async path (Phase 3 — EnrichmentPipeline)
    # ------------------------------------------------------------------

    async def execute_async(self, lead_id: str) -> Lead:
        """
        Async enrichment using EnrichmentPipeline (Apollo → Hunter waterfall).

        Falls back to the synchronous execute() path if no pipeline is
        configured (e.g., during tests or when API keys are not set).
        """
        lead = self._repo.find_by_id(lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id!r} not found.")

        if lead.enrichment_status == EnrichmentStatus.COMPLETED:
            return lead

        if self._pipeline is None:
            # No async pipeline — use sync path
            return self.execute(lead_id)

        lead.enrichment_status = EnrichmentStatus.IN_PROGRESS
        lead.updated_at = datetime.now(timezone.utc)
        self._repo.save(lead)

        try:
            enriched = await self._pipeline.enrich(lead)
            enriched.enrichment_status = EnrichmentStatus.COMPLETED
            enriched.updated_at = datetime.now(timezone.utc)
            return self._repo.save(enriched)
        except Exception:
            lead.enrichment_status = EnrichmentStatus.FAILED
            lead.updated_at = datetime.now(timezone.utc)
            self._repo.save(lead)
            raise
