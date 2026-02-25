from src.application.dtos.lead_dto import LeadSearchDTO
from src.domain.entities.lead import Lead
from src.domain.interfaces.lead_repository import LeadRepository


class SearchLeads:
    """Use case: Query leads with filters and pagination."""

    def __init__(self, lead_repository: LeadRepository) -> None:
        self._repo = lead_repository

    def execute(self, dto: LeadSearchDTO) -> tuple[list[Lead], int]:
        filters: dict = {}
        if dto.status:
            filters["status"] = dto.status.value
        if dto.source:
            filters["source"] = dto.source.value
        if dto.enrichment_status:
            filters["enrichment_status"] = dto.enrichment_status.value
        if dto.keyword:
            filters["keyword"] = dto.keyword
        if dto.company_domain:
            filters["company_domain"] = dto.company_domain
        if dto.created_after:
            filters["created_after"] = dto.created_after
        if dto.created_before:
            filters["created_before"] = dto.created_before

        leads = self._repo.search(filters, limit=dto.limit, offset=dto.offset)
        total = self._repo.count(filters)
        return leads, total
