"""Which patients may the caller see? The object-level rule every module reuses.

- patients:read_all       -> every patient of the caller's organisation
- patients:read_assigned  -> only patients with an ACTIVE assignment to the caller,
                             directly or through a team the caller belongs to
- anything else           -> none

A patient the caller may not see is reported as 404 NOT_FOUND (never 403), whether it
belongs to another organisation or just is not assigned, so a guessed UUID reveals nothing.
The attempt itself is written to the audit log as access.denied.
"""
from sqlalchemy import text

from app.audit import DENIED, record_event_now
from app.errors import not_found
from app.security import has

ASSIGNED_TO_CALLER = """
    EXISTS (
        SELECT 1 FROM patient_assignments pa
        WHERE pa.patient_id = {alias}.id AND pa.active
          AND (pa.staff_user_id = :caller_id
               OR pa.team_id IN (SELECT team_id FROM team_members WHERE user_id = :caller_id))
    )
"""


def patient_scope(principal, alias="p"):
    """SQL condition + params limiting rows of `patients {alias}` to what the caller may see."""
    params = {"org": principal["organisation_id"], "caller_id": principal["user_id"]}
    condition = f"{alias}.organisation_id = :org"
    if has(principal, "patients:read_all"):
        return condition, params
    if has(principal, "patients:read_assigned"):
        return condition + " AND " + ASSIGNED_TO_CALLER.format(alias=alias), params
    return "false", params


# Tables whose rows can be the target of a denied lookup. The table name always comes from here,
# never from the request.
AUDITED_TABLES = {"patient": "patients", "appointment": "appointments", "task": "tasks", "note": "notes",
                  "document": "documents", "notification": "notifications"}


def log_denied_access(db, principal, resource_type, resource_id):
    """If the id belongs to a real record the caller may not see, keep a record of the attempt.
    Guessing random ids that do not exist is not logged (there is nothing to protect)."""
    table = AUDITED_TABLES[resource_type]
    exists = db.execute(text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": resource_id}).first()
    if exists:
        # Own transaction: this request is about to fail with 404, which rolls back the main one.
        record_event_now(db.engine, principal, "access.denied", resource_type, resource_id, outcome=DENIED,
                         metadata={"reason": f"{resource_type}_not_visible"})


def log_denied_patient_access(db, principal, patient_id):
    log_denied_access(db, principal, "patient", patient_id)


def visible_patient_condition(principal, patient_column):
    """SQL condition: the patient in `patient_column` is one the caller may see.
    For records that point to a patient (appointments, notes, documents...)."""
    condition, params = patient_scope(principal, "vp")
    return f"EXISTS (SELECT 1 FROM patients vp WHERE vp.id = {patient_column} AND {condition})", params


def find_patient(db, principal, patient_id, lock=False):
    condition, params = patient_scope(principal)
    row = db.execute(
        text(f"SELECT p.* FROM patients p WHERE p.id = :patient_id AND {condition}"
             + (" FOR UPDATE" if lock else "")),
        dict(params, patient_id=patient_id),
    ).mappings().first()
    if row is None:
        log_denied_patient_access(db, principal, patient_id)
        raise not_found("Patient")
    return row


def check_patient_link(db, principal, patient_id, field="patient_id"):
    """For records that point to a patient (appointments, tasks, notes...): the patient must be
    one the caller can see. Otherwise the request is invalid (422), without saying why."""
    from app.errors import invalid

    condition, params = patient_scope(principal)
    row = db.execute(
        text(f"SELECT p.id, p.status FROM patients p WHERE p.id = :patient_id AND {condition}"),
        dict(params, patient_id=patient_id),
    ).mappings().first()
    if row is None:
        log_denied_patient_access(db, principal, patient_id)
        raise invalid("No such patient in your organisation, or you do not have access to it.", field=field)
    return row


# ---------- Visibility classes of notes and documents ----------

def readable_visibilities(principal, read_permission):
    """Which visibility classes the caller may read. read_permission is notes:read or documents:read.
    CLINICAL content additionally needs notes:read_clinical (support roles and the app never have it)."""
    from app.security import has

    if not has(principal, read_permission):
        return []
    classes = ["INTERNAL", "APP_VISIBLE"]
    if has(principal, "notes:read_clinical"):
        classes.append("CLINICAL")
    return classes


def visibility_condition(column, classes):
    """SQL condition limiting `column` to the given classes. The class names come from the list
    above (fixed strings), never from the request."""
    if not classes:
        return "false"
    return f"{column} IN ({', '.join(repr(c) for c in classes)})"
