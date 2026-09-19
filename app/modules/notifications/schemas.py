from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.modules.notifications.templates import TEMPLATES
from app.schemas import AwareDateTime, Out, Page, StrictModel

Channel = Literal["EMAIL", "SMS", "PUSH"]
NotificationStatus = Literal["QUEUED", "SENDING", "SENT", "FAILED", "SKIPPED", "CANCELLED"]


class NotificationCreate(StrictModel):
    """Only ids and a template key: the text comes from the template, the address from the patient
    record at send time. There is deliberately no free-text body field."""
    patient_id: UUID
    channel: Channel
    template_key: str = Field(description="One of: " + ", ".join(sorted(TEMPLATES)))
    reference_type: Literal["appointment", "task", "document", "note"] | None = None
    reference_id: UUID | None = None
    scheduled_at: AwareDateTime | None = Field(None, description="Send later. Default: as soon as possible")

    @field_validator("template_key")
    @classmethod
    def known_template(cls, value):
        if value not in TEMPLATES:
            raise ValueError("Unknown template_key.")
        return value

    model_config = {"json_schema_extra": {"examples": [{
        "patient_id": "0b6c1f0e-3a55-4c1e-9d0a-2f7f5d1c9a10", "channel": "SMS",
        "template_key": "appointment_reminder", "reference_type": "appointment",
        "reference_id": "8d2f5a61-0c4b-4f7e-9b3a-1e6d7c8f9a20",
    }]}}


class AttemptOut(Out):
    attempt_number: int
    outcome: str
    error_code: str | None
    attempted_at: datetime


class NotificationOut(Out):
    id: UUID
    patient_id: UUID | None
    channel: Channel
    template_key: str
    reference_type: str | None
    reference_id: UUID | None
    transactional: bool
    status: NotificationStatus
    skip_reason: str | None
    attempts: int
    max_attempts: int
    scheduled_at: datetime
    next_attempt_at: datetime
    last_error_code: str | None
    sent_at: datetime | None
    provider_message_id: str | None
    created_at: datetime
    updated_at: datetime


class NotificationDetail(NotificationOut):
    attempt_log: list[AttemptOut]


class NotificationList(Page):
    data: list[NotificationOut]


class ProcessResult(Out):
    processed: int
    sent: int
    retry_scheduled: int
    failed: int
    skipped: int
