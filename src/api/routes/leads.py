from fastapi import APIRouter, Depends, HTTPException, Response, Query
from typing import Optional
from datetime import datetime

from src.api.dependencies import get_lead_repository
from src.application.dtos.lead_dto import (
    LeadCreateDTO, LeadResponseDTO, LeadSearchDTO, LeadUpdateDTO, LeadExportDTO,
)
from src.application.services.deduplication import DeduplicationService
from src.application.use_cases.enrich_lead import EnrichLead
from src.application.use_cases.export_leads import ExportLeads
from src.application.use_cases.ingest_lead import IngestLead
from src.application.use_cases.search_leads import SearchLeads
from src.domain.enums import DataSource, EnrichmentStatus, LeadStatus
from src.domain.interfaces.lead_repository import LeadRepository

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.post("", response_model=LeadResponseDTO, status_code=201)
def create_lead(dto: LeadCreateDTO, repo: LeadRepository = Depends(get_lead_repository)):
    dedup = DeduplicationService(repo)
    use_case = IngestLead(repo, dedup)
    lead = use_case.execute(dto)
    return LeadResponseDTO.model_validate(lead.__dict__)


@router.get("", response_model=dict)
def list_leads(
    status: Optional[LeadStatus] = Query(None),
    source: Optional[DataSource] = Query(None),
    enrichment_status: Optional[EnrichmentStatus] = Query(None),
    keyword: Optional[str] = Query(None),
    company_domain: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: LeadRepository = Depends(get_lead_repository),
):
    search_dto = LeadSearchDTO(
        status=status,
        source=source,
        enrichment_status=enrichment_status,
        keyword=keyword,
        company_domain=company_domain,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    use_case = SearchLeads(repo)
    leads, total = use_case.execute(search_dto)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [LeadResponseDTO.model_validate(l.__dict__) for l in leads],
    }


@router.get("/{lead_id}", response_model=LeadResponseDTO)
def get_lead(lead_id: str, repo: LeadRepository = Depends(get_lead_repository)):
    lead = repo.find_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadResponseDTO.model_validate(lead.__dict__)


@router.put("/{lead_id}", response_model=LeadResponseDTO)
def update_lead(
    lead_id: str,
    dto: LeadUpdateDTO,
    repo: LeadRepository = Depends(get_lead_repository),
):
    from datetime import timezone
    lead = repo.find_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_data = dto.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(lead, key, value)
    lead.updated_at = datetime.now(timezone.utc)
    repo.save(lead)
    return LeadResponseDTO.model_validate(lead.__dict__)


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: str, repo: LeadRepository = Depends(get_lead_repository)):
    deleted = repo.delete(lead_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Response(status_code=204)


@router.post("/export", response_class=Response)
def export_leads(dto: LeadExportDTO, repo: LeadRepository = Depends(get_lead_repository)):
    use_case = ExportLeads(repo)
    data = use_case.execute(dto)
    media_type = "application/json" if dto.format == "json" else "text/csv"
    filename = f"leads.{dto.format}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{lead_id}/enrich", response_model=LeadResponseDTO)
def enrich_lead(lead_id: str, repo: LeadRepository = Depends(get_lead_repository)):
    use_case = EnrichLead(repo)
    lead = use_case.execute(lead_id)
    return LeadResponseDTO.model_validate(lead.__dict__)
