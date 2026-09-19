"""Assigning staff and teams to patients, and staff caseloads."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.database import get_engine
from app.modules.assignments import service
from app.modules.patients.schemas import AssignmentCreate, AssignmentOut, Caseload
from app.pagination import page_params
from app.security import require, require_any

router = APIRouter(prefix="/api/v1", tags=["Assignments"])

can_read_patients = require_any("patients:read_all", "patients:read_assigned")


@router.get("/patients/{patient_id}/assignments", response_model=list[AssignmentOut])
def list_assignments(patient_id: UUID, include_ended: bool = False, principal=Depends(can_read_patients),
                     engine=Depends(get_engine)):
    """Who is responsible for the patient. `include_ended=true` adds past assignments (history).
    **Permission:** can see the patient."""
    with engine.connect() as db:
        return service.list_assignments(db, principal, patient_id, include_ended)


@router.post("/patients/{patient_id}/assignments", status_code=201, response_model=AssignmentOut)
def assign(patient_id: UUID, data: AssignmentCreate, principal=Depends(require("assignments:manage")),
           engine=Depends(get_engine)):
    """Assign an active staff member (PRIMARY or SECONDARY) or a team (TEAM) to the patient.

    One active PRIMARY per patient; the same person or team cannot be assigned twice
    (409 `ASSIGNMENT_CONFLICT`). **Permission:** `assignments:manage`.
    """
    with engine.begin() as db:
        return service.assign(db, principal, patient_id, data)


@router.post("/patients/{patient_id}/assignments/{assignment_id}/end", response_model=AssignmentOut)
def end_assignment(patient_id: UUID, assignment_id: UUID, principal=Depends(require("assignments:manage")),
                   engine=Depends(get_engine)):
    """Unassign: the assignment ends today and is kept as history. **Permission:** `assignments:manage`."""
    with engine.begin() as db:
        return service.end_assignment(db, principal, patient_id, assignment_id)


@router.get("/staff/{staff_user_id}/caseload", response_model=Caseload)
def caseload(staff_user_id: UUID, paging=Depends(page_params),
             principal=Depends(require_any("patients:read_all", "patients:read_assigned", "assignments:manage")),
             engine=Depends(get_engine)):
    """Patients assigned to a staff member, directly or through their teams. You can always see
    your own; someone else's needs `assignments:manage`."""
    with engine.connect() as db:
        return service.caseload(db, principal, staff_user_id, paging)
