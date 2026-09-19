"""Appointments / visits (CRM side). The patient app's view is in the app router."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.database import get_engine
from app.modules.appointments import service
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentEventOut,
    AppointmentList,
    AppointmentOut,
    AppointmentStatus,
    AppointmentUpdate,
    CancelRequest,
    RescheduleRequest,
)
from app.pagination import page_params
from app.schemas import AwareDateTime
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Appointments"])


@router.post("/appointments", status_code=201, response_model=AppointmentOut)
def create_appointment(data: AppointmentCreate, principal=Depends(require("appointments:write")),
                       engine=Depends(get_engine)):
    """Book an appointment for a patient you may see. **Permission:** `appointments:write`.

    Times need an explicit offset (or Z) and are stored in UTC; `timezone` is kept for display.
    The staff member must be free: overlapping bookings are 409 `APPOINTMENT_CONFLICT`.
    The patient is notified through the outbox (if the appointment is app-visible).
    """
    with engine.begin() as db:
        appointment_id = service.create_appointment(db, principal, data)
        return service.get_appointment(db, principal, appointment_id)


@router.get("/appointments", response_model=AppointmentList)
def list_appointments(
    patient_id: UUID | None = None,
    staff_user_id: UUID | None = None,
    team_id: UUID | None = None,
    status: AppointmentStatus | None = None,
    starts_from: AwareDateTime | None = Query(None, alias="from", description="Start time >= this (ISO 8601, "
                                                                             "e.g. 2026-10-01T00:00:00Z)"),
    starts_before: AwareDateTime | None = Query(None, alias="to", description="Start time < this"),
    sort: str | None = Query(None, description="starts_at, created_at, updated_at (prefix - for descending)"),
    paging=Depends(page_params),
    principal=Depends(require("appointments:read")),
    engine=Depends(get_engine),
):
    """Appointments of patients you may see, and your own bookings. **Permission:** `appointments:read`."""
    with engine.connect() as db:
        return service.list_appointments(db, principal, paging, patient_id, staff_user_id, team_id, status,
                                         starts_from, starts_before, sort)


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: UUID, principal=Depends(require("appointments:read")),
                    engine=Depends(get_engine)):
    """One appointment. Not visible to you: 404. **Permission:** `appointments:read`."""
    with engine.connect() as db:
        return service.get_appointment(db, principal, appointment_id)


@router.get("/appointments/{appointment_id}/history", response_model=list[AppointmentEventOut])
def appointment_history(appointment_id: UUID, principal=Depends(require("appointments:read")),
                        engine=Depends(get_engine)):
    """Every lifecycle step (created, rescheduled, cancelled...) with who and when.
    **Permission:** `appointments:read`."""
    with engine.connect() as db:
        return service.list_events(db, principal, appointment_id)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(appointment_id: UUID, data: AppointmentUpdate,
                       principal=Depends(require("appointments:write")), engine=Depends(get_engine)):
    """Change staff, type, mode, location, instructions or app visibility of a SCHEDULED/CONFIRMED
    appointment. Send the `version` you read (409 `VERSION_CONFLICT` otherwise).
    **Permission:** `appointments:write`."""
    with engine.begin() as db:
        service.update_appointment(db, principal, appointment_id, data.model_dump(exclude_unset=True))
        return service.get_appointment(db, principal, appointment_id)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(appointment_id: UUID, data: RescheduleRequest, principal=Depends(require("appointments:write")),
               engine=Depends(get_engine)):
    """Move to a new time. A confirmed appointment goes back to SCHEDULED. Audited, kept in the
    history, and the patient is notified. **Permission:** `appointments:write`."""
    with engine.begin() as db:
        service.reschedule(db, principal, appointment_id, data)
        return service.get_appointment(db, principal, appointment_id)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
def confirm(appointment_id: UUID, principal=Depends(require("appointments:write")), engine=Depends(get_engine)):
    """SCHEDULED -> CONFIRMED. **Permission:** `appointments:write`."""
    with engine.begin() as db:
        service.change_status(db, principal, appointment_id, "CONFIRMED")
        return service.get_appointment(db, principal, appointment_id)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(appointment_id: UUID, data: CancelRequest, principal=Depends(require("appointments:write")),
           engine=Depends(get_engine)):
    """Cancel with a reason. Final. Audited and the patient is notified. **Permission:** `appointments:write`."""
    with engine.begin() as db:
        service.change_status(db, principal, appointment_id, "CANCELLED", reason=data.reason)
        return service.get_appointment(db, principal, appointment_id)


@router.post("/appointments/{appointment_id}/complete", response_model=AppointmentOut)
def complete(appointment_id: UUID, principal=Depends(require("appointments:update_outcome")),
             engine=Depends(get_engine)):
    """Record that the appointment took place (only after it started). **Permission:** `appointments:update_outcome`."""
    with engine.begin() as db:
        service.change_status(db, principal, appointment_id, "COMPLETED")
        return service.get_appointment(db, principal, appointment_id)


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentOut)
def no_show(appointment_id: UUID, principal=Depends(require("appointments:update_outcome")),
            engine=Depends(get_engine)):
    """Record that the patient did not attend (only after it started).
    **Permission:** `appointments:update_outcome`."""
    with engine.begin() as db:
        service.change_status(db, principal, appointment_id, "NO_SHOW")
        return service.get_appointment(db, principal, appointment_id)
