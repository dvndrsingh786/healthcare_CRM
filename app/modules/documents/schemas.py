from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas import Out, Page, ShortText, StrictModel

Category = Literal["REFERRAL", "CARE_PLAN", "LETTER", "CONSENT_FORM", "ASSESSMENT", "IDENTITY", "OTHER"]
Visibility = Literal["INTERNAL", "CLINICAL", "APP_VISIBLE"]
DocumentStatus = Literal["PENDING_UPLOAD", "AVAILABLE", "REJECTED", "ARCHIVED"]
# A plain file name: no folders, no control characters.
FileName = Annotated[str, StringConstraints(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f]+$")]


class UploadIntent(StrictModel):
    original_filename: FileName
    mime_type: Literal["application/pdf", "image/png", "image/jpeg"]
    size_bytes: int = Field(gt=0, description="Exact size of the file you will upload")
    category: Category
    visibility: Visibility = "INTERNAL"
    title: Annotated[str, StringConstraints(max_length=200)] | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "original_filename": "referral-letter.pdf", "mime_type": "application/pdf", "size_bytes": 48213,
        "category": "REFERRAL", "visibility": "INTERNAL", "title": "GP referral",
    }]}}


class ConfirmUpload(StrictModel):
    checksum_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = Field(
        None, description="Optional: the SHA-256 you computed; the upload is rejected if it differs")

    model_config = {"json_schema_extra": {"examples": [
        {"checksum_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"},
    ]}}


class ArchiveDocument(StrictModel):
    reason: ShortText

    model_config = {"json_schema_extra": {"examples": [{"reason": "Replaced by an updated care plan"}]}}


class DocumentOut(Out):
    id: UUID
    patient_id: UUID
    category: Category
    title: str | None
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str | None
    visibility: Visibility
    status: DocumentStatus
    scan_status: str
    rejected_reason: str | None
    uploaded_by: UUID
    uploaded_at: datetime | None
    archived_at: datetime | None
    created_at: datetime


class DocumentList(Page):
    data: list[DocumentOut]


class UploadIntentOut(Out):
    document: DocumentOut
    upload_url: str = Field(description="PUT the raw file bytes here, with Content-Type = mime_type")
    upload_method: Literal["PUT"] = "PUT"
    expires_at: datetime


class DownloadLink(Out):
    download_url: str
    expires_at: datetime


class AppDocumentOut(Out):
    id: UUID
    category: str
    title: str | None
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime | None


class AppDocumentList(Page):
    data: list[AppDocumentOut]
