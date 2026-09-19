"""Small functions that many tests use."""
from sqlalchemy import text

from app.modules.organisations.service import create_organisation
from app.modules.users.service import create_user

PASSWORD = "DemoPass123!"

STAFF_ROLES = {
    "sysadmin": "SYSTEM_ADMIN",
    "ops": "OPS_ADMIN",
    "care": "CARE_STAFF",
    "care2": "CARE_STAFF",
    "coord": "COORDINATOR",
}


def login(client, email, password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def make_organisation(client, engine, slug):
    """An organisation with one staff user per role, all logged in.

    Returns {"id": ..., "sysadmin": {"id", "email", "headers"}, "ops": {...}, ...}
    """
    with engine.begin() as db:
        org_id = create_organisation(db, f"{slug.title()} Health", slug)
        users = {}
        for key, role in STAFF_ROLES.items():
            email = f"{key}@{slug}.example"
            user_id = create_user(db, org_id, email, "STAFF", password=PASSWORD, role_keys=[role],
                                  profile={"display_name": f"{key.title()} {slug.title()}"})
            users[key] = {"id": str(user_id), "email": email}

    org = {"id": str(org_id), "slug": slug}
    for key, user in users.items():
        user["headers"] = auth(login(client, user["email"]))
        org[key] = user
    return org


def make_app_user(client, engine, org_id, email, patient_id=None):
    """A patient app account. Linking it to a patient record is done by the caller when needed."""
    with engine.begin() as db:
        user_id = create_user(db, org_id, email, "PATIENT", password=PASSWORD, role_keys=["APP_USER"])
        if patient_id is not None:
            db.execute(text("UPDATE patients SET app_user_id = :u WHERE id = :p"), {"u": user_id, "p": patient_id})
    return {"id": str(user_id), "email": email, "headers": auth(login(client, email))}


def audit_events(engine, action=None):
    sql = "SELECT * FROM audit_events"
    params = {}
    if action:
        sql += " WHERE action = :action"
        params["action"] = action
    with engine.connect() as db:
        return [dict(row) for row in db.execute(text(sql + " ORDER BY occurred_at"), params).mappings()]


def patient_body(**overrides):
    body = {"legal_first_name": "Margaret", "legal_last_name": "Okafor", "date_of_birth": "1948-03-14",
            "phone": "+44 7700 900456", "email": "maggie@example.com", "address_line1": "12 Elm Road",
            "city": "Leeds", "postcode": "LS1 4AB"}
    body.update(overrides)
    return body


def make_patient(client, org, **overrides):
    """Created by the org's Ops Admin. Returns the patient JSON."""
    response = client.post("/api/v1/patients", headers=org["ops"]["headers"], json=patient_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def at(hours=0, days=0, minutes=0):
    """An ISO time relative to now, with an explicit UTC offset."""
    from datetime import UTC, datetime, timedelta
    return (datetime.now(UTC) + timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


def make_appointment(client, org, patient_id, staff_key="care", start_hours=24, length_minutes=45, headers=None,
                     **overrides):
    body = {"patient_id": patient_id, "staff_user_id": org[staff_key]["id"] if staff_key else None,
            "starts_at": at(hours=start_hours), "ends_at": at(hours=start_hours, minutes=length_minutes),
            "appointment_type": "HOME_VISIT", "location": "Patient's home",
            "patient_instructions": "Have your medication list ready.", "internal_note": "Staff only: dog on site"}
    body.update(overrides)
    response = client.post("/api/v1/appointments", headers=headers or org["ops"]["headers"], json=body)
    assert response.status_code == 201, response.text
    return response.json()


def move_to_past(engine, appointment_id, hours_ago=2):
    """Tests only: pretend an appointment already started (the API refuses to book in the past)."""
    with engine.begin() as db:
        db.execute(text("UPDATE appointments SET starts_at = now() - make_interval(hours => :h), "
                        "ends_at = now() - make_interval(hours => :h) + interval '30 minutes' WHERE id = :id"),
                   {"h": hours_ago, "id": appointment_id})


def assign_patient(client, org, patient_id, staff_key="care", assignment_type="PRIMARY"):
    response = client.post(f"/api/v1/patients/{patient_id}/assignments", headers=org["ops"]["headers"],
                           json={"staff_user_id": org[staff_key]["id"], "assignment_type": assignment_type})
    assert response.status_code == 201, response.text


def make_worker(client, org):
    """A NOTIFICATION_WORKER service account. Returns headers with its API key."""
    response = client.post("/api/v1/service-accounts", headers=org["sysadmin"]["headers"], json={
        "name": "outbox-worker", "role_keys": ["NOTIFICATION_WORKER"], "expires_in_days": 30})
    assert response.status_code == 201, response.text
    return {"X-API-Key": response.json()["key"]["api_key"]}


# ---------- Documents ----------

PDF = b"%PDF-1.7\n" + b"Discharge summary for the patient.\n" * 20 + b"%%EOF"


def start_upload(client, headers, patient_id, content=PDF, **body):
    response = client.post(f"/api/v1/patients/{patient_id}/documents", headers=headers, json={
        "original_filename": "discharge.pdf", "mime_type": "application/pdf", "size_bytes": len(content),
        "category": "LETTER", **body})
    return response


def upload(client, headers, patient_id, content=PDF, content_type="application/pdf", **body):
    intent = start_upload(client, headers, patient_id, content, **body)
    assert intent.status_code == 201, intent.text
    put = client.put(intent.json()["upload_url"], content=content, headers={"Content-Type": content_type})
    assert put.status_code == 204, put.text
    return intent.json()["document"]["id"]


def upload_and_confirm(client, headers, patient_id, **body):
    import hashlib

    document_id = upload(client, headers, patient_id, **body)
    confirmed = client.post(f"/api/v1/documents/{document_id}/confirm", headers=headers,
                            json={"checksum_sha256": hashlib.sha256(PDF).hexdigest()})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def api_routes(app):
    """Every APIRoute of the app. Newer FastAPI versions wrap included routers, so app.routes alone
    does not list them; we walk into each included router."""
    from fastapi.routing import APIRoute

    def walk(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from walk(route.original_router.routes)
            elif hasattr(route, "routes"):
                yield from walk(route.routes)

    return list(walk(app.routes))
