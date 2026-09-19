"""The patient app boundary: own data only, app-safe fields, consents, documents and devices."""
from uuid import uuid4

from helpers import (
    api_routes,
    assign_patient,
    audit_events,
    make_app_user,
    make_appointment,
    make_patient,
    make_worker,
    move_to_past,
    upload_and_confirm,
)


def two_patients(client, org, engine):
    alice = make_patient(client, org, legal_first_name="Alice", legal_last_name="Able", email="alice@example.com")
    bob = make_patient(client, org, legal_first_name="Bob", legal_last_name="Baker", email="bob@example.com")
    alice_app = make_app_user(client, engine, org["id"], "alice@northfield.example", alice["id"])
    bob_app = make_app_user(client, engine, org["id"], "bob@northfield.example", bob["id"])
    return alice, bob, alice_app["headers"], bob_app["headers"]


def test_app_user_sees_only_own_app_visible_appointments(client, org_a, test_engine):
    alice, bob, alice_h, _ = two_patients(client, org_a, test_engine)
    upcoming = make_appointment(client, org_a, alice["id"], start_hours=24)
    crm_only = make_appointment(client, org_a, alice["id"], staff_key="care2", start_hours=30, app_visible=False)
    past = make_appointment(client, org_a, alice["id"], staff_key="coord", start_hours=40)
    move_to_past(test_engine, past["id"], hours_ago=48)
    bobs = make_appointment(client, org_a, bob["id"], staff_key="ops", start_hours=26)

    listed = client.get("/api/v1/app/appointments", headers=alice_h).json()
    assert [a["id"] for a in listed["data"]] == [upcoming["id"]]
    shown = listed["data"][0]
    assert shown["patient_instructions"] == "Have your medication list ready."
    for internal in ("internal_note", "staff_user_id", "patient_id", "version", "created_by"):
        assert internal not in shown
    assert "dog on site" not in client.get("/api/v1/app/appointments", headers=alice_h).text
    assert [a["id"] for a in client.get("/api/v1/app/appointments?when=past", headers=alice_h).json()["data"]] == [
        past["id"]]

    # Another patient's appointment, a CRM-only one and a random id all look the same: 404.
    responses = [client.get(f"/api/v1/app/appointments/{i}", headers=alice_h)
                 for i in (bobs["id"], crm_only["id"], uuid4())]
    assert {r.status_code for r in responses} == {404}
    assert len({r.json()["error"]["message"] for r in responses}) == 1
    assert any(e["resource_id"] == bobs["id"] for e in audit_events(test_engine, "access.denied"))


def test_app_user_cannot_reach_crm_or_another_patient(client, org_a, test_engine):
    """Mandatory scenario: app user A cannot retrieve or infer patient/app user B by guessed UUID."""
    alice, bob, alice_h, bob_h = two_patients(client, org_a, test_engine)
    for url in (f"/api/v1/patients/{bob['id']}", f"/api/v1/patients/{bob['id']}/notes",
                f"/api/v1/patients/{bob['id']}/timeline", "/api/v1/appointments", "/api/v1/tasks",
                f"/api/v1/users/{org_a['care']['id']}"):
        assert client.get(url, headers=alice_h).status_code == 403
    # The app has no endpoint that takes a patient or user id at all.
    from app.main import app
    app_paths = [route.path for route in api_routes(app) if route.path.startswith("/api/v1/app/")]
    assert app_paths and not any("patient_id" in path or "user_id" in path for path in app_paths)
    assert client.get("/api/v1/app/profile", headers=bob_h).json()["legal_first_name"] == "Bob"
    # Staff tokens cannot use app routes either.
    assert client.get("/api/v1/app/appointments", headers=org_a["ops"]["headers"]).status_code == 403


def test_messages_are_only_app_visible_notes(client, org_a, test_engine):
    alice, _, alice_h, bob_h = two_patients(client, org_a, test_engine)
    assign_patient(client, org_a, alice["id"])
    care = org_a["care"]["headers"]
    for visibility, subject in (("APP_VISIBLE", "Your next visit"), ("INTERNAL", "Team note"),
                                ("CLINICAL", "Clinical obs")):
        client.post(f"/api/v1/patients/{alice['id']}/notes", headers=care,
                    json={"subject": subject, "body": f"{subject} body", "visibility": visibility})
    messages = client.get("/api/v1/app/messages", headers=alice_h).json()["data"]
    assert [m["subject"] for m in messages] == ["Your next visit"]
    assert messages[0]["author_display_name"] == "Care Northfield"
    assert client.get("/api/v1/app/messages", headers=bob_h).json()["data"] == []
    queued = client.get(f"/api/v1/notifications?patient_id={alice['id']}", headers=org_a["ops"]["headers"]).json()
    assert [n["template_key"] for n in queued["data"]] == ["new_message"]


