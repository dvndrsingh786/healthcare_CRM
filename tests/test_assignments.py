"""Assigning staff and teams to patients, unassigning, and staff caseloads."""
from helpers import audit_events, make_patient


def assign(client, org, patient_id, headers=None, **body):
    return client.post(f"/api/v1/patients/{patient_id}/assignments", headers=headers or org["ops"]["headers"],
                       json=body)


def test_assign_and_unassign_staff(client, org_a, test_engine):
    care = org_a["care"]
    patient = make_patient(client, org_a)

    created = assign(client, org_a, patient["id"], staff_user_id=care["id"], assignment_type="PRIMARY")
    assert created.status_code == 201, created.text
    assignment = created.json()
    assert assignment["staff_display_name"] == "Care Northfield" and assignment["active"] is True
    assert client.get(f"/api/v1/patients/{patient['id']}", headers=care["headers"]).status_code == 200

    ended = client.post(f"/api/v1/patients/{patient['id']}/assignments/{assignment['id']}/end",
                        headers=org_a["ops"]["headers"])
    assert ended.status_code == 200 and ended.json()["active"] is False and ended.json()["ends_on"]
    # Access ends with the assignment.
    assert client.get(f"/api/v1/patients/{patient['id']}", headers=care["headers"]).status_code == 404

    url = f"/api/v1/patients/{patient['id']}/assignments"
    assert client.get(url, headers=org_a["ops"]["headers"]).json() == []
    history = client.get(url + "?include_ended=true", headers=org_a["ops"]["headers"]).json()
    assert [a["id"] for a in history] == [assignment["id"]]
    assert {e["action"] for e in audit_events(test_engine)} >= {"assignment.create", "assignment.end"}


def test_assignment_rules(client, org_a, org_b):
    patient = make_patient(client, org_a)
    pid = patient["id"]
    assert assign(client, org_a, pid, staff_user_id=org_a["care"]["id"], assignment_type="PRIMARY").status_code == 201

    second_primary = assign(client, org_a, pid, staff_user_id=org_a["care2"]["id"], assignment_type="PRIMARY")
    assert second_primary.status_code == 409
    assert second_primary.json()["error"]["code"] == "ASSIGNMENT_CONFLICT"
    twice = assign(client, org_a, pid, staff_user_id=org_a["care"]["id"], assignment_type="SECONDARY")
    assert twice.status_code == 409
    assert assign(client, org_a, pid, staff_user_id=org_a["care2"]["id"],
                  assignment_type="SECONDARY").status_code == 201

    # Staff of another organisation, and malformed requests, are rejected.
    assert assign(client, org_a, pid, staff_user_id=org_b["care"]["id"], assignment_type="SECONDARY").status_code == 422
    assert assign(client, org_a, pid, staff_user_id=org_a["coord"]["id"], assignment_type="TEAM").status_code == 422
    assert assign(client, org_a, pid, assignment_type="SECONDARY").status_code == 422
    # Care staff cannot assign.
    assert assign(client, org_a, pid, headers=org_a["care"]["headers"], staff_user_id=org_a["coord"]["id"],
                  assignment_type="SECONDARY").status_code == 403
    # Another organisation cannot assign its own staff to our patient.
    assert assign(client, org_b, pid, staff_user_id=org_b["care"]["id"], assignment_type="SECONDARY").status_code == 404


def test_team_assignment_gives_team_members_access(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    team_id = client.post("/api/v1/teams", headers=ops, json={"name": "District Nursing"}).json()["id"]
    client.post(f"/api/v1/teams/{team_id}/members", headers=ops, json={"user_id": org_a["care2"]["id"]})

    assert assign(client, org_a, patient["id"], team_id=team_id, assignment_type="TEAM").status_code == 201
    assert client.get(f"/api/v1/patients/{patient['id']}", headers=org_a["care2"]["headers"]).status_code == 200
    assert client.get(f"/api/v1/patients/{patient['id']}", headers=org_a["care"]["headers"]).status_code == 404
    listed = client.get(f"/api/v1/patients?team_id={team_id}", headers=ops).json()["data"]
    assert [p["id"] for p in listed] == [patient["id"]]

    # A team from another organisation cannot be used.
    b_team = client.post("/api/v1/teams", headers=org_b["ops"]["headers"], json={"name": "Other"}).json()["id"]
    assert assign(client, org_a, patient["id"], team_id=b_team, assignment_type="TEAM").status_code == 404


def test_archived_patients_cannot_be_assigned(client, org_a):
    patient = make_patient(client, org_a)
    client.post(f"/api/v1/patients/{patient['id']}/archive", headers=org_a["ops"]["headers"], json={"reason": "Died"})
    response = assign(client, org_a, patient["id"], staff_user_id=org_a["care"]["id"], assignment_type="PRIMARY")
    assert response.status_code == 409


def test_caseload(client, org_a):
    care = org_a["care"]
    ops = org_a["ops"]["headers"]
    first = make_patient(client, org_a, legal_first_name="Zed", legal_last_name="Adams")
    second = make_patient(client, org_a, legal_first_name="Amy", legal_last_name="Young")
    make_patient(client, org_a, legal_first_name="Not", legal_last_name="Mine")
    team_id = client.post("/api/v1/teams", headers=ops, json={"name": "Rapid Response"}).json()["id"]
    client.post(f"/api/v1/teams/{team_id}/members", headers=ops, json={"user_id": care["id"]})
    assign(client, org_a, first["id"], staff_user_id=care["id"], assignment_type="PRIMARY")
    assign(client, org_a, second["id"], team_id=team_id, assignment_type="TEAM")

    own = client.get(f"/api/v1/staff/{care['id']}/caseload", headers=care["headers"])
    assert own.status_code == 200, own.text
    entries = own.json()["data"]
    assert [e["legal_last_name"] for e in entries] == ["Adams", "Young"]
    assert entries[1]["via_team"] == "Rapid Response"

    # Someone else's caseload needs assignments:manage.
    assert client.get(f"/api/v1/staff/{org_a['care2']['id']}/caseload", headers=care["headers"]).status_code == 403
    assert client.get(f"/api/v1/staff/{care['id']}/caseload", headers=ops).json()["meta"]["total"] == 2
