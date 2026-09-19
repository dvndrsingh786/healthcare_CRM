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
