"""Documents: upload intent -> private upload -> confirmation -> authorised, short-lived download.

1. POST /patients/{id}/documents       creates a PENDING_UPLOAD row and a signed upload link.
2. PUT  /storage/upload/<token>        the client sends the bytes (single use, size-limited).
3. POST /documents/{id}/confirm        the server checks size, file signature, checksum and runs
                                       the malware hook -> AVAILABLE, or REJECTED (file deleted).
4. POST /documents/{id}/download-link  a signed link valid for SIGNED_URL_SECONDS.
5. GET  /storage/download/<token>      re-checks the user's CURRENT access, streams the file,
                                       and audits the download.

Visibility classes are the same as notes: CLINICAL needs notes:read_clinical to read OR upload.
Documents are archived, never deleted (retention); the stored file is kept.
"""
from datetime import UTC, datetime

from sqlalchemy import text

from app.audit import record_event
from app.config import get_settings
from app.errors import ApiError, forbidden, invalid, not_found
from app.modules.patients.access import (
    check_patient_link,
    find_patient,
    log_denied_access,
    readable_visibilities,
    visibility_condition,
    visible_patient_condition,
)
from app.pagination import paginate
from app.security import principal_for_user
from app.storage import (
    check_file_type,
    content_matches_type,
    get_scanner,
    get_storage,
    new_storage_key,
    sign,
    verify,
)


def document_scope(principal, alias="d"):
    patient_visible, params = visible_patient_condition(principal, f"{alias}.patient_id")
    classes = visibility_condition(f"{alias}.visibility", readable_visibilities(principal, "documents:read"))
    return f"{alias}.organisation_id = :org AND {classes} AND {patient_visible}", params


def find_document(db, principal, document_id, lock=False):
    condition, params = document_scope(principal)
    row = db.execute(text(f"SELECT d.* FROM documents d WHERE d.id = :id AND {condition}"
                          + (" FOR UPDATE OF d" if lock else "")), dict(params, id=document_id)).mappings().first()
    if row is None:
        log_denied_access(db, principal, "document", document_id)
        raise not_found("Document")
    return row


def find_app_document(db, principal, document_id):
    """A patient's own, app-visible, available document."""
    from app.modules.patients.service import find_own_patient

    patient = find_own_patient(db, principal)
    row = db.execute(
        text("SELECT * FROM documents WHERE id = :id AND patient_id = :patient_id AND visibility = 'APP_VISIBLE' "
             "AND status = 'AVAILABLE'"),
        {"id": document_id, "patient_id": patient["id"]},
    ).mappings().first()
    if row is None:
        log_denied_access(db, principal, "document", document_id)
        raise not_found("Document")
    return row


def utc(unix_seconds):
    return datetime.fromtimestamp(unix_seconds, UTC)


# ---------- Upload ----------

def create_upload_intent(db, principal, patient_id, data):
    if data.visibility == "CLINICAL" and "notes:read_clinical" not in principal["permissions"]:
        raise forbidden("You cannot upload CLINICAL documents.")
    patient = check_patient_link(db, principal, patient_id)
    if patient["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Documents cannot be added to an archived patient.")
    check_file_type(data.original_filename, data.mime_type)
    if data.size_bytes > get_settings().max_upload_bytes:
        raise invalid(f"Files can be at most {get_settings().max_upload_bytes} bytes.", field="size_bytes")

    document_id = db.execute(
        text("""
            INSERT INTO documents (organisation_id, patient_id, category, title, original_filename, mime_type,
                                   size_bytes, storage_key, visibility, uploaded_by)
            VALUES (:org, :patient_id, :category, :title, :filename, :mime_type, :size, :key, :visibility, :by)
            RETURNING id
        """),
        {"org": principal["organisation_id"], "patient_id": patient_id, "category": data.category,
         "title": data.title, "filename": data.original_filename, "mime_type": data.mime_type,
         "size": data.size_bytes, "key": new_storage_key(principal["organisation_id"]),
         "visibility": data.visibility, "by": principal["user_id"]},
    ).scalar_one()
    record_event(db, principal, "document.upload_intent", "document", document_id,
                 metadata={"patient_id": str(patient_id), "visibility": data.visibility})
    token, expires = sign("upload", document_id, principal["user_id"], principal["scope"])
    return document_id, f"/api/v1/storage/upload/{token}", utc(expires)


def receive_upload(engine, token, content_type, chunks):
    """Store the bytes for a PENDING_UPLOAD document. The signed token is the credential."""
    payload = verify(token, "upload")
    with engine.connect() as db:
        document = db.execute(text("SELECT * FROM documents WHERE id = :id"), {"id": payload["d"]}).mappings().first()
    if document is None or document["status"] != "PENDING_UPLOAD" or str(document["uploaded_by"]) != payload["u"]:
        raise ApiError(403, "INVALID_LINK", "This link is invalid or has expired. Request a new one.")
    if (content_type or "").split(";")[0].strip().lower() != document["mime_type"]:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", f"Send the file with Content-Type: {document['mime_type']}.")
    storage = get_storage()
    if storage.exists(document["storage_key"]):
        raise ApiError(409, "ALREADY_UPLOADED", "The file was already uploaded. Confirm it, or start a new upload.")
    storage.save(document["storage_key"], chunks, max_bytes=document["size_bytes"])


