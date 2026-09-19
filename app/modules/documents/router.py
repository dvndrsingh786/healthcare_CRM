"""Documents (CRM side) and the signed storage links shared with the patient app."""
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.database import get_engine
from app.errors import ApiError
from app.modules.documents import service
from app.modules.documents.schemas import (
    ArchiveDocument,
    Category,
    ConfirmUpload,
    DocumentList,
    DocumentOut,
    DocumentStatus,
    DownloadLink,
    UploadIntent,
    UploadIntentOut,
)
from app.pagination import page_params
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Documents"])
storage_router = APIRouter(prefix="/api/v1/storage", tags=["Documents"])


@router.post("/patients/{patient_id}/documents", status_code=201, response_model=UploadIntentOut)
def create_upload_intent(patient_id: UUID, data: UploadIntent, principal=Depends(require("documents:write")),
                         engine=Depends(get_engine)):
    """Step 1: declare the file (PDF, PNG or JPEG; size up to MAX_UPLOAD_BYTES) and get a
    short-lived upload link. Then PUT the bytes to `upload_url` and call `/confirm`.
    **Permission:** `documents:write` (+ `notes:read_clinical` for CLINICAL documents)."""
    with engine.begin() as db:
        document_id, url, expires_at = service.create_upload_intent(db, principal, patient_id, data)
        return {"document": service.find_document(db, principal, document_id), "upload_url": url,
                "expires_at": expires_at}


@router.post("/documents/{document_id}/confirm", response_model=DocumentOut)
def confirm_upload(document_id: UUID, data: ConfirmUpload, principal=Depends(require("documents:write")),
                   engine=Depends(get_engine)):
    """Step 3: verify the uploaded file (size, real file type, optional checksum, malware hook).
    Rejected files are deleted and the call fails with 422 `FILE_REJECTED`.
    **Permission:** `documents:write`."""
    with engine.begin() as db:
        reason = service.confirm_upload(db, principal, document_id, data.checksum_sha256)
    if reason is not None:
        raise ApiError(422, "FILE_REJECTED", f"The uploaded file was rejected ({reason}). Upload it again.")
    with engine.connect() as db:
        return service.find_document(db, principal, document_id)


@router.get("/patients/{patient_id}/documents", response_model=DocumentList)
def list_documents(patient_id: UUID, category: Category | None = None, status: DocumentStatus | None = None,
                   paging=Depends(page_params), principal=Depends(require("documents:read")),
                   engine=Depends(get_engine)):
    """Documents you may see (CLINICAL ones only with `notes:read_clinical`). Default: available and
    pending uploads. **Permission:** `documents:read`."""
    with engine.connect() as db:
        return service.list_documents(db, principal, patient_id, paging, category, status)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: UUID, principal=Depends(require("documents:read")), engine=Depends(get_engine)):
    """Document metadata. **Permission:** `documents:read`."""
    with engine.connect() as db:
        return service.find_document(db, principal, document_id)


@router.post("/documents/{document_id}/download-link", response_model=DownloadLink)
def download_link(document_id: UUID, principal=Depends(require("documents:read")), engine=Depends(get_engine)):
    """A download link valid for SIGNED_URL_SECONDS. Your access is checked again when it is used.
    Audited. **Permission:** `documents:read`."""
    with engine.begin() as db:
        return service.create_download_link(db, principal, service.find_document(db, principal, document_id))


@router.post("/documents/{document_id}/archive", response_model=DocumentOut)
def archive_document(document_id: UUID, data: ArchiveDocument, principal=Depends(require("documents:write")),
                     engine=Depends(get_engine)):
    """Archive (hide) a document. It is kept under the retention policy, never deleted.
    **Permission:** `documents:write`."""
    with engine.begin() as db:
        service.archive_document(db, principal, document_id, data.reason)
        return service.find_document(db, principal, document_id)


# ---------- Signed links (no bearer token: the signed token is the credential) ----------

@storage_router.put("/upload/{token}", status_code=204)
async def upload(token: str, request: Request, engine=Depends(get_engine)):
    """Step 2: send the raw file bytes. Single use; the size must match what was declared."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > get_settings().max_upload_bytes:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "The file is too large.")
    # Read with a hard cap so a client cannot stream an endless body into memory.
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > get_settings().max_upload_bytes:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "The file is too large.")
        chunks.append(chunk)
    await run_in_threadpool(service.receive_upload, engine, token, request.headers.get("content-type"), chunks)
    return Response(status_code=204)


@storage_router.get("/download/{token}")
def download(token: str, engine=Depends(get_engine)):
    """Stream a document. The link must be valid and unexpired, AND the person it was issued to
    must still have access to the document right now."""
    document, chunks = service.open_download(engine, token)
    filename = quote(document["original_filename"])
    return StreamingResponse(chunks, media_type=document["mime_type"], headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "Content-Length": str(document["size_bytes"]),
    })
