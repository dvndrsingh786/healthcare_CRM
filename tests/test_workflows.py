"""End-to-end workflows from the specification (section 8), through the public API only,
plus a check that application logs stay free of tokens and personal data."""
import logging

from app.logging_setup import JsonFormatter
from helpers import at, audit_events, login, make_app_user, make_worker, move_to_past, patient_body


def test_new_patient_intake(client, org_a, test_engine):
    """Create patient -> duplicate check -> consent/preferences -> assign staff -> audit events."""
    ops = org_a["ops"]["headers"]
    created = client.post("/api/v1/patients", headers=ops, json=patient_body(mrn="NF-5001", contact_by_sms=True))
    assert created.status_code == 201
    patient_id = created.json()["id"]
    duplicate = client.post("/api/v1/patients", headers=ops, json=patient_body())
    assert duplicate.json()["error"]["code"] == "POSSIBLE_DUPLICATE"

    consent = client.post(f"/api/v1/patients/{patient_id}/consents", headers=ops, json={
        "consent_type": "DATA_PROCESSING", "status": "GRANTED", "source": "PAPER_FORM", "policy_version": "v1"})
    assert consent.status_code == 201
    assigned = client.post(f"/api/v1/patients/{patient_id}/assignments", headers=ops, json={
        "staff_user_id": org_a["care"]["id"], "assignment_type": "PRIMARY"})
    assert assigned.status_code == 201
    caseload = client.get(f"/api/v1/staff/{org_a['care']['id']}/caseload", headers=org_a["care"]["headers"]).json()
    assert [c["patient_id"] for c in caseload["data"]] == [patient_id]

    actions = [e["action"] for e in audit_events(test_engine) if e["resource_id"] == patient_id]
    assert actions == ["patient.create", "consent.record", "assignment.create"]


def test_appointment_lifecycle_with_app_view_and_notification(client, org_a, test_engine, sent_messages):
    """Create -> notify/queue -> patient sees it in the app -> reschedule -> complete; history kept."""
    ops = org_a["ops"]["headers"]
    patient_id = client.post("/api/v1/patients", headers=ops, json=patient_body()).json()["id"]
    app_user = make_app_user(client, test_engine, org_a["id"], "maggie.app@northfield.example", patient_id)
    appointment = client.post("/api/v1/appointments", headers=ops, json={
        "patient_id": patient_id, "staff_user_id": org_a["care"]["id"], "starts_at": at(hours=24),
        "ends_at": at(hours=25), "appointment_type": "HOME_VISIT", "internal_note": "Parking at rear"}).json()

    client.post("/api/v1/notifications/process", headers=make_worker(client, org_a))
    assert [m.template_key for m in sent_messages] == ["appointment_booked"]

    in_app = client.get(f"/api/v1/app/appointments/{appointment['id']}", headers=app_user["headers"])
    assert in_app.status_code == 200 and "Parking" not in in_app.text

    client.post(f"/api/v1/appointments/{appointment['id']}/reschedule", headers=ops, json={
        "version": 1, "starts_at": at(hours=26), "ends_at": at(hours=27), "reason": "Traffic"})
    move_to_past(test_engine, appointment["id"])
    client.post(f"/api/v1/appointments/{appointment['id']}/complete", headers=org_a["ops"]["headers"])
    history = client.get(f"/api/v1/appointments/{appointment['id']}/history", headers=ops).json()
    assert [h["event"] for h in history] == ["CREATED", "RESCHEDULED", "COMPLETED"]
    assert client.get("/api/v1/app/appointments?when=past", headers=app_user["headers"]).json()["meta"]["total"] == 1


def test_follow_up_task(client, org_a, test_engine):
    """Staff creates a task -> owner sees it in their open list -> completion captures who/when -> audit."""
    patient_id = client.post("/api/v1/patients", headers=org_a["ops"]["headers"], json=patient_body()).json()["id"]
    care = org_a["care"]
    task = client.post("/api/v1/tasks", headers=org_a["coord"]["headers"], json={
        "title": "Chase GP letter", "patient_id": patient_id, "owner_user_id": care["id"],
        "due_at": at(hours=-1)}).json()
    mine = client.get("/api/v1/tasks?owner=me&status=open&overdue=true", headers=care["headers"]).json()["data"]
    assert [t["id"] for t in mine] == [task["id"]]
    done = client.post(f"/api/v1/tasks/{task['id']}/complete", headers=care["headers"]).json()
    assert done["completed_by"] == care["id"] and done["completed_at"]
    assert audit_events(test_engine, "task.complete")[0]["resource_id"] == task["id"]


def test_logs_contain_no_tokens_or_personal_data(client, org_a, caplog):
    formatter = JsonFormatter()
    with caplog.at_level(logging.INFO):
        tokens = login(client, org_a["ops"]["email"])
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        created = client.post("/api/v1/patients", headers=headers, json=patient_body(mrn="NF-7777"))
        client.get("/api/v1/patients?search=Okafor&page_size=5", headers=headers)
        client.post("/api/v1/patients", headers=headers, json=patient_body(date_of_birth="2999-01-01"))
        logging.getLogger("hcrm.test").info("oops", extra={"patient": {"email": "maggie@example.com",
                                                                        "date_of_birth": "1948-03-14"}})
    output = "\n".join(formatter.format(record) for record in caplog.records)
    assert created.status_code == 201 and '"request_id"' in output
    for secret in (tokens["access_token"], tokens["refresh_token"], "DemoPass123!", "maggie@example.com",
                   "1948-03-14", "NF-7777", "Okafor", "Elm Road"):
        assert secret not in output, secret
