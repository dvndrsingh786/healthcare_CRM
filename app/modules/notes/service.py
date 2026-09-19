"""Interactions / notes with visibility classes (see migration 008 and patients/access.py).

- A note is visible when its patient is visible AND its class is readable by the caller.
- Writing a CLINICAL note needs notes:read_clinical too (you cannot write what you may not read).
- Only the author edits a note; every edit stores the previous version in note_revisions.
- Notes are never deleted; a wrong one is retracted (ENTERED_IN_ERROR) with a reason.
- Reads that return CLINICAL content are audited.
"""
from datetime import UTC, datetime

from sqlalchemy import text

from app.audit import changed_fields, record_event
from app.errors import ApiError, conflict, forbidden, invalid, not_found
from app.modules.patients.access import (
    check_patient_link,
    find_patient,
    log_denied_access,
    readable_visibilities,
    visibility_condition,
    visible_patient_condition,
)
from app.pagination import paginate

NOTE_SELECT = """
    SELECT n.*, sp.display_name AS author_display_name, n.version > 1 AS edited
    FROM notes n LEFT JOIN staff_profiles sp ON sp.user_id = n.author_user_id
"""
EDITABLE_COLUMNS = ("note_type", "subject", "body", "visibility", "occurred_at")


def note_scope(principal, alias="n"):
    patient_visible, params = visible_patient_condition(principal, f"{alias}.patient_id")
    classes = visibility_condition(f"{alias}.visibility", readable_visibilities(principal, "notes:read"))
    return f"{alias}.organisation_id = :org AND {classes} AND {patient_visible}", params


def check_can_write(principal, visibility):
    if visibility == "CLINICAL" and "notes:read_clinical" not in principal["permissions"]:
        raise forbidden("You cannot write CLINICAL notes.")


def audit_clinical_read(db, principal, patient_id, notes):
    clinical = [str(n["id"]) for n in notes if n["visibility"] == "CLINICAL"]
    if clinical:
        record_event(db, principal, "note.read_clinical", "patient", patient_id, metadata={"note_ids": clinical})


def find_note(db, principal, note_id, lock=False):
    condition, params = note_scope(principal)
    row = db.execute(text(f"{NOTE_SELECT} WHERE n.id = :id AND {condition}" + (" FOR UPDATE OF n" if lock else "")),
                     dict(params, id=note_id)).mappings().first()
    if row is None:
        log_denied_access(db, principal, "note", note_id)
        raise not_found("Note")
    return row


def get_note(db, principal, note_id):
    note = find_note(db, principal, note_id)
    audit_clinical_read(db, principal, note["patient_id"], [note])
    return note


def create_note(db, principal, patient_id, data):
    check_can_write(principal, data.visibility)
    patient = check_patient_link(db, principal, patient_id)
    if patient["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Notes cannot be added to an archived patient.")
    if data.appointment_id is not None:
        belongs = db.execute(text("SELECT 1 FROM appointments WHERE id = :id AND patient_id = :p"),
                             {"id": data.appointment_id, "p": patient_id}).first()
        if not belongs:
            raise invalid("The appointment does not belong to this patient.", field="appointment_id")
    occurred_at = data.occurred_at or datetime.now(UTC)
    if occurred_at > datetime.now(UTC):
        raise invalid("occurred_at cannot be in the future.", field="occurred_at")
    note_id = db.execute(
        text("""
            INSERT INTO notes (organisation_id, patient_id, appointment_id, author_user_id, note_type, subject, body,
                               visibility, occurred_at, updated_by)
            VALUES (:org, :patient_id, :appointment_id, :by, :note_type, :subject, :body, :visibility, :occurred_at,
                    :by)
            RETURNING id
        """),
        {"org": principal["organisation_id"], "patient_id": patient_id, "appointment_id": data.appointment_id,
         "by": principal["user_id"], "note_type": data.note_type, "subject": data.subject, "body": data.body,
         "visibility": data.visibility, "occurred_at": occurred_at},
    ).scalar_one()
    record_event(db, principal, "note.create", "note", note_id,
                 metadata={"patient_id": str(patient_id), "visibility": data.visibility})
    if data.visibility == "APP_VISIBLE":
        from app.modules.notifications.service import queue_patient_notification
        queue_patient_notification(db, principal, patient_id, "new_message", "note", note_id, "created")
    return note_id


