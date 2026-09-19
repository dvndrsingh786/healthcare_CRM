from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas import AwareDateTime, LongText, Out, Page, ShortText, StrictModel

NoteType = Literal["NOTE", "PHONE_CALL", "VISIT", "EMAIL", "SMS", "MEETING", "MESSAGE"]
Visibility = Literal["INTERNAL", "CLINICAL", "APP_VISIBLE"]
Subject = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class NoteCreate(StrictModel):
    note_type: NoteType = "NOTE"
    subject: Subject
    body: LongText
    visibility: Visibility = Field(description="INTERNAL: CRM staff. CLINICAL: restricted, needs "
                                               "notes:read_clinical. APP_VISIBLE: also shown to the patient")
    occurred_at: AwareDateTime | None = Field(None, description="When it happened. Default: now")
    appointment_id: UUID | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "note_type": "PHONE_CALL", "subject": "Welfare call", "visibility": "INTERNAL",
        "body": "Spoke to patient; managing well at home. Asked for a call back next week.",
    }]}}


class NoteUpdate(StrictModel):
    """Only the author can edit. The previous text is kept as a revision."""
    version: int = Field(ge=1)
    note_type: NoteType | None = None
    subject: Subject | None = None
    body: LongText | None = None
    visibility: Visibility | None = None
    occurred_at: AwareDateTime | None = None
    reason: ShortText | None = Field(None, description="Why it was changed (kept with the revision)")

    @model_validator(mode="after")
    def required_fields_not_cleared(self):
        for field in ("note_type", "subject", "body", "visibility", "occurred_at"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be empty.")
        return self

    model_config = {"json_schema_extra": {"examples": [
        {"version": 1, "body": "Spoke to patient and her son; managing well at home.",
         "reason": "Added who was present"},
    ]}}


class RetractRequest(StrictModel):
    reason: ShortText

    model_config = {"json_schema_extra": {"examples": [{"reason": "Recorded against the wrong patient"}]}}


class NoteOut(Out):
    id: UUID
    patient_id: UUID
    appointment_id: UUID | None
    author_user_id: UUID
    author_display_name: str | None
    note_type: NoteType
    subject: str
    body: str
    visibility: Visibility
    occurred_at: datetime
    status: str
    retracted_reason: str | None
    version: int
    edited: bool
    created_at: datetime
    updated_at: datetime


class NoteList(Page):
    data: list[NoteOut]


class NoteRevisionOut(Out):
    version: int
    note_type: str
    subject: str
    body: str
    visibility: Visibility
    occurred_at: datetime
    edited_by: UUID
    edit_reason: str | None
    edited_at: datetime


class AppMessageOut(Out):
    """A note the care team chose to share with the patient."""
    id: UUID
    note_type: str
    subject: str
    body: str
    occurred_at: datetime
    author_display_name: str | None


class AppMessageList(Page):
    data: list[AppMessageOut]
