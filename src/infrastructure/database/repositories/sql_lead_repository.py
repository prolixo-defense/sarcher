from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, EnrichmentStatus, LeadStatus
from src.domain.interfaces.lead_repository import LeadRepository
from src.infrastructure.database.models import LeadModel


def _model_to_entity(m: LeadModel) -> Lead:
    return Lead(
        id=m.id,
        first_name=m.first_name,
        last_name=m.last_name,
        email=m.email,
        phone=m.phone,
        job_title=m.job_title,
        company_name=m.company_name,
        company_domain=m.company_domain,
        linkedin_url=m.linkedin_url,
        location=m.location,
        status=LeadStatus(m.status),
        source=DataSource(m.source),
        enrichment_status=EnrichmentStatus(m.enrichment_status),
        confidence_score=m.confidence_score,
        raw_data=m.raw_data,
        tags=list(m.tags or []),
        created_at=m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=timezone.utc),
        updated_at=m.updated_at if m.updated_at.tzinfo else m.updated_at.replace(tzinfo=timezone.utc),
        expires_at=(
            m.expires_at.replace(tzinfo=timezone.utc)
            if m.expires_at and not m.expires_at.tzinfo
            else m.expires_at
        ),
    )


def _entity_to_model(lead: Lead) -> dict:
    return {
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
        "raw_data": lead.raw_data,
        "tags": lead.tags,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "expires_at": lead.expires_at,
    }


class SqlLeadRepository(LeadRepository):

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, lead: Lead) -> Lead:
        existing = self._session.get(LeadModel, lead.id)
        data = _entity_to_model(lead)
        if existing:
            for key, value in data.items():
                setattr(existing, key, value)
        else:
            self._session.add(LeadModel(**data))
        self._session.flush()
        return lead

    def find_by_id(self, id: str) -> Lead | None:
        m = self._session.get(LeadModel, id)
        return _model_to_entity(m) if m else None

    def find_by_email(self, email: str) -> Lead | None:
        m = self._session.query(LeadModel).filter(
            LeadModel.email == email.lower()
        ).first()
        return _model_to_entity(m) if m else None

    def find_by_domain(self, domain: str) -> list[Lead]:
        rows = self._session.query(LeadModel).filter(
            LeadModel.company_domain == domain
        ).all()
        return [_model_to_entity(r) for r in rows]

    def search(self, filters: dict, limit: int = 50, offset: int = 0) -> list[Lead]:
        q = self._session.query(LeadModel)
        q = _apply_filters(q, filters)
        rows = q.order_by(LeadModel.created_at.desc()).limit(limit).offset(offset).all()
        return [_model_to_entity(r) for r in rows]

    def count(self, filters: dict) -> int:
        q = self._session.query(func.count(LeadModel.id))
        q = _apply_filters(q, filters)
        return q.scalar() or 0

    def delete(self, id: str) -> bool:
        m = self._session.get(LeadModel, id)
        if m:
            self._session.delete(m)
            self._session.flush()
            return True
        return False

    def delete_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = self._session.query(LeadModel).filter(
            LeadModel.expires_at != None,
            LeadModel.expires_at < now,
        ).delete(synchronize_session=False)
        self._session.flush()
        return result

    def upsert(self, lead: Lead) -> Lead:
        existing = None
        if lead.email:
            existing = self._session.query(LeadModel).filter(
                LeadModel.email == lead.email.lower()
            ).first()
        if not existing and lead.company_domain:
            existing = self._session.query(LeadModel).filter(
                LeadModel.company_domain == lead.company_domain,
                LeadModel.first_name == lead.first_name,
                LeadModel.last_name == lead.last_name,
            ).first()
        if existing:
            lead.id = existing.id
            # Keep higher confidence values
            if lead.confidence_score < existing.confidence_score:
                lead.confidence_score = existing.confidence_score
        return self.save(lead)


def _apply_filters(q, filters: dict):
    if filters.get("status"):
        q = q.filter(LeadModel.status == filters["status"])
    if filters.get("source"):
        q = q.filter(LeadModel.source == filters["source"])
    if filters.get("enrichment_status"):
        q = q.filter(LeadModel.enrichment_status == filters["enrichment_status"])
    if filters.get("company_domain"):
        q = q.filter(LeadModel.company_domain == filters["company_domain"])
    if filters.get("keyword"):
        kw = f"%{filters['keyword']}%"
        q = q.filter(or_(
            LeadModel.first_name.ilike(kw),
            LeadModel.last_name.ilike(kw),
            LeadModel.email.ilike(kw),
            LeadModel.company_name.ilike(kw),
            LeadModel.job_title.ilike(kw),
        ))
    if filters.get("created_after"):
        q = q.filter(LeadModel.created_at >= filters["created_after"])
    if filters.get("created_before"):
        q = q.filter(LeadModel.created_at <= filters["created_before"])
    return q
