"""Automated demo of the sprint's required workflows against a RUNNING API with seeded data.

    python migrate.py && python seed.py          (once, on an empty database)
    uvicorn app.main:app                          (in another terminal)
    python scripts/demo.py [http://127.0.0.1:8000]

Each step prints what it shows and fails loudly if the API does not behave as specified.
It creates a fresh demo patient every run, so it can be repeated.
"""
import hashlib
import os
import secrets
import string
import sys
from datetime import UTC, datetime, timedelta

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
PASSWORD = os.getenv("SEED_PASSWORD", "DemoPass123!")
PDF = b"%PDF-1.4\n% demo letter\n" + b"Referral letter text.\n" * 10 + b"%%EOF\n"

client = httpx.Client(base_url=BASE, timeout=30)
step_number = 0


def step(title):
    global step_number
    step_number += 1
    print(f"\n{step_number}. {title}")


def check(condition, message):
    if not condition:
        sys.exit(f"   FAILED: {message}")
    print(f"   ok  {message}")


def call(method, path, headers=None, expect=None, **kwargs):
    # Paths are relative to /api/v1, except links the API returns (they are already full paths).
    url = path if path.startswith("/api/") else f"/api/v1{path}"
    response = client.request(method, url, headers=headers, **kwargs)
    if expect is not None and response.status_code != expect:
        sys.exit(f"   FAILED: {method} {path} returned {response.status_code}, expected {expect}: {response.text}")
    return response