def list_notes(db, principal, patient_id, paging, visibility=None, note_type=None, include_retracted=True):
    find_patient(db, principal, patient_id)
    condition, params = note_scope(principal)
    conditions = [condition, "n.patient_id = :patient_id"]
    params["patient_id"] = patient_id
    if visibility:
        conditions.append("n.visibility = :f_visibility")
        params["f_visibility"] = visibility
    if note_type:
        conditions.append("n.note_type = :f_type")
        params["f_type"] = note_type
    if not include_retracted:
        conditions.append("n.status = 'ACTIVE'")
    where = " AND ".join(conditions)
    page = paginate(db, f"{NOTE_SELECT} WHERE {where} ORDER BY n.occurred_at DESC, n.id DESC",
                    f"SELECT count(*) FROM notes n WHERE {where}", params, paging)
    audit_clinical_read(db, principal, patient_id, page["data"])
    return page


def find_own_note(db, principal, note_id):
    note = find_note(db, principal, note_id, lock=True)
    if str(note["author_user_id"]) != str(principal["user_id"]):
        raise forbidden("Only the author can change a note.")
    if note["status"] != "ACTIVE":
        raise ApiError(409, "INVALID_STATE", "A retracted note cannot be changed.")
    return note


def update_note(db, principal, note_id, changes):
    version = changes.pop("version")
    reason = changes.pop("reason", None)
    old = find_own_note(db, principal, note_id)
    if old["version"] != version:
        raise conflict("This note was changed since you read it. Reload it and try again.", code="VERSION_CONFLICT")
    if "visibility" in changes:
        check_can_write(principal, changes["visibility"])
    if changes.get("occurred_at") and changes["occurred_at"] > datetime.now(UTC):
        raise invalid("occurred_at cannot be in the future.", field="occurred_at")
    changes = {c: v for c, v in changes.items() if c in EDITABLE_COLUMNS}
    changed = changed_fields(old, changes)
    if not changed:
        return
    # Keep the text as it was before this edit.
    db.execute(
        text("""
            INSERT INTO note_revisions (organisation_id, note_id, version, note_type, subject, body, visibility,
                                        occurred_at, edited_by, edit_reason)
            VALUES (:org, :id, :version, :note_type, :subject, :body, :visibility, :occurred_at, :by, :reason)
        """),
        {"org": principal["organisation_id"], "id": note_id, "version": old["version"],
         **{c: old[c] for c in EDITABLE_COLUMNS}, "by": principal["user_id"], "reason": reason},
    )
    sets = ", ".join(f"{c} = :{c}" for c in changed)
    db.execute(text(f"UPDATE notes SET {sets}, version = version + 1, updated_by = :by WHERE id = :id"),
               dict({c: changes[c] for c in changed}, by=principal["user_id"], id=note_id))
    record_event(db, principal, "note.update", "note", note_id, changed_fields=changed)


def retract_note(db, principal, note_id, reason):
    find_own_note(db, principal, note_id)
    db.execute(text("UPDATE notes SET status = 'ENTERED_IN_ERROR', retracted_reason = :reason, "
                    "version = version + 1, updated_by = :by WHERE id = :id"),
               {"reason": reason, "by": principal["user_id"], "id": note_id})
    record_event(db, principal, "note.retract", "note", note_id, changed_fields=["status"])


def list_revisions(db, principal, note_id):
    """Earlier versions. A revision that was in a class the caller may not read is left out,
    so re-classifying a note never exposes its restricted history."""
    find_note(db, principal, note_id)
    classes = visibility_condition("r.visibility", readable_visibilities(principal, "notes:read"))
    rows = db.execute(text(f"SELECT r.* FROM note_revisions r WHERE r.note_id = :id AND {classes} "
                           "ORDER BY r.version"), {"id": note_id}).mappings()
    return [dict(row) for row in rows]


# ---------- Patient app ----------

def list_app_messages(db, patient_id, paging):
    return paginate(
        db,
        f"{NOTE_SELECT} WHERE n.patient_id = :patient_id AND n.visibility = 'APP_VISIBLE' AND n.status = 'ACTIVE' "
        "ORDER BY n.occurred_at DESC, n.id DESC",
        "SELECT count(*) FROM notes n WHERE n.patient_id = :patient_id AND n.visibility = 'APP_VISIBLE' "
        "AND n.status = 'ACTIVE'",
        {"patient_id": patient_id}, paging,
    )