def test_app_consent_changes_keep_history(client, org_a, test_engine):
    alice, _, alice_h, _ = two_patients(client, org_a, test_engine)
    body = {"consent_type": "MARKETING_SMS", "status": "GRANTED", "policy_version": "comms-2026.1"}
    first = client.post("/api/v1/app/consents", headers=alice_h, json=body)
    assert first.status_code == 201 and first.json()["changeable_in_app"] is True
    # A retried submission records nothing new.
    assert client.post("/api/v1/app/consents", headers=alice_h, json=body).status_code == 200
    client.post("/api/v1/app/consents", headers=alice_h, json={**body, "status": "WITHDRAWN"})
    # Consents that staff must record cannot be changed from the app.
    assert client.post("/api/v1/app/consents", headers=alice_h, json={
        "consent_type": "DATA_PROCESSING", "status": "WITHDRAWN", "policy_version": "v1"}).status_code == 422

    current = client.get("/api/v1/app/consents", headers=alice_h).json()
    assert [(c["consent_type"], c["status"], c["source"]) for c in current] == [("MARKETING_SMS", "WITHDRAWN", "APP")]
    history = client.get(f"/api/v1/patients/{alice['id']}/consents/history",
                         headers=org_a["ops"]["headers"]).json()
    assert [(h["status"], h["captured_by_type"]) for h in history] == [("WITHDRAWN", "PATIENT"),
                                                                      ("GRANTED", "PATIENT")]
    assert len(audit_events(test_engine, "consent.record")) == 2


def test_app_documents(client, org_a, test_engine):
    alice, bob, alice_h, bob_h = two_patients(client, org_a, test_engine)
    ops = org_a["ops"]["headers"]
    shared = upload_and_confirm(client, ops, alice["id"], visibility="APP_VISIBLE", title="Care plan")
    internal = upload_and_confirm(client, ops, alice["id"], visibility="INTERNAL")
    bobs = upload_and_confirm(client, ops, bob["id"], visibility="APP_VISIBLE")

    listed = client.get("/api/v1/app/documents", headers=alice_h).json()["data"]
    assert [d["id"] for d in listed] == [shared["id"]]
    assert "checksum_sha256" not in listed[0] and "visibility" not in listed[0]

    link = client.post(f"/api/v1/app/documents/{shared['id']}/download-link", headers=alice_h)
    assert link.status_code == 200
    assert client.get(link.json()["download_url"]).content.startswith(b"%PDF-")
    for other in (internal["id"], bobs["id"]):
        assert client.post(f"/api/v1/app/documents/{other}/download-link", headers=alice_h).status_code == 404
    # A CRM link for Bob's document is useless to Alice, and Alice's link stops once she loses access.
    alice_link = client.post(f"/api/v1/app/documents/{shared['id']}/download-link", headers=alice_h).json()
    client.post(f"/api/v1/documents/{shared['id']}/archive", headers=ops, json={"reason": "Replaced"})
    assert client.get(alice_link["download_url"]).status_code == 404
    assert client.get("/api/v1/app/documents", headers=bob_h).json()["meta"]["total"] == 1


def test_push_devices(client, org_a, test_engine, sent_messages):
    alice, bob, alice_h, bob_h = two_patients(client, org_a, test_engine)
    device = {"platform": "IOS", "push_token": "apns-token-0123456789abcdef", "device_name": "Alice's phone"}
    registered = client.post("/api/v1/app/devices", headers=alice_h, json=device)
    assert registered.status_code == 201 and "push_token" not in registered.json()
    again = client.post("/api/v1/app/devices", headers=alice_h, json=device)
    assert again.json()["id"] == registered.json()["id"]

    # Booking an appointment now also goes to the phone (push is on by default).
    make_appointment(client, org_a, alice["id"])
    client.post("/api/v1/notifications/process", headers=make_worker(client, org_a))
    pushed = [m for m in sent_messages if m.channel == "PUSH"]
    assert [m.to for m in pushed] == ["apns-token-0123456789abcdef"]
    assert "Alice" not in pushed[0].body

    # The phone changes hands: Bob registers the same token and Alice's registration is revoked.
    client.post("/api/v1/app/devices", headers=bob_h, json=device)
    assert client.get("/api/v1/app/devices", headers=alice_h).json() == []
    bob_device = client.get("/api/v1/app/devices", headers=bob_h).json()[0]["id"]
    assert client.delete(f"/api/v1/app/devices/{bob_device}", headers=alice_h).status_code == 404
    assert client.delete(f"/api/v1/app/devices/{bob_device}", headers=bob_h).status_code == 204
    too_short = client.post("/api/v1/app/devices", headers=alice_h, json={**device, "push_token": "short"})
    assert too_short.status_code == 422