def login(email):
    tokens = call("POST", "/auth/login", json={"email": email, "password": PASSWORD}, expect=200).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def when(hours):
    return (datetime.now(UTC) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def main():
    step("Health, readiness and OpenAPI")
    check(call("GET", "/health/ready", expect=200).json()["status"] == "ready", "database reachable")
    check(client.get("/openapi.json").status_code == 200, "OpenAPI document at /openapi.json, Swagger UI at /docs")

    step("Different roles, different access")
    admin, ops = login("admin@northfield.example"), login("ops@northfield.example")
    nurse, coordinator = login("nurse@northfield.example"), login("coordinator@northfield.example")
    maggie = login("maggie@northfield.example")
    other_org = login("ops@southbank.example")
    nurse_id = call("GET", "/auth/me", headers=nurse, expect=200).json()["id"]
    check(call("GET", "/patients", headers=admin).status_code == 403, "System Admin has no clinical/patient access")
    check(call("GET", "/patients", headers=maggie).status_code == 403, "patient app token refused on CRM routes")
    nurse_sees = call("GET", "/patients", headers=nurse, expect=200).json()["meta"]["total"]
    ops_sees = call("GET", "/patients", headers=ops, expect=200).json()["meta"]["total"]
    check(nurse_sees < ops_sees, f"care staff see only assigned patients ({nurse_sees} of {ops_sees})")

    step("New patient intake: validation, duplicates, consent, assignment, audit")
    surname = "Demo" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
    body = {"legal_first_name": "Rosa", "legal_last_name": surname, "date_of_birth": "1950-05-05",
            "phone": "+44 7700 900111", "email": f"{surname.lower()}@example.com", "postcode": "LS2 7AB"}
    check(call("POST", "/patients", headers=ops, json={**body, "date_of_birth": "2999-01-01"}).status_code == 422,
          "future date of birth rejected")
    patient = call("POST", "/patients", headers=ops, json=body, expect=201).json()
    check(call("POST", "/patients", headers=ops, json=body).json()["error"]["code"] == "POSSIBLE_DUPLICATE",
          "same name + date of birth flagged as POSSIBLE_DUPLICATE")
    call("POST", f"/patients/{patient['id']}/consents", headers=ops, expect=201, json={
        "consent_type": "DATA_PROCESSING", "status": "GRANTED", "source": "PAPER_FORM", "policy_version": "v1"})
    call("POST", f"/patients/{patient['id']}/assignments", headers=ops, expect=201,
         json={"staff_user_id": nurse_id, "assignment_type": "PRIMARY"})
    check(call("GET", f"/patients/{patient['id']}", headers=nurse).status_code == 200,
          "assigned nurse can now see them")
    events = call("GET", f"/audit-events?resource_id={patient['id']}", headers=admin, expect=200).json()["data"]
    check({"patient.create", "consent.record", "assignment.create"} <= {e["action"] for e in events},
          "intake steps are in the audit log")

    step("Cross-user and cross-tenant access is denied")
    check(call("GET", f"/patients/{patient['id']}", headers=other_org).status_code == 404,
          "another organisation gets 404 for the patient id")
    check(call("GET", f"/patients/{patient['id']}", headers=maggie).status_code == 403,
          "a patient app user cannot open another patient's record")

    step("Appointment lifecycle")
    appointment = call("POST", "/appointments", headers=ops, expect=201, json={
        "patient_id": patient["id"], "staff_user_id": nurse_id, "starts_at": when(72), "ends_at": when(73),
        "timezone": "Europe/London", "appointment_type": "HOME_VISIT", "internal_note": "Staff only"}).json()
    url = f"/appointments/{appointment['id']}"
    call("POST", f"{url}/confirm", headers=ops, expect=200)
    call("POST", f"{url}/reschedule", headers=ops, expect=200, json={
        "version": 2, "starts_at": when(96), "ends_at": when(97), "reason": "Nurse on training"})
    bad = call("POST", f"{url}/complete", headers=nurse)
    check(bad.json()["error"]["code"] == "INVALID_TRANSITION", "cannot complete before it starts (INVALID_TRANSITION)")
    call("POST", f"{url}/cancel", headers=ops, expect=200, json={"reason": "Admitted to hospital"})
    history = [h["event"] for h in call("GET", f"{url}/history", headers=ops, expect=200).json()]
    check(history == ["CREATED", "CONFIRMED", "RESCHEDULED", "CANCELLED"], f"history kept: {history}")
    upcoming = call("GET", "/app/appointments", headers=maggie, expect=200).json()["data"]
    check(upcoming and all("internal_note" not in a for a in upcoming),
          "Maggie sees her own appointments in the app, without internal notes")

    step("Follow-up task")
    task = call("POST", "/tasks", headers=coordinator, expect=201, json={
        "title": "Call about new equipment", "patient_id": patient["id"], "owner_user_id": nurse_id,
        "due_at": when(-2)}).json()
    mine = call("GET", "/tasks?owner=me&status=open&overdue=true", headers=nurse, expect=200).json()["data"]
    check(task["id"] in [t["id"] for t in mine], "the owner sees it in their open/overdue list")
    done = call("POST", f"/tasks/{task['id']}/complete", headers=nurse, expect=200).json()
    check(done["completed_by"] == nurse_id and done["completed_at"], "completion records who and when")

    step("Restricted clinical note")
    note = call("POST", f"/patients/{patient['id']}/notes", headers=nurse, expect=201, json={
        "subject": "Skin check", "body": "Clinical observation.", "visibility": "CLINICAL"}).json()
    listed = call("GET", f"/patients/{patient['id']}/notes", headers=coordinator, expect=200).json()["data"]
    check(note["id"] not in [n["id"] for n in listed], "coordinator (support role) does not see it")
    check(call("GET", f"/notes/{note['id']}", headers=coordinator).status_code == 404, "direct access is 404")
    timeline = call("GET", f"/patients/{patient['id']}/timeline", headers=coordinator, expect=200).text
    check(note["id"] not in timeline, "and it is not on the coordinator's timeline")

    step("Consent history")
    call("POST", f"/patients/{patient['id']}/consents", headers=ops, expect=201, json={
        "consent_type": "DATA_PROCESSING", "status": "WITHDRAWN", "source": "STAFF_VERBAL", "policy_version": "v1"})
    history = call("GET", f"/patients/{patient['id']}/consents/history", headers=ops, expect=200).json()
    check([h["status"] for h in history] == ["WITHDRAWN", "GRANTED"], "the earlier GRANTED evidence is kept")

    step("Private document")
    intent = call("POST", f"/patients/{patient['id']}/documents", headers=ops, expect=201, json={
        "original_filename": "referral.pdf", "mime_type": "application/pdf", "size_bytes": len(PDF),
        "category": "REFERRAL"}).json()
    call("PUT", intent["upload_url"], content=PDF, headers={"Content-Type": "application/pdf"}, expect=204)
    document = call("POST", f"/documents/{intent['document']['id']}/confirm", headers=ops, expect=200, json={
        "checksum_sha256": hashlib.sha256(PDF).hexdigest()}).json()
    check(call("GET", f"/storage/download/{document['id']}").status_code == 403, "the id alone downloads nothing")
    link = call("POST", f"/documents/{document['id']}/download-link", headers=ops, expect=200).json()
    check(call("GET", link["download_url"]).content == PDF, f"signed link works until {link['expires_at']}")
    audited = call("GET", f"/audit-events?resource_id={document['id']}", headers=admin, expect=200).json()["data"]
    check("document.download" in {e["action"] for e in audited}, "the download is audited")

    step("Notification outbox with idempotency and retry")
    worker = call("POST", "/service-accounts", headers=admin, expect=201, json={
        "name": "demo-worker-" + secrets.token_hex(3), "role_keys": ["NOTIFICATION_WORKER"],
        "expires_in_days": 1}).json()
    key = {"Idempotency-Key": "demo-" + secrets.token_hex(8)}
    request = {"patient_id": patient["id"], "channel": "EMAIL", "template_key": "appointment_reminder"}
    first = call("POST", "/notifications", headers={**ops, **key}, json=request, expect=201).json()
    again = call("POST", "/notifications", headers={**ops, **key}, json=request, expect=200).json()
    check(first["id"] == again["id"], "same Idempotency-Key: one message, not two")
    call("POST", "/notifications/process", headers={"X-API-Key": worker["key"]["api_key"]}, expect=200)
    status = call("GET", f"/notifications/{first['id']}", headers=ops, expect=200).json()
    check(status["status"] == "SENT", f"sent by the worker after {status['attempts']} attempt(s)")

    step("Dashboard")
    summary = call("GET", "/summary", headers=nurse, expect=200).json()
    check(summary["tasks"] is not None, f"nurse summary: {summary['appointments']} / {summary['tasks']}")

    print("\nAll demo steps passed.")


if __name__ == "__main__":
    main()
