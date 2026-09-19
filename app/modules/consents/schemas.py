from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas import AwareDateTime, Out, StrictModel

ConsentType = Literal["DATA_PROCESSING", "CARE_INFORMATION_SHARING", "APP_TERMS", "MARKETING_EMAIL",
                      "MARKETING_SMS", "RESEARCH_CONTACT"]
ConsentStatus = Literal["GRANTED", "WITHDRAWN", "REFUSED"]
PolicyVersion = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")]

# Consents a patient may change themselves in the app. The others (e.g. data processing for
# care, information sharing) are discussed with and recorded by staff.
APP_MANAGED_TYPES = ("APP_TERMS", "MARKETING_EMAIL", "MARKETING_SMS", "RESEARCH_CONTACT")


class ConsentCreate(StrictModel):
    consent_type: ConsentType
    status: ConsentStatus
    source: Literal["STAFF_VERBAL", "PAPER_FORM", "ELECTRONIC_FORM", "IMPORT"]
    policy_version: PolicyVersion = Field(description="Version of the consent wording/policy, e.g. privacy-2026.1")
    captured_at: AwareDateTime | None = Field(None, description="When the patient gave it. Default: now")
    expires_at: AwareDateTime | None = None
    evidence_document_id: UUID | None = Field(None, description="e.g. the scanned signed form")
    note: Annotated[str, StringConstraints(max_length=500)] | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "consent_type": "CARE_INFORMATION_SHARING", "status": "GRANTED", "source": "PAPER_FORM",
        "policy_version": "sharing-2026.1", "captured_at": "2026-09-18T10:00:00+01:00",
    }]}}


class AppConsentChange(StrictModel):
    consent_type: Literal["APP_TERMS", "MARKETING_EMAIL", "MARKETING_SMS", "RESEARCH_CONTACT"]
    status: Literal["GRANTED", "WITHDRAWN"]
    policy_version: PolicyVersion


class ConsentOut(Out):
    id: UUID
    consent_type: ConsentType
    status: ConsentStatus
    effective_status: str = Field(description="status, or EXPIRED once expires_at has passed")
    source: str
    policy_version: str
    captured_at: datetime
    expires_at: datetime | None
    captured_by: UUID
    captured_by_type: str
    evidence_document_id: UUID | None
    note: str | None
    supersedes_id: UUID | None
    recorded_at: datetime


class AppConsentOut(Out):
    consent_type: ConsentType
    status: ConsentStatus
    effective_status: str
    source: str
    policy_version: str
    captured_at: datetime
    expires_at: datetime | None
    recorded_at: datetime
    changeable_in_app: bool
