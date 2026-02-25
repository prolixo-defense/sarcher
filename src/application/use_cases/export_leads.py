import csv
import io
import json
from dataclasses import asdict

from src.application.dtos.lead_dto import LeadExportDTO
from src.application.use_cases.search_leads import SearchLeads
from src.domain.interfaces.lead_repository import LeadRepository


class ExportLeads:
    """Use case: Export leads to CSV or JSON."""

    def __init__(self, lead_repository: LeadRepository) -> None:
        self._repo = lead_repository
        self._search = SearchLeads(lead_repository)

    def execute(self, dto: LeadExportDTO) -> bytes:
        # Fetch all matching leads (no pagination limit for export)
        from src.application.dtos.lead_dto import LeadSearchDTO
        search_dto = LeadSearchDTO(
            status=dto.filters.status,
            source=dto.filters.source,
            enrichment_status=dto.filters.enrichment_status,
            keyword=dto.filters.keyword,
            company_domain=dto.filters.company_domain,
            created_after=dto.filters.created_after,
            created_before=dto.filters.created_before,
            limit=500,
            offset=0,
        )
        leads, _ = self._search.execute(search_dto)

        if dto.format == "json":
            data = []
            for lead in leads:
                d = {
                    "id": lead.id,
                    "first_name": lead.first_name,
                    "last_name": lead.last_name,
                    "email": lead.email,
                    "phone": lead.phone,
                    "job_title": lead.job_title,
                    "company_name": lead.company_name,
                    "company_domain": lead.company_domain,
                    "linkedin_url": lead.linkedin_url,
                    "location": lead.location,
                    "status": lead.status.value,
                    "source": lead.source.value,
                    "enrichment_status": lead.enrichment_status.value,
                    "confidence_score": lead.confidence_score,
                    "tags": lead.tags,
                    "created_at": lead.created_at.isoformat(),
                    "updated_at": lead.updated_at.isoformat(),
                    "expires_at": lead.expires_at.isoformat() if lead.expires_at else None,
                }
                data.append(d)
            return json.dumps(data, indent=2).encode("utf-8")

        # CSV
        output = io.StringIO()
        fieldnames = [
            "id", "first_name", "last_name", "email", "phone", "job_title",
            "company_name", "company_domain", "linkedin_url", "location",
            "status", "source", "enrichment_status", "confidence_score",
            "tags", "created_at", "updated_at", "expires_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                "id": lead.id,
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "email": lead.email or "",
                "phone": lead.phone or "",
                "job_title": lead.job_title or "",
                "company_name": lead.company_name or "",
                "company_domain": lead.company_domain or "",
                "linkedin_url": lead.linkedin_url or "",
                "location": lead.location or "",
                "status": lead.status.value,
                "source": lead.source.value,
                "enrichment_status": lead.enrichment_status.value,
                "confidence_score": lead.confidence_score,
                "tags": ",".join(lead.tags),
                "created_at": lead.created_at.isoformat(),
                "updated_at": lead.updated_at.isoformat(),
                "expires_at": lead.expires_at.isoformat() if lead.expires_at else "",
            })
        return output.getvalue().encode("utf-8")
