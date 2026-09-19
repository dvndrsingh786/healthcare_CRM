from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas import AwareDateTime, Out, Page, ShortText, StrictModel

AppointmentType = Literal["HOME_VISIT", "CLINIC", "ASSESSMENT", "REVIEW", "FOLLOW_UP", "OTHER"]
AppointmentMode = Literal["IN_PERSON", "PHONE", "VIDEO"]
AppointmentStatus = Literal["SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"]
TimeZoneName = Annotated[str, StringConstraints(min_length=3, max_length=64)]
Instructions = Annotated[str, StringConstraints(max_length=1000)]
InternalNote = Annotated[str, StringConstraints(max_length=2000)]


class AppointmentCreate(StrictModel):
    patient_id: UUID
    staff_user_id: UUID | None = None
    team_id: UUID | None = None
    starts_at: AwareDateTime = Field(description="With a UTC offset or Z, e.g. 2026-10-01T09:30:00+01:00")
    ends_at: AwareDateTime
    timezone: TimeZoneName | None = Field(None, description="IANA name, e.g. Europe/London. "
                                                            "Default: the organisation's time zone")
    appointment_type: AppointmentType
    mode: AppointmentMode = "IN_PERSON"
    location: ShortText | None = None
    patient_instructions: Instructions | None = Field(None, description="Shown to the patient in the app")
    internal_note: InternalNote | None = Field(None, description="CRM only; never shown in the app")
    app_visible: bool = True

    model_config = {"json_schema_extra": {"examples": [{
        "patient_id": "0b6c1f0e-3a55-4c1e-9d0a-2f7f5d1c9a10", "staff_user_id": "5f1d7c3e-8b2a-4e61-a0c4-7d9e2b6f1a33",
        "starts_at": "2026-10-01T09:30:00+01:00", "ends_at": "2026-10-01T10:15:00+01:00",
        "timezone": "Europe/London", "appointment_type": "HOME_VISIT", "mode": "IN_PERSON",
        "location": "Patient's home", "patient_instructions": "Please have your medication list ready.",
    }]}}


class AppointmentUpdate(StrictModel):
    """Details only. Use /reschedule to change the time and the status endpoints for the lifecycle."""
    version: int = Field(ge=1)
    staff_user_id: UUID | None = None
    team_id: UUID | None = None
    appointment_type: AppointmentType | None = None
    mode: AppointmentMode | None = None
    location: ShortText | None = None
    patient_instructions: Instructions | None = None
    internal_note: InternalNote | None = None
    app_visible: bool | None = None

    model_config = {"json_schema_extra": {"examples": [
        {"version": 2, "mode": "PHONE", "location": None, "patient_instructions": "We will call you on your mobile."},
    ]}}


class RescheduleRequest(StrictModel):
    version: int = Field(ge=1)
    starts_at: AwareDateTime
    ends_at: AwareDateTime
    timezone: TimeZoneName | None = None
    reason: ShortText | None = None

    model_config = {"json_schema_extra": {"examples": [
        {"version": 2, "starts_at": "2026-10-03T14:00:00+01:00", "ends_at": "2026-10-03T14:45:00+01:00",
         "reason": "Nurse unavailable"},
    ]}}


class CancelRequest(StrictModel):
    reason: ShortText

    model_config = {"json_schema_extra": {"examples": [{"reason": "Patient admitted to hospital"}]}}


class AppointmentOut(Out):
    id: UUID
    patient_id: UUID
    patient_name: str
    staff_user_id: UUID | None
    staff_display_name: str | None
    team_id: UUID | None
    team_name: str | None
    starts_at: datetime
    ends_at: datetime
    timezone: str
    starts_at_local: str = Field(description="Start time in the appointment's own time zone")
    appointment_type: str
    mode: str
    location: str | None
    patient_instructions: str | None
    internal_note: str | None
    status: AppointmentStatus
    cancellation_reason: str | None
    cancelled_at: datetime | None
    outcome_recorded_at: datetime | None
    app_visible: bool
    version: int
    created_at: datetime
    updated_at: datetime


class AppointmentList(Page):
    data: list[AppointmentOut]


class AppointmentEventOut(Out):
    event: str
    from_status: str | None
    to_status: str
    old_starts_at: datetime | None
    new_starts_at: datetime | None
    reason: str | None
    actor_user_id: UUID | None
    occurred_at: datetime


class AppAppointmentOut(Out):
    """The patient app's view: no internal note, no staff ids, no audit fields."""
    id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone: str
    starts_at_local: str
    appointment_type: str
    mode: str
    location: str | None
    patient_instructions: str | None
    status: AppointmentStatus
    staff_display_name: str | None
    team_name: str | None
    cancellation_reason: str | None


class AppAppointmentList(Page):
    data: list[AppAppointmentOut]
