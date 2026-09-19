"""Consent records (CRM side). The patient app's endpoints are in the app router."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.database import get_engine
from app.modules.consents import service
from app.modules.consents.schemas import ConsentCreate, ConsentOut, ConsentType
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Consent"])


@router.post("/patients/{patient_id}/consents", status_code=201, response_model=ConsentOut)
def record_consent(patient_id: UUID, data: ConsentCreate, principal=Depends(require("consents:write")),
                   engine=Depends(get_engine)):
    """Record a consent decision given to staff (verbally, on a form...). It is added as a new
    record; the previous one stays as evidence. **Permission:** `consents:write`."""
    with engine.begin() as db:
        consent_id = service.record_staff_consent(db, principal, patient_id, data)
        return service.get_consent(db, consent_id)


@router.get("/patients/{patient_id}/consents", response_model=list[ConsentOut])
def current_consents(patient_id: UUID, principal=Depends(require("consents:read")), engine=Depends(get_engine)):
    """The current state of each consent type (its latest record). **Permission:** `consents:read`."""
    with engine.connect() as db:
        return service.list_current(db, principal, patient_id)


@router.get("/patients/{patient_id}/consents/history", response_model=list[ConsentOut])
def consent_history(patient_id: UUID, consent_type: ConsentType | None = None,
                    principal=Depends(require("consents:read")), engine=Depends(get_engine)):
    """Every consent record, newest first, with who/how/when/which policy version.
    **Permission:** `consents:read`."""
    with engine.connect() as db:
        return service.list_history(db, principal, patient_id, consent_type)
