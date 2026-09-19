"""Consent evidence. Every change is a NEW append-only row that points to the one it replaces
(supersedes_id); nothing is overwritten, so the full history stays traceable. The current state
of a consent type is its latest row. Each change records who (captured_by + type), how (source),
when (captured_at, recorded_at) and against which wording (policy_version).
"""
from datetime import UTC, datetime

from sqlalchemy import text

from app.audit import record_event
from app.errors import invalid
from app.modules.consents.schemas import APP_MANAGED_TYPES
from app.modules.patients.access import check_patient_link, find_patient

CONSENT_COLUMNS = """
    c.*, CASE WHEN c.expires_at IS NOT NULL AND c.expires_at <= now() THEN 'EXPIRED'
              ELSE c.status END AS effective_status
"""
CONSENT_SELECT = f"SELECT {CONSENT_COLUMNS} FROM consent_records c"


def current_consents(db, patient_id):
    # DISTINCT ON keeps the first row per type in the ORDER BY, i.e. the newest one.
    rows = db.execute(text(f"SELECT DISTINCT ON (c.consent_type) {CONSENT_COLUMNS} FROM consent_records c "
                           "WHERE c.patient_id = :patient_id ORDER BY c.consent_type, c.recorded_at DESC"),
                      {"patient_id": patient_id}).mappings()
    return [dict(row) for row in rows]


def current_consent(db, patient_id, consent_type):
    return db.execute(text(f"{CONSENT_SELECT} WHERE c.patient_id = :p AND c.consent_type = :t "
                           "ORDER BY c.recorded_at DESC LIMIT 1"),
                      {"p": patient_id, "t": consent_type}).mappings().first()


def consent_history(db, patient_id, consent_type=None):
    sql = f"{CONSENT_SELECT} WHERE c.patient_id = :p"
    params = {"p": patient_id}
    if consent_type:
        sql += " AND c.consent_type = :t"
        params["t"] = consent_type
    return [dict(row) for row in db.execute(text(sql + " ORDER BY c.recorded_at DESC"), params).mappings()]


def insert_consent(db, principal, patient_id, values):
    # Lock the patient row so two changes to the same patient are recorded one after the other.
    db.execute(text("SELECT 1 FROM patients WHERE id = :id FOR UPDATE"), {"id": patient_id})
    previous = current_consent(db, patient_id, values["consent_type"])
    consent_id = db.execute(
        text("""
            INSERT INTO consent_records (organisation_id, patient_id, consent_type, status, source, policy_version,
                                         captured_at, expires_at, captured_by, captured_by_type,
                                         evidence_document_id, note, supersedes_id)
            VALUES (:org, :patient_id, :consent_type, :status, :source, :policy_version,
                    coalesce(:captured_at, now()), :expires_at, :by, :by_type, :evidence_document_id, :note,
                    :supersedes_id)
            RETURNING id
        """),
        {"org": principal["organisation_id"], "patient_id": patient_id, "by": principal["user_id"],
         "by_type": "PATIENT" if principal["user_type"] == "PATIENT" else "STAFF",
         "supersedes_id": previous["id"] if previous else None,
         "captured_at": None, "expires_at": None, "evidence_document_id": None, "note": None, **values},
    ).scalar_one()
    # Types and statuses only: consent notes can contain personal details.
    record_event(db, principal, "consent.record", "patient", patient_id, changed_fields=["consent"],
                 metadata={"consent_id": str(consent_id), "consent_type": values["consent_type"],
                           "status": values["status"], "source": values["source"],
                           "previous_status": previous["status"] if previous else None})
    return consent_id


def record_staff_consent(db, principal, patient_id, data):
    patient = check_patient_link(db, principal, patient_id)
    if data.captured_at and data.captured_at > datetime.now(UTC):
        raise invalid("captured_at cannot be in the future.", field="captured_at")
    if data.expires_at and data.expires_at <= (data.captured_at or datetime.now(UTC)):
        raise invalid("expires_at must be after captured_at.", field="expires_at")
    if data.evidence_document_id:
        belongs = db.execute(
            text("SELECT 1 FROM documents WHERE id = :id AND patient_id = :p AND status = 'AVAILABLE'"),
            {"id": data.evidence_document_id, "p": patient["id"]}).first()
        if not belongs:
            raise invalid("The evidence document must be an available document of this patient.",
                          field="evidence_document_id")
    return insert_consent(db, principal, patient_id, data.model_dump())


def list_current(db, principal, patient_id):
    find_patient(db, principal, patient_id)
    return current_consents(db, patient_id)


def list_history(db, principal, patient_id, consent_type=None):
    find_patient(db, principal, patient_id)
    return consent_history(db, patient_id, consent_type)


def get_consent(db, consent_id):
    return db.execute(text(f"{CONSENT_SELECT} WHERE c.id = :id"), {"id": consent_id}).mappings().one()


# ---------- Patient app ----------

def app_view(row):
    return dict(row, changeable_in_app=row["consent_type"] in APP_MANAGED_TYPES)


def app_change_consent(db, principal, patient_id, data):
    """Returns (consent_row, created). Re-sending the current state is a no-op, so a retried
    app submission never creates duplicate evidence."""
    current = current_consent(db, patient_id, data.consent_type)
    if current and current["effective_status"] == data.status and current["policy_version"] == data.policy_version:
        return current, False
    consent_id = insert_consent(db, principal, patient_id, {
        "consent_type": data.consent_type, "status": data.status, "source": "APP",
        "policy_version": data.policy_version})
    return get_consent(db, consent_id), True
