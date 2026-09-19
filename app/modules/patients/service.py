"""Patients, emergency contacts and patient app accounts."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.audit import changed_fields, record_event
from app.errors import ApiError, conflict, invalid, not_found
from app.modules.patients.access import find_patient, patient_scope
from app.modules.patients.schemas import SENSITIVE_FIELDS
from app.pagination import like_pattern, order_by, paginate
from app.security import has

PUBLIC_FIELDS = (
    "id", "legal_first_name", "legal_last_name", "preferred_name", "email", "phone", "preferred_language",
    "contact_by_email", "contact_by_sms", "contact_by_push", "status", "version", "created_at", "updated_at",
    "archived_at",
)

EDITABLE_COLUMNS = {
    "legal_first_name", "legal_last_name", "preferred_name", "date_of_birth", "mrn", "email", "phone",
    "address_line1", "address_line2", "city", "postcode", "country", "preferred_language",
    "contact_by_email", "contact_by_sms", "contact_by_push", "status",
}


def serialize(principal, row):
    """Allow-list serializer: build the response field by field, never return the row itself."""
    show_sensitive = has(principal, "patients:read_sensitive")
    out = {field: row[field] for field in PUBLIC_FIELDS}
    out["has_app_account"] = row["app_user_id"] is not None
    out["sensitive_fields_hidden"] = not show_sensitive
    for field in SENSITIVE_FIELDS:
        out[field] = row[field] if show_sensitive else None
    return out


def raise_on_unique_violation(error):
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "uq_patients_org_mrn":
        raise conflict("Another patient already has this MRN.", code="DUPLICATE_IDENTIFIER") from error
    raise error


# ---------- Patients ----------

def create_patient(db, principal, data):
    patient = data.model_dump(exclude={"emergency_contacts", "confirm_not_duplicate"})
    org = principal["organisation_id"]

    if patient["mrn"] is not None:
        taken = db.execute(text("SELECT 1 FROM patients WHERE organisation_id = :org AND mrn = :mrn"),
                           {"org": org, "mrn": patient["mrn"]}).first()
        if taken:
            raise conflict("Another patient already has this MRN.", code="DUPLICATE_IDENTIFIER")

    if not data.confirm_not_duplicate:
        possible_duplicate = db.execute(
            text("""
                SELECT 1 FROM patients
                WHERE organisation_id = :org AND lower(legal_last_name) = lower(:last)
                  AND lower(legal_first_name) = lower(:first) AND date_of_birth = :dob
            """),
            {"org": org, "last": patient["legal_last_name"], "first": patient["legal_first_name"],
             "dob": patient["date_of_birth"]},
        ).first()
        if possible_duplicate:
            # No id or details of the other record: the caller may not be allowed to see it.
            raise conflict("A patient with the same name and date of birth already exists. "
                           "Check before creating another; resend with confirm_not_duplicate=true if it is "
                           "a different person.", code="POSSIBLE_DUPLICATE")

    columns = list(patient)
    try:
        patient_id = db.execute(
            text(f"""
                INSERT INTO patients (organisation_id, created_by, updated_by, {', '.join(columns)})
                VALUES (:org, :by, :by, {', '.join(':' + c for c in columns)})
                RETURNING id
            """),
            dict(patient, org=org, by=principal["user_id"]),
        ).scalar_one()
    except IntegrityError as error:
        # Two requests with the same MRN at the same moment: the unique index decides.
        raise_on_unique_violation(error)

    for contact in data.emergency_contacts:
        insert_contact(db, principal, patient_id, contact.model_dump())

    record_event(db, principal, "patient.create", "patient", patient_id,
                 changed_fields=[c for c in columns if patient[c] is not None],
                 metadata={"emergency_contacts": len(data.emergency_contacts),
                           "duplicate_override": data.confirm_not_duplicate})
    return patient_id


def get_patient(db, principal, patient_id, audit=True):
    row = find_patient(db, principal, patient_id)
    if audit:
        # Viewing a full patient record is a sensitive read, so it is audited.
        record_event(db, principal, "patient.read", "patient", patient_id,
                     metadata={"sensitive": has(principal, "patients:read_sensitive")})
    return serialize(principal, row)


def list_patients(db, principal, paging, search=None, status=None, assigned_staff_id=None, team_id=None,
                  sort=None):
    condition, params = patient_scope(principal)
    conditions = [condition]
    if status:
        conditions.append("p.status = :status")
        params["status"] = status
    else:
        conditions.append("p.status <> 'ARCHIVED'")
    if search:
        searchable = ["lower(p.legal_first_name || ' ' || p.legal_last_name || ' ' || coalesce(p.preferred_name, '')) "
                      "LIKE lower(:search)", "lower(p.email) LIKE lower(:search)", "p.phone LIKE :search"]
        if has(principal, "patients:read_sensitive"):
            searchable.append("p.mrn ILIKE :search")
        conditions.append("(" + " OR ".join(searchable) + ")")
        params["search"] = like_pattern(search)
    if assigned_staff_id:
        conditions.append("EXISTS (SELECT 1 FROM patient_assignments a WHERE a.patient_id = p.id AND a.active "
                          "AND a.staff_user_id = :assigned_staff_id)")
        params["assigned_staff_id"] = assigned_staff_id
    if team_id:
        conditions.append("EXISTS (SELECT 1 FROM patient_assignments a WHERE a.patient_id = p.id AND a.active "
                          "AND a.team_id = :team_id)")
        params["team_id"] = team_id

    sortable = {"updated_at": "p.updated_at", "created_at": "p.created_at", "legal_last_name": "p.legal_last_name"}
    if has(principal, "patients:read_sensitive"):
        sortable["date_of_birth"] = "p.date_of_birth"
    where = " AND ".join(conditions)
    return paginate(
        db,
        f"SELECT p.* FROM patients p WHERE {where} {order_by(sort, sortable, '-updated_at', 'p.id')}",
        f"SELECT count(*) FROM patients p WHERE {where}",
        params, paging, serialize=lambda row: serialize(principal, row),
    )


def update_patient(db, principal, patient_id, changes):
    expected_version = changes.pop("version")
    old = find_patient(db, principal, patient_id, lock=True)
    if old["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Archived patients cannot be edited. Restore the patient first.")
    if old["version"] != expected_version:
        raise conflict("This patient was changed by someone else. Reload it and try again.", code="VERSION_CONFLICT")

    changes = {column: value for column, value in changes.items() if column in EDITABLE_COLUMNS}
    changed = changed_fields(old, changes)
    if not changed:
        return
    sets = ", ".join(f"{column} = :{column}" for column in changed)
    try:
        db.execute(
            text(f"UPDATE patients SET {sets}, version = version + 1, updated_by = :by WHERE id = :id"),
            dict({c: changes[c] for c in changed}, by=principal["user_id"], id=patient_id),
        )
    except IntegrityError as error:
        raise_on_unique_violation(error)
    record_event(db, principal, "patient.update", "patient", patient_id, changed_fields=changed)


def archive_patient(db, principal, patient_id, reason):
    patient = find_patient(db, principal, patient_id, lock=True)
    if patient["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "The patient is already archived.")
    # Archive, never hard-delete: the health record must be kept under the retention policy.
    db.execute(
        text("""UPDATE patients SET status = 'ARCHIVED', archived_at = now(), archived_reason = :reason,
                version = version + 1, updated_by = :by WHERE id = :id"""),
        {"reason": reason, "by": principal["user_id"], "id": patient_id},
    )
    # The patient's app account stops working too.
    if patient["app_user_id"]:
        db.execute(text("UPDATE users SET status = 'INACTIVE' WHERE id = :id"), {"id": patient["app_user_id"]})
        db.execute(text("UPDATE sessions SET revoked_at = now(), revoked_reason = 'patient_archived' "
                        "WHERE user_id = :id AND revoked_at IS NULL"), {"id": patient["app_user_id"]})
    record_event(db, principal, "patient.archive", "patient", patient_id, changed_fields=["status"])


def restore_patient(db, principal, patient_id):
    patient = find_patient(db, principal, patient_id, lock=True)
    if patient["status"] != "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Only archived patients can be restored.")
    db.execute(
        text("""UPDATE patients SET status = 'ACTIVE', archived_at = NULL, archived_reason = NULL,
                version = version + 1, updated_by = :by WHERE id = :id"""),
        {"by": principal["user_id"], "id": patient_id},
    )
    record_event(db, principal, "patient.restore", "patient", patient_id, changed_fields=["status"])


# ---------- Emergency contacts ----------

CONTACT_COLUMNS = ("name", "relationship", "phone", "email", "priority", "is_next_of_kin")


def insert_contact(db, principal, patient_id, contact):
    return db.execute(
        text("""
            INSERT INTO emergency_contacts (organisation_id, patient_id, name, relationship, phone, email,
                                            priority, is_next_of_kin, created_by, updated_by)
            VALUES (:org, :patient_id, :name, :relationship, :phone, :email, :priority, :is_next_of_kin, :by, :by)
            RETURNING id
        """),
        dict(contact, org=principal["organisation_id"], patient_id=patient_id, by=principal["user_id"]),
    ).scalar_one()


def list_contacts(db, principal, patient_id):
    find_patient(db, principal, patient_id)
    rows = db.execute(
        text("SELECT * FROM emergency_contacts WHERE patient_id = :id ORDER BY priority, created_at"),
        {"id": patient_id},
    ).mappings()
    return [dict(row) for row in rows]


def find_contact(db, principal, patient_id, contact_id):
    find_patient(db, principal, patient_id)
    contact = db.execute(
        text("SELECT * FROM emergency_contacts WHERE id = :id AND patient_id = :patient_id FOR UPDATE"),
        {"id": contact_id, "patient_id": patient_id},
    ).mappings().first()
    if contact is None:
        raise not_found("Emergency contact")
    return contact


def add_contact(db, principal, patient_id, contact):
    find_patient(db, principal, patient_id)
    contact_id = insert_contact(db, principal, patient_id, contact)
    record_event(db, principal, "emergency_contact.create", "patient", patient_id,
                 metadata={"emergency_contact_id": str(contact_id)})
    return db.execute(text("SELECT * FROM emergency_contacts WHERE id = :id"), {"id": contact_id}).mappings().one()


def update_contact(db, principal, patient_id, contact_id, changes):
    old = find_contact(db, principal, patient_id, contact_id)
    changed = changed_fields(old, changes)
    merged = {**{c: old[c] for c in CONTACT_COLUMNS}, **changes}
    if merged["phone"] is None and merged["email"] is None:
        raise invalid("An emergency contact needs a phone number or an email address.")
    if changed:
        sets = ", ".join(f"{column} = :{column}" for column in changed)
        db.execute(text(f"UPDATE emergency_contacts SET {sets}, updated_by = :by WHERE id = :id"),
                   dict({c: changes[c] for c in changed}, by=principal["user_id"], id=contact_id))
    record_event(db, principal, "emergency_contact.update", "patient", patient_id, changed_fields=changed,
                 metadata={"emergency_contact_id": str(contact_id)})
    return db.execute(text("SELECT * FROM emergency_contacts WHERE id = :id"), {"id": contact_id}).mappings().one()


def delete_contact(db, principal, patient_id, contact_id):
    find_contact(db, principal, patient_id, contact_id)
    db.execute(text("DELETE FROM emergency_contacts WHERE id = :id"), {"id": contact_id})
    record_event(db, principal, "emergency_contact.delete", "patient", patient_id,
                 metadata={"emergency_contact_id": str(contact_id)})


# ---------- App account ----------

def create_app_account(db, principal, patient_id, email):
    from app.modules.auth.service import send_password_reset
    from app.modules.users.service import create_user

    patient = find_patient(db, principal, patient_id, lock=True)
    if patient["status"] != "ACTIVE":
        raise ApiError(409, "INVALID_STATE", "Only active patients can get an app account.")
    if patient["app_user_id"] is not None:
        raise conflict("This patient already has an app account.", code="APP_ACCOUNT_EXISTS")

    user_id = create_user(db, principal["organisation_id"], email, "PATIENT", role_keys=["APP_USER"],
                          created_by=principal["user_id"])
    db.execute(text("UPDATE patients SET app_user_id = :user_id, version = version + 1, updated_by = :by "
                    "WHERE id = :id"), {"user_id": user_id, "by": principal["user_id"], "id": patient_id})
    # The patient sets their own password with a one-time code.
    send_password_reset(db, user_id, email, template_key="account_invite")
    record_event(db, principal, "patient.app_account_create", "patient", patient_id,
                 metadata={"app_user_id": str(user_id)})


# ---------- Patient app: own profile ----------

APP_EDITABLE_COLUMNS = {"preferred_name", "phone", "preferred_language", "contact_by_email", "contact_by_sms",
                        "contact_by_push"}


def find_own_patient(db, principal, lock=False):
    """The patient record linked to the calling app account. There is no patient id in the URL,
    so an app user can never ask for someone else's record."""
    row = db.execute(
        text("SELECT * FROM patients WHERE app_user_id = :user_id AND organisation_id = :org "
             "AND status <> 'ARCHIVED'" + (" FOR UPDATE" if lock else "")),
        {"user_id": principal["user_id"], "org": principal["organisation_id"]},
    ).mappings().first()
    if row is None:
        raise not_found("Patient profile")
    return row


def update_own_profile(db, principal, changes):
    old = find_own_patient(db, principal, lock=True)
    changes = {column: value for column, value in changes.items() if column in APP_EDITABLE_COLUMNS}
    changed = changed_fields(old, changes)
    if changed:
        sets = ", ".join(f"{column} = :{column}" for column in changed)
        db.execute(
            text(f"UPDATE patients SET {sets}, version = version + 1, updated_by = :by WHERE id = :id"),
            dict({c: changes[c] for c in changed}, by=principal["user_id"], id=old["id"]),
        )
        record_event(db, principal, "patient.self_update", "patient", old["id"], changed_fields=changed)
    return find_own_patient(db, principal)
