from typing import Optional
from pydantic import BaseModel, EmailStr


class OptOutRequest(BaseModel):
    email: str
    reason: Optional[str] = "manual"


class DSARExportRequest(BaseModel):
    email: str


class DSARDeleteRequest(BaseModel):
    email: str


class SuppressionCheckRequest(BaseModel):
    email: str


class ComplianceResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
