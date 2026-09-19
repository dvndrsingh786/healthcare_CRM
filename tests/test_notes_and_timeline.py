"""Notes/interactions with visibility classes, traceable edits, and the patient timeline."""
import json

from helpers import assign_patient, audit_events, make_appointment, make_patient


def add_note(client, headers, patient_id, **body):
    response = client.post(f"/api/v1/patients/{patient_id}/notes", headers=headers, json={
        "subject": "Visit", "body": "Routine visit.", "visibility": "INTERNAL", **body})
    assert response.status_code == 201, response.text
    return response.json()


def test_support_role_cannot_see_restricted_clinical_notes(client, org_a, test_engine):
    """Mandatory scenario: the CRM support role cannot access the restricted clinical note class."""
    care, coord, ops = org_a["care"]["headers"], org_a["coord"]["headers"], org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    clinical = add_note(client, care, patient["id"], subject="Wound assessment", visibility="CLINICAL",
                        body="Pressure ulcer grade 2 on left heel; dressing changed.")
    internal = add_note(client, coord, patient["id"], subject="Rota", body="Prefers morning visits.")

    for headers in (coord, ops):  # support/coordinator and ops admin: no notes:read_clinical
        listed = client.get(f"/api/v1/patients/{patient['id']}/notes", headers=headers).json()
        assert [n["id"] for n in listed["data"]] == [internal["id"]]
        assert listed["meta"]["total"] == 1
        assert client.get(f"/api/v1/notes/{clinical['id']}", headers=headers).status_code == 404
        assert client.get(f"/api/v1/patients/{patient['id']}/notes?visibility=CLINICAL",
                          headers=headers).json()["data"] == []
        timeline = client.get(f"/api/v1/patients/{patient['id']}/timeline", headers=headers).text
        assert clinical["id"] not in timeline and "ulcer" not in timeline

    # They cannot write one either.
    denied = client.post(f"/api/v1/patients/{patient['id']}/notes", headers=coord, json={
        "subject": "x", "body": "x", "visibility": "CLINICAL"})
    assert denied.status_code == 403

    # Care staff can, and that read is audited (ids only, not the text).
    seen = client.get(f"/api/v1/patients/{patient['id']}/notes", headers=care).json()["data"]
    assert {n["id"] for n in seen} == {clinical["id"], internal["id"]}
    events = audit_events(test_engine, "note.read_clinical")
    assert events and events[0]["metadata"]["note_ids"] == [clinical["id"]]
    assert "ulcer" not in json.dumps(audit_events(test_engine), default=str)
    assert any(e["resource_id"] == clinical["id"] for e in audit_events(test_engine, "access.denied"))


def test_edits_are_traceable_and_only_by_the_author(client, org_a):
    care, care2 = org_a["care"]["headers"], org_a["care2"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    assign_patient(client, org_a, patient["id"], "care2", "SECONDARY")
    note = add_note(client, care, patient["id"], visibility="CLINICAL", body="Original clinical text.")
    url = f"/api/v1/notes/{note['id']}"

    assert client.patch(url, headers=care2, json={"version": 1, "body": "Hijacked"}).status_code == 403
    edited = client.patch(url, headers=care, json={"version": 1, "body": "Corrected text.", "visibility": "INTERNAL",
                                                   "reason": "Not clinical after all"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["edited"] is True and edited.json()["version"] == 2
    assert client.patch(url, headers=care, json={"version": 1, "body": "Stale"}).status_code == 409

    revisions = client.get(f"{url}/revisions", headers=care).json()
    assert [(r["version"], r["body"], r["edit_reason"]) for r in revisions] == [
        (1, "Original clinical text.", "Not clinical after all")]
    # The coordinator can now read the (INTERNAL) note, but not its earlier CLINICAL version.
    coord = org_a["coord"]["headers"]
    assert client.get(url, headers=coord).json()["body"] == "Corrected text."
    assert client.get(f"{url}/revisions", headers=coord).json() == []

    retracted = client.post(f"{url}/retract", headers=care, json={"reason": "Wrong patient"})
    assert retracted.json()["status"] == "ENTERED_IN_ERROR"
    assert client.patch(url, headers=care, json={"version": 3, "body": "x"}).status_code == 409
    active_only = client.get(f"/api/v1/patients/{patient['id']}/notes?include_retracted=false", headers=care)
    assert active_only.json()["data"] == []


def test_note_validation_and_scope(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    url = f"/api/v1/patients/{patient['id']}/notes"
    assert client.post(url, headers=ops, json={"subject": "", "body": "x", "visibility": "INTERNAL"}).status_code == 422
    assert client.post(url, headers=ops, json={"subject": "x", "body": "x" * 20001,
                                               "visibility": "INTERNAL"}).status_code == 422
    assert client.post(url, headers=ops, json={"subject": "x", "body": "x", "visibility": "PUBLIC"}).status_code == 422
    assert client.post(url, headers=ops, json={"subject": "x", "body": "x", "visibility": "INTERNAL",
                                               "occurred_at": "2999-01-01T00:00:00Z"}).status_code == 422
    note = add_note(client, ops, patient["id"])
    assert client.get(f"/api/v1/notes/{note['id']}", headers=org_b["ops"]["headers"]).status_code == 404
    assert client.post(f"/api/v1/patients/{patient['id']}/notes", headers=org_b["ops"]["headers"], json={
        "subject": "x", "body": "x", "visibility": "INTERNAL"}).status_code == 422
    assert client.get(url, headers=org_a["sysadmin"]["headers"]).status_code == 403


def test_timeline_combines_sources_in_order(client, org_a):
    care, ops = org_a["care"]["headers"], org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    appointment = make_appointment(client, org_a, patient["id"], start_hours=48)
    note = add_note(client, care, patient["id"], subject="Call", occurred_at="2026-01-10T10:00:00Z")
    task = client.post("/api/v1/tasks", headers=ops, json={"title": "Book review", "patient_id": patient["id"],
                                                           "owner_user_id": org_a["care"]["id"]}).json()
    client.post(f"/api/v1/patients/{patient['id']}/consents", headers=ops, json={
        "consent_type": "DATA_PROCESSING", "status": "GRANTED", "source": "STAFF_VERBAL", "policy_version": "v1"})

    entries = client.get(f"/api/v1/patients/{patient['id']}/timeline", headers=care).json()
    assert [e["entry_type"] for e in entries["data"]] == ["appointment", "consent", "task", "note"]
    assert entries["data"][0]["id"] == appointment["id"] and entries["data"][3]["id"] == note["id"]
    assert entries["data"][2]["id"] == task["id"]

    oldest_first = client.get(f"/api/v1/patients/{patient['id']}/timeline?order=asc&types=note&types=task",
                              headers=care).json()
    assert [e["entry_type"] for e in oldest_first["data"]] == ["note", "task"]
    # Someone who cannot see the patient gets nothing at all.
    assert client.get(f"/api/v1/patients/{patient['id']}/timeline",
                      headers=org_a["care2"]["headers"]).status_code == 404
