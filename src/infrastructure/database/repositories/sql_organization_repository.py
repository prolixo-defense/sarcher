from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

from src.domain.entities.organization import Organization
from src.domain.enums import DataSource
from src.domain.interfaces.organization_repository import OrganizationRepository
from src.infrastructure.database.models import OrganizationModel


def _model_to_entity(m: OrganizationModel) -> Organization:
    return Organization(
        id=m.id,
        name=m.name,
        domain=m.domain,
        industry=m.industry,
        employee_count=m.employee_count,
        annual_revenue=m.annual_revenue,
        location=m.location,
        description=m.description,
        technologies=list(m.technologies or []),
        source=DataSource(m.source),
        raw_data=m.raw_data,
        cage_code=m.cage_code,
        uei=m.uei,
        naics_codes=list(m.naics_codes or []),
        size_band=m.size_band,
        segment=m.segment,
        created_at=m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=timezone.utc),
        updated_at=m.updated_at if m.updated_at.tzinfo else m.updated_at.replace(tzinfo=timezone.utc),
    )


class SqlOrganizationRepository(OrganizationRepository):

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, org: Organization) -> Organization:
        existing = self._session.get(OrganizationModel, org.id)
        data = {
            "id": org.id, "name": org.name, "domain": org.domain,
            "industry": org.industry, "employee_count": org.employee_count,
            "annual_revenue": org.annual_revenue, "location": org.location,
            "description": org.description, "technologies": org.technologies,
            "source": org.source.value, "raw_data": org.raw_data,
            "cage_code": org.cage_code, "uei": org.uei,
            "naics_codes": org.naics_codes, "size_band": org.size_band,
            "segment": org.segment,
            "created_at": org.created_at, "updated_at": org.updated_at,
        }
        if existing:
            for key, value in data.items():
                setattr(existing, key, value)
        else:
            self._session.add(OrganizationModel(**data))
        self._session.flush()
        return org

    def find_by_id(self, id: str) -> Organization | None:
        m = self._session.get(OrganizationModel, id)
        return _model_to_entity(m) if m else None

    def find_by_domain(self, domain: str) -> Organization | None:
        m = self._session.query(OrganizationModel).filter(
            OrganizationModel.domain == domain
        ).first()
        return _model_to_entity(m) if m else None

    def find_by_name(self, name: str) -> list[Organization]:
        rows = self._session.query(OrganizationModel).filter(
            OrganizationModel.name.ilike(f"%{name}%")
        ).all()
        return [_model_to_entity(r) for r in rows]

    def search(self, filters: dict, limit: int = 50, offset: int = 0) -> list[Organization]:
        q = self._session.query(OrganizationModel)
        if filters.get("keyword"):
            kw = f"%{filters['keyword']}%"
            q = q.filter(OrganizationModel.name.ilike(kw))
        if filters.get("industry"):
            q = q.filter(OrganizationModel.industry == filters["industry"])
        rows = q.order_by(OrganizationModel.name).limit(limit).offset(offset).all()
        return [_model_to_entity(r) for r in rows]

    def count(self, filters: dict) -> int:
        q = self._session.query(func.count(OrganizationModel.id))
        return q.scalar() or 0

    def delete(self, id: str) -> bool:
        m = self._session.get(OrganizationModel, id)
        if m:
            self._session.delete(m)
            self._session.flush()
            return True
        return False

    def find_by_cage_code(self, cage_code: str) -> Organization | None:
        m = self._session.query(OrganizationModel).filter(
            OrganizationModel.cage_code == cage_code
        ).first()
        return _model_to_entity(m) if m else None

    def upsert(self, org: Organization) -> Organization:
        if org.domain:
            existing = self.find_by_domain(org.domain)
            if existing:
                org.id = existing.id
        return self.save(org)
