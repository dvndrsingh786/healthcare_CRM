"""Patients, emergency contacts and patient app accounts (CRM side). The patient app's own
profile is in the app_api module.

Every endpoint first checks the permission (require / require_any), then the service layer
checks that the caller may see this particular patient (see access.py).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.database import get_engine
from app.modules.patients import service
from app.modules.patients.schemas import (
    AppAccountCreate,
    ArchiveRequest,
    EmergencyContactIn,
    EmergencyContactOut,
    EmergencyContactUpdate,
    PatientCreate,
    PatientList,
    PatientOut,
    PatientUpdate,
)
from app.pagination import page_params
from app.security import require, require_any

router = APIRouter(prefix="/api/v1", tags=["Patients"])

# Anyone who can see at least some patients.
can_read_patients = require_any("patients:read_all", "patients:read_assigned")


@router.post("/patients", status_code=201, response_model=PatientOut)
def create_patient(data: PatientCreate, principal=Depends(require("patients:write")), engine=Depends(get_engine)):
    """Create a patient, optionally with emergency contacts. **Permission:** `patients:write`.

    - Same MRN as another patient of your organisation: 409 `DUPLICATE_IDENTIFIER`.
    - Same first name, last name and date of birth as an existing patient: 409 `POSSIBLE_DUPLICATE`.
      Check it is a different person, then resend with `confirm_not_duplicate: true`.
    """
    with engine.begin() as db:
        patient_id = service.create_patient(db, principal, data)
        return service.serialize(principal, service.find_patient(db, principal, patient_id))


@router.get("/patients", response_model=PatientList)
def list_patients(
    search: str | None = Query(None, min_length=2, max_length=100,
                               description="Matches name, email, phone (and MRN if you may see it)"),
    status: str | None = Query(None, pattern="(?i)^(active|inactive|archived)$",
                               description="ACTIVE, INACTIVE or ARCHIVED. Default: everything except ARCHIVED"),
    assigned_staff_id: UUID | None = None,
    team_id: UUID | None = None,
    sort: str | None = Query(None, description="updated_at, created_at, legal_last_name, date_of_birth "
                                               "(prefix - for descending). Default -updated_at"),
    paging=Depends(page_params),
    principal=Depends(can_read_patients),
    engine=Depends(get_engine),
):
    """Search and filter the patients you may see. **Permission:** `patients:read_all`, or
    `patients:read_assigned` (then only patients assigned to you or your teams).

    Filters narrow your visible patients; they can never widen them.
    """
    with engine.connect() as db:
        return service.list_patients(db, principal, paging, search, status.upper() if status else None,
                                     assigned_staff_id, team_id, sort)


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: UUID, principal=Depends(can_read_patients), engine=Depends(get_engine)):
    """One patient. Sensitive fields (MRN, date of birth, address) are null unless you have
    `patients:read_sensitive`. Not visible to you: 404. Every read is audited."""
    with engine.begin() as db:
        return service.get_patient(db, principal, patient_id)


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: UUID, data: PatientUpdate, principal=Depends(require("patients:write")),
                   engine=Depends(get_engine)):
    """Update the fields you send. Include the `version` you read; if the patient changed since,
    you get 409 `VERSION_CONFLICT`. Archived patients cannot be edited. **Permission:** `patients:write`."""
    with engine.begin() as db:
        service.update_patient(db, principal, patient_id, data.model_dump(exclude_unset=True))
        return service.get_patient(db, principal, patient_id, audit=False)


@router.post("/patients/{patient_id}/archive", response_model=PatientOut)
def archive_patient(patient_id: UUID, data: ArchiveRequest, principal=Depends(require("patients:archive")),
                    engine=Depends(get_engine)):
    """Archive a patient (records are kept, never deleted). Their app account is deactivated and
    signed out. **Permission:** `patients:archive`."""
    with engine.begin() as db:
        service.archive_patient(db, principal, patient_id, data.reason)
        return service.get_patient(db, principal, patient_id, audit=False)


@router.post("/patients/{patient_id}/restore", response_model=PatientOut)
def restore_patient(patient_id: UUID, principal=Depends(require("patients:archive")), engine=Depends(get_engine)):
    """Bring an archived patient back to ACTIVE. The app account stays deactivated until staff
    re-activate it. **Permission:** `patients:archive`."""
    with engine.begin() as db:
        service.restore_patient(db, principal, patient_id)
        return service.get_patient(db, principal, patient_id, audit=False)


@router.post("/patients/{patient_id}/app-account", status_code=201, response_model=PatientOut)
def create_app_account(patient_id: UUID, data: AppAccountCreate, principal=Depends(require("patients:write")),
                       engine=Depends(get_engine)):
    """Invite the patient to the app: creates their app account and emails a one-time code to set
    a password. **Permission:** `patients:write`."""
    with engine.begin() as db:
        service.create_app_account(db, principal, patient_id, data.email)
        return service.get_patient(db, principal, patient_id, audit=False)


# ---------- Emergency contacts ----------

@router.get("/patients/{patient_id}/emergency-contacts", response_model=list[EmergencyContactOut])
def list_contacts(patient_id: UUID, principal=Depends(can_read_patients), engine=Depends(get_engine)):
    """Emergency contacts / next of kin, in call order. **Permission:** can see the patient."""
    with engine.connect() as db:
        return service.list_contacts(db, principal, patient_id)


@router.post("/patients/{patient_id}/emergency-contacts", status_code=201, response_model=EmergencyContactOut)
def add_contact(patient_id: UUID, data: EmergencyContactIn, principal=Depends(require("patients:write")),
                engine=Depends(get_engine)):
    """Add an emergency contact (phone or email required). **Permission:** `patients:write`."""
    with engine.begin() as db:
        return service.add_contact(db, principal, patient_id, data.model_dump())


@router.patch("/patients/{patient_id}/emergency-contacts/{contact_id}", response_model=EmergencyContactOut)
def update_contact(patient_id: UUID, contact_id: UUID, data: EmergencyContactUpdate,
                   principal=Depends(require("patients:write")), engine=Depends(get_engine)):
    """Update an emergency contact. **Permission:** `patients:write`."""
    with engine.begin() as db:
        return service.update_contact(db, principal, patient_id, contact_id, data.model_dump(exclude_unset=True))


@router.delete("/patients/{patient_id}/emergency-contacts/{contact_id}", status_code=204)
def delete_contact(patient_id: UUID, contact_id: UUID, principal=Depends(require("patients:write")),
                   engine=Depends(get_engine)):
    """Remove an emergency contact. **Permission:** `patients:write`."""
    with engine.begin() as db:
        service.delete_contact(db, principal, patient_id, contact_id)
    return Response(status_code=204)
