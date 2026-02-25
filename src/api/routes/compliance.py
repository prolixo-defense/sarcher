from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class OptOutRequest(BaseModel):
    email: str
    reason: Optional[str] = "manual"


class DSARRequest(BaseModel):
    email: str


def _get_gdpr():
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.compliance.gdpr_manager import GDPRManager

    session = SessionLocal()
    return session, GDPRManager(session)


@router.post("/opt-out")
async def opt_out(req: OptOutRequest):
    """Manually add an email to the suppression list."""
    session, gdpr = _get_gdpr()
    try:
        await gdpr.add_to_suppression(req.email, reason=req.reason or "manual", source="api")
        session.commit()
        return {"success": True, "email": req.email, "message": "Added to suppression list"}
    finally:
        session.close()


@router.post("/dsar/export")
async def dsar_export(req: DSARRequest):
    """Export all data held for an email address (GDPR Article 15)."""
    session, gdpr = _get_gdpr()
    try:
        result = await gdpr.handle_dsar_export(req.email)
        session.commit()
        return result
    finally:
        session.close()


@router.post("/dsar/delete")
async def dsar_delete(req: DSARRequest):
    """Delete all data for an email address (GDPR Article 17)."""
    session, gdpr = _get_gdpr()
    try:
        result = await gdpr.handle_dsar_delete(req.email)
        session.commit()
        return result
    finally:
        session.close()


@router.get("/suppression")
def list_suppression(limit: int = 100):
    """View the suppression list."""
    session, gdpr = _get_gdpr()
    try:
        return {"suppression_list": gdpr.get_suppression_list(limit=limit)}
    finally:
        session.close()


@router.get("/suppression/check")
async def check_suppression(email: str):
    """Check if an email is on the suppression list."""
    session, gdpr = _get_gdpr()
    try:
        is_suppressed = await gdpr.check_suppression(email)
        return {"email": email, "suppressed": is_suppressed}
    finally:
        session.close()
