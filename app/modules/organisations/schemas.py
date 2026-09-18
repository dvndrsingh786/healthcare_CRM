from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas import Name, Out, StrictModel


class RetentionSettings(StrictModel):
    patient_records_years: int | None = Field(None, ge=1, le=100)
    audit_events_years: int | None = Field(None, ge=1, le=100)
    notifications_days: int | None = Field(None, ge=30, le=3650)
    delete_on_app_account_closure: bool | None = None


class NotificationSettings(StrictModel):
    transactional_ignores_opt_out: bool | None = None


class SettingsUpdate(StrictModel):
    retention: RetentionSettings | None = None
    notifications: NotificationSettings | None = None


class OrganisationUpdate(StrictModel):
    name: Name | None = None
    timezone: str | None = Field(None, max_length=64)
    settings: SettingsUpdate | None = None


class OrganisationResponse(Out):
    id: UUID
    name: str
    slug: str
    status: str
    timezone: str
    data_region: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