def reject(db, document, reason):
    get_storage().delete(document["storage_key"])
    db.execute(text("UPDATE documents SET status = 'REJECTED', rejected_reason = :reason WHERE id = :id"),
               {"reason": reason, "id": document["id"]})


def confirm_upload(db, principal, document_id, checksum=None):
    """Returns the rejection reason, or None when the document is now AVAILABLE."""
    document = find_document(db, principal, document_id, lock=True)
    if document["status"] != "PENDING_UPLOAD":
        raise ApiError(409, "INVALID_STATE", "This document is not waiting for an upload.")
    storage = get_storage()
    if not storage.exists(document["storage_key"]):
        raise ApiError(409, "UPLOAD_MISSING", "No file has been uploaded yet.")

    size, digest = storage.size_and_checksum(document["storage_key"])
    reason = None
    if size != document["size_bytes"]:
        reason = "SIZE_MISMATCH"
    elif not content_matches_type(storage.head(document["storage_key"]), document["mime_type"]):
        reason = "CONTENT_TYPE_MISMATCH"   # e.g. an executable renamed to .pdf
    elif checksum is not None and checksum != digest:
        reason = "CHECKSUM_MISMATCH"
    scan_status = "NOT_SCANNED"
    if reason is None:
        scan_status = get_scanner().scan(storage, document["storage_key"])
        if scan_status == "INFECTED":
            reason = "MALWARE_DETECTED"
    if reason is not None:
        reject(db, document, reason)
        record_event(db, principal, "document.rejected", "document", document_id, metadata={"reason": reason})
        return reason

    db.execute(text("UPDATE documents SET status = 'AVAILABLE', uploaded_at = now(), checksum_sha256 = :digest, "
                    "scan_status = :scan WHERE id = :id"), {"digest": digest, "scan": scan_status, "id": document_id})
    record_event(db, principal, "document.upload", "document", document_id,
                 metadata={"patient_id": str(document["patient_id"]), "size_bytes": size})
    if document["visibility"] == "APP_VISIBLE":
        from app.modules.notifications.service import queue_patient_notification
        queue_patient_notification(db, principal, document["patient_id"], "document_available", "document",
                                   document_id, "available")
    return None


# ---------- List / archive ----------

def list_documents(db, principal, patient_id, paging, category=None, status=None):
    find_patient(db, principal, patient_id)
    condition, params = document_scope(principal)
    conditions = [condition, "d.patient_id = :patient_id"]
    params["patient_id"] = patient_id
    if category:
        conditions.append("d.category = :f_category")
        params["f_category"] = category
    if status:
        conditions.append("d.status = :f_status")
        params["f_status"] = status
    else:
        conditions.append("d.status IN ('AVAILABLE', 'PENDING_UPLOAD')")
    where = " AND ".join(conditions)
    return paginate(db, f"SELECT d.* FROM documents d WHERE {where} ORDER BY d.created_at DESC, d.id DESC",
                    f"SELECT count(*) FROM documents d WHERE {where}", params, paging)


def archive_document(db, principal, document_id, reason):
    document = find_document(db, principal, document_id, lock=True)
    if document["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "The document is already archived.")
    db.execute(text("UPDATE documents SET status = 'ARCHIVED', archived_at = now(), archived_by = :by, "
                    "archived_reason = :reason WHERE id = :id"),
               {"by": principal["user_id"], "reason": reason, "id": document_id})
    record_event(db, principal, "document.archive", "document", document_id, changed_fields=["status"])


# ---------- Download ----------

def check_downloadable(document):
    if document["status"] != "AVAILABLE" or document["scan_status"] == "INFECTED":
        raise ApiError(409, "INVALID_STATE", "This document cannot be downloaded.")


def create_download_link(db, principal, document, app=False):
    check_downloadable(document)
    token, expires = sign("download", document["id"], principal["user_id"], principal["scope"])
    record_event(db, principal, "document.download_link", "document", document["id"], metadata={"app": app})
    return {"download_url": f"/api/v1/storage/download/{token}", "expires_at": utc(expires)}


def open_download(engine, token):
    """Check the link AND the holder's current right to the document. Returns (document, chunks)."""
    payload = verify(token, "download")
    with engine.begin() as db:
        principal = principal_for_user(db, payload["u"], payload["s"])
        if principal is None:
            raise ApiError(403, "INVALID_LINK", "This link is invalid or has expired. Request a new one.")
        if principal["scope"] == "app":
            document = find_app_document(db, principal, payload["d"])
        else:
            if "documents:read" not in principal["permissions"]:
                raise forbidden()
            document = find_document(db, principal, payload["d"])
        check_downloadable(document)
        record_event(db, principal, "document.download", "document", document["id"])
    return document, get_storage().read_chunks(document["storage_key"])
