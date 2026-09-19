"""Appointment lifecycle, transitions, validation, double-booking and visibility."""
from helpers import (
    assign_patient,
    at,
    audit_events,
    make_appointment,
    make_patient,
    move_to_past,
)


def test_lifecycle_with_history_audit_and_notification(client, org_a, test_engine):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    appt = make_appointment(client, org_a, patient["id"], timezone="Europe/London")
    assert appt["status"] == "SCHEDULED" and appt["staff_display_name"] == "Care Northfield"
    assert appt["patient_name"] == "Margaret Okafor"
    assert appt["starts_at_local"][-6:] in ("+01:00", "+00:00")
    url = f"/api/v1/appointments/{appt['id']}"

    # Booking queued a message for the patient (email is on by default).
    queued = client.get(f"/api/v1/notifications?reference_id={appt['id']}", headers=ops).json()["data"]
    assert [(n["channel"], n["template_key"], n["status"]) for n in queued] == [
        ("EMAIL", "appointment_booked", "QUEUED")]

    assert client.post(f"{url}/confirm", headers=ops).json()["status"] == "CONFIRMED"
    moved = client.post(f"{url}/reschedule", headers=ops, json={
        "version": 2, "starts_at": at(hours=48), "ends_at": at(hours=49), "reason": "Nurse unavailable"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "SCHEDULED"  # needs confirming again
    cancelled = client.post(f"{url}/cancel", headers=ops, json={"reason": "Patient in hospital"})
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancellation_reason"] == "Patient in hospital"

    history = client.get(f"{url}/history", headers=ops).json()
    assert [h["event"] for h in history] == ["CREATED", "CONFIRMED", "RESCHEDULED", "CANCELLED"]
    assert history[2]["reason"] == "Nurse unavailable" and history[2]["old_starts_at"] is not None
    actions = {e["action"] for e in audit_events(test_engine)}
    assert {"appointment.create", "appointment.confirmed", "appointment.reschedule",
            "appointment.cancelled"} <= actions
    templates = [n["template_key"] for n in client.get(
        f"/api/v1/notifications?reference_id={appt['id']}&sort=created_at", headers=ops).json()["data"]]
    assert templates == ["appointment_booked", "appointment_rescheduled", "appointment_cancelled"]


def test_invalid_transitions_are_refused(client, org_a, test_engine):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    appt = make_appointment(client, org_a, patient["id"])
    url = f"/api/v1/appointments/{appt['id']}"

    # No outcome before the appointment has started.
    early = client.post(f"{url}/complete", headers=ops)
    assert early.status_code == 409 and early.json()["error"]["code"] == "INVALID_TRANSITION"

    move_to_past(test_engine, appt["id"])
    assert client.post(f"{url}/no-show", headers=ops).json()["status"] == "NO_SHOW"
    for action in ("confirm", "complete", "no-show"):
        response = client.post(f"{url}/{action}", headers=ops)
        assert response.status_code == 409 and response.json()["error"]["code"] == "INVALID_TRANSITION"
    assert client.post(f"{url}/cancel", headers=ops, json={"reason": "x"}).status_code == 409
    finished = client.post(f"{url}/reschedule", headers=ops, json={
        "version": 2, "starts_at": at(hours=5), "ends_at": at(hours=6)})
    assert finished.status_code == 409 and finished.json()["error"]["code"] == "INVALID_STATE"
    assert client.patch(url, headers=ops, json={"version": 2, "location": "Clinic"}).status_code == 409


def test_care_staff_record_outcomes_but_cannot_book(client, org_a, test_engine):
    care = org_a["care"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    appt = make_appointment(client, org_a, patient["id"])

    assert client.post("/api/v1/appointments", headers=care, json={
        "patient_id": patient["id"], "starts_at": at(hours=3), "ends_at": at(hours=4),
        "appointment_type": "CLINIC"}).status_code == 403
    move_to_past(test_engine, appt["id"])
    done = client.post(f"/api/v1/appointments/{appt['id']}/complete", headers=care)
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    event = audit_events(test_engine, "appointment.completed")[0]
    assert event["actor_user_id"] is not None and str(event["actor_user_id"]) == org_a["care"]["id"]


def test_validation(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    base = {"patient_id": patient["id"], "starts_at": at(hours=24), "ends_at": at(hours=25),
            "appointment_type": "CLINIC"}

    def post(**changes):
        return client.post("/api/v1/appointments", headers=ops, json={**base, **changes})

    assert post().status_code == 201
    assert post(starts_at="2030-01-01T09:00:00", ends_at="2030-01-01T10:00:00").status_code == 422  # no offset
    assert post(ends_at=at(hours=23)).status_code == 422             # ends before it starts
    assert post(ends_at=at(hours=60)).status_code == 422             # longer than 24 hours
    assert post(starts_at=at(hours=-3), ends_at=at(hours=-2)).status_code == 422  # in the past
    assert post(timezone="Mars/Olympus").status_code == 422
    assert post(appointment_type="SURGERY").status_code == 422
    assert post(staff_user_id=org_b["care"]["id"]).status_code == 422  # staff of another organisation
    other_patient = make_patient(client, org_b)
    assert post(patient_id=other_patient["id"]).status_code == 422

    client.post(f"/api/v1/patients/{patient['id']}/archive", headers=ops, json={"reason": "Moved away"})
    assert post().status_code == 409


def test_staff_cannot_be_double_booked(client, org_a):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    first = make_appointment(client, org_a, patient["id"], start_hours=30, length_minutes=60)
    other = make_patient(client, org_a, legal_first_name="Other", legal_last_name="Person")
    overlap = client.post("/api/v1/appointments", headers=ops, json={
        "patient_id": other["id"], "staff_user_id": org_a["care"]["id"], "starts_at": at(hours=30, minutes=30),
        "ends_at": at(hours=31, minutes=30), "appointment_type": "CLINIC"})
    assert overlap.status_code == 409 and overlap.json()["error"]["code"] == "APPOINTMENT_CONFLICT"

    # Back to back is fine, and a cancelled slot is free again.
    make_appointment(client, org_a, other["id"], start_hours=31, length_minutes=30)
    client.post(f"/api/v1/appointments/{first['id']}/cancel", headers=ops, json={"reason": "Not needed"})
    make_appointment(client, org_a, other["id"], start_hours=30, length_minutes=30)


def test_visibility_and_filters(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    mine = make_patient(client, org_a, legal_first_name="Mine")
    other = make_patient(client, org_a, legal_first_name="Other")
    assign_patient(client, org_a, mine["id"], staff_key="care2")
    a1 = make_appointment(client, org_a, mine["id"], staff_key=None, start_hours=10)
    a2 = make_appointment(client, org_a, other["id"], staff_key="care2", start_hours=50)
    a3 = make_appointment(client, org_a, other["id"], staff_key="care", start_hours=70)

    care2 = org_a["care2"]["headers"]
    seen = {a["id"] for a in client.get("/api/v1/appointments", headers=care2).json()["data"]}
    # Their assigned patient's appointment, and the one booked with them; not someone else's.
    assert seen == {a1["id"], a2["id"]}
    assert client.get(f"/api/v1/appointments/{a3['id']}", headers=care2).status_code == 404
    assert client.get(f"/api/v1/appointments/{a1['id']}", headers=org_b["ops"]["headers"]).status_code == 404
    assert client.get("/api/v1/appointments", headers=org_a["sysadmin"]["headers"]).status_code == 403

    def ids(query):
        response = client.get(f"/api/v1/appointments?{query}", headers=ops)
        assert response.status_code == 200, response.text
        return [a["id"] for a in response.json()["data"]]

    assert ids("") == [a1["id"], a2["id"], a3["id"]]
    assert ids(f"patient_id={other['id']}&sort=-starts_at") == [a3["id"], a2["id"]]
    assert ids(f"from={at(hours=40).replace('+00:00', 'Z')}&to={at(hours=60).replace('+00:00', 'Z')}") == [a2["id"]]
    assert ids(f"staff_user_id={org_a['care']['id']}") == [a3["id"]]
    assert ids("status=CANCELLED") == []


def test_update_details_with_version(client, org_a):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    appt = make_appointment(client, org_a, patient["id"])
    url = f"/api/v1/appointments/{appt['id']}"
    changed = client.patch(url, headers=ops, json={"version": 1, "mode": "PHONE", "location": None,
                                                   "app_visible": False})
    assert changed.status_code == 200, changed.text
    assert changed.json()["mode"] == "PHONE" and changed.json()["version"] == 2
    stale = client.patch(url, headers=ops, json={"version": 1, "mode": "VIDEO"})
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert client.patch(url, headers=ops, json={"version": 2, "mode": None}).status_code == 422
