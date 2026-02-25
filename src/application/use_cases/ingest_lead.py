from datetime import datetime, timedelta, timezone

from src.application.dtos.lead_dto import LeadCreateDTO
from src.application.services.deduplication import DeduplicationService
from src.domain.entities.lead import Lead
from src.domain.interfaces.lead_repository import LeadRepository
from src.infrastructure.config.settings import get_settings


class IngestLead:
    """Use case: Create or upsert a lead from raw data."""

    def __init__(
        self,
        lead_repository: LeadRepository,
        dedup_service: DeduplicationService,
    ) -> None:
        self._repo = lead_repository
        self._dedup = dedup_service

    def execute(self, dto: LeadCreateDTO) -> Lead:
        settings = get_settings()
        retention_days = settings.default_retention_days
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=retention_days)

        lead = Lead(
            first_name=dto.first_name,
            last_name=dto.last_name,
            email=dto.email.lower().strip() if dto.email else None,
            phone=dto.phone,
            job_title=dto.job_title,
            company_name=dto.company_name,
            company_domain=dto.company_domain,
            linkedin_url=dto.linkedin_url,
            location=dto.location,
            source=dto.source,
            confidence_score=dto.confidence_score,
            raw_data=dto.raw_data,
            tags=dto.tags,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        lead.validate()

        # Check for duplicates
        result = self._dedup.find_duplicate(lead)
        if result.is_duplicate and result.matched_lead:
            merged = self._dedup.merge(result.matched_lead, lead)
            return self._repo.save(merged)

        return self._repo.upsert(lead)
