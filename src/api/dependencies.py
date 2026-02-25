from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from src.infrastructure.config.settings import Settings, get_settings
from src.infrastructure.database.connection import SessionLocal
from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
from src.infrastructure.database.repositories.sql_organization_repository import SqlOrganizationRepository
from src.domain.interfaces.lead_repository import LeadRepository
from src.domain.interfaces.organization_repository import OrganizationRepository


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_lead_repository(db: Session = Depends(get_db)) -> LeadRepository:
    return SqlLeadRepository(db)


def get_organization_repository(db: Session = Depends(get_db)) -> OrganizationRepository:
    return SqlOrganizationRepository(db)


def get_settings_dep() -> Settings:
    return get_settings()
