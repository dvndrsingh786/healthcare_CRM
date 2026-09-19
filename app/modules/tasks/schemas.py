from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas import AwareDateTime, Out, Page, StrictModel

Priority = Literal["LOW", "NORMAL", "HIGH", "URGENT"]
TaskStatus = Literal["OPEN", "IN_PROGRESS", "DONE", "CANCELLED"]
Title = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=4000)]


class TaskCreate(StrictModel):
    title: Title
    description: Description | None = None
    owner_user_id: UUID | None = Field(None, description="Staff member responsible. Default: you")
    patient_id: UUID | None = None
    appointment_id: UUID | None = Field(None, description="The patient is taken from the appointment if not given")
    priority: Priority = "NORMAL"
    due_at: AwareDateTime | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "title": "Call to check on new medication", "patient_id": "0b6c1f0e-3a55-4c1e-9d0a-2f7f5d1c9a10",
        "priority": "HIGH", "due_at": "2027-03-16T12:00:00Z",
    }]}}


class TaskUpdate(StrictModel):
    """Use /complete, /reopen and /cancel for those status changes."""
    version: int = Field(ge=1)
    title: Title | None = None
    description: Description | None = None
    owner_user_id: UUID | None = None
    priority: Priority | None = None
    due_at: AwareDateTime | None = None
    status: Literal["OPEN", "IN_PROGRESS"] | None = None

    @model_validator(mode="after")
    def required_fields_not_cleared(self):
        for field in ("title", "owner_user_id", "priority", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be empty.")
        return self

    model_config = {"json_schema_extra": {"examples": [
        {"version": 1, "status": "IN_PROGRESS", "due_at": "2027-03-18T12:00:00Z"},
    ]}}


class TaskOut(Out):
    id: UUID
    title: str
    description: str | None
    owner_user_id: UUID
    owner_display_name: str | None
    patient_id: UUID | None
    appointment_id: UUID | None
    priority: Priority
    due_at: datetime | None
    is_overdue: bool
    status: TaskStatus
    completed_at: datetime | None
    completed_by: UUID | None
    created_by: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


class TaskList(Page):
    data: list[TaskOut]
