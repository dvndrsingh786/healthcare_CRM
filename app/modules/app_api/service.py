"""Patient app queries and push-device registration.

Every query here starts from the caller's OWN patient record (find_own_patient), never from an
id in the request, and only returns records explicitly marked for the app. A guessed id of
another patient's appointment or document gives the same 404 as a random one.
"""
from sqlalchemy import text

from app.audit import record_event
from app.errors import not_found
from app.modules.appointments.service import APPOINTMENT_SELECT, serialize
from app.modules.patients.access import log_denied_access
from app.pagination import paginate
from app.security import hash_token

MAX_DEVICES_PER_USER = 10


# ---------- Appointments ----------

def list_own_appointments(db, patient_id, paging, when="upcoming"):
    condition = "ap.patient_id = :patient_id AND ap.app_visible"
    if when == "upcoming":
        condition += " AND ap.ends_at >= now()"
        order = "ap.starts_at ASC, ap.id ASC"
    else:
        condition += " AND ap.ends_at < now()"
        order = "ap.starts_at DESC, ap.id DESC"
    return paginate(db, f"{APPOINTMENT_SELECT} WHERE {condition} ORDER BY {order}",
                    f"SELECT count(*) FROM appointments ap WHERE {condition}",
                    {"patient_id": patient_id}, paging, serialize=serialize)


def get_own_appointment(db, principal, patient_id, appointment_id):
    row = db.execute(text(f"{APPOINTMENT_SELECT} WHERE ap.id = :id AND ap.patient_id = :patient_id "
                          "AND ap.app_visible"), {"id": appointment_id, "patient_id": patient_id}).mappings().first()
    if row is None:
        log_denied_access(db, principal, "appointment", appointment_id)
        raise not_found("Appointment")
    return serialize(row)


# ---------- Documents ----------

def list_own_documents(db, patient_id, paging):
    condition = "patient_id = :patient_id AND visibility = 'APP_VISIBLE' AND status = 'AVAILABLE'"
    return paginate(db, f"SELECT * FROM documents WHERE {condition} ORDER BY uploaded_at DESC, id DESC",
                    f"SELECT count(*) FROM documents WHERE {condition}", {"patient_id": patient_id}, paging)


# ---------- Push devices ----------

def register_device(db, principal, data):
    """Register (or refresh) this device's push token for the calling user. A token can belong to
    one user at a time: if the phone changed hands, the previous registration is revoked."""
    token_hash = hash_token(data.push_token)
    existing = db.execute(text("SELECT id, user_id FROM device_tokens WHERE token_hash = :h AND revoked_at IS NULL"),
                          {"h": token_hash}).mappings().first()
    if existing and str(existing["user_id"]) == str(principal["user_id"]):
        db.execute(text("UPDATE device_tokens SET last_seen_at = now(), platform = :platform, "
                        "device_name = :name WHERE id = :id"),
                   {"platform": data.platform, "name": data.device_name, "id": existing["id"]})
        return existing["id"]
    if existing:
        db.execute(text("UPDATE device_tokens SET revoked_at = now() WHERE id = :id"), {"id": existing["id"]})

    device_id = db.execute(
        text("""
            INSERT INTO device_tokens (organisation_id, user_id, platform, push_token, token_hash, device_name)
            VALUES (:org, :user_id, :platform, :token, :h, :name) RETURNING id
        """),
        {"org": principal["organisation_id"], "user_id": principal["user_id"], "platform": data.platform,
         "token": data.push_token, "h": token_hash, "name": data.device_name},
    ).scalar_one()
    # Keep only the most recent devices.
    db.execute(text("""
        UPDATE device_tokens SET revoked_at = now()
        WHERE user_id = :u AND revoked_at IS NULL AND id NOT IN (
            SELECT id FROM device_tokens WHERE user_id = :u AND revoked_at IS NULL
            ORDER BY last_seen_at DESC LIMIT :keep)
    """), {"u": principal["user_id"], "keep": MAX_DEVICES_PER_USER})
    record_event(db, principal, "device.register", "device", device_id, metadata={"platform": data.platform})
    return device_id


def list_devices(db, principal):
    rows = db.execute(text("SELECT * FROM device_tokens WHERE user_id = :u AND revoked_at IS NULL "
                           "ORDER BY last_seen_at DESC"), {"u": principal["user_id"]}).mappings()
    return [dict(row) for row in rows]


def get_device(db, device_id):
    return db.execute(text("SELECT * FROM device_tokens WHERE id = :id"), {"id": device_id}).mappings().one()


def revoke_device(db, principal, device_id):
    revoked = db.execute(text("UPDATE device_tokens SET revoked_at = now() WHERE id = :id AND user_id = :u "
                              "AND revoked_at IS NULL RETURNING id"),
                         {"id": device_id, "u": principal["user_id"]}).first()
    if revoked is None:
        raise not_found("Device")
    record_event(db, principal, "device.revoke", "device", device_id)
