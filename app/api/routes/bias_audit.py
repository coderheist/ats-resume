from __future__ import annotations

from fastapi import APIRouter

from app.core.bias_audit.jd_bias_scanner import audit_job_description
from app.schemas.api_models import BiasAuditRequest

router = APIRouter(prefix="/bias-audit", tags=["ethical-ai"])


@router.post("/jd")
def audit_jd(request: BiasAuditRequest) -> dict:
    result = audit_job_description(request.jd_text)
    return result.to_dict()
