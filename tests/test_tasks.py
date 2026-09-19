"""Task / follow-up lifecycle, filters, visibility and the CRM summary."""
from helpers import assign_patient, at, audit_events, make_appointment, make_patient


def create_task(client, headers, **body):
    response = client.post("/api/v1/tasks", headers=headers, json={"title": "Follow up", **body})
    assert response.status_code == 201, response.text
    return response.json()


def test_follow_up_lifecycle(client, org_a, test_engine):
    ops, care = org_a["ops"]["headers"], org_a["care"]
    patient = make_patient(client, org_a)
    appt = make_appointment(client, org_a, patient["id"])
    task = create_task(client, ops, title="Check blood pressure readings", owner_user_id=care["id"],
                       appointment_id=appt["id"], due_at=at(days=2), priority="HIGH")
    # The patient comes from the appointment.
    assert task["patient_id"] == patient["id"] and task["status"] == "OPEN"

    open_list = client.get("/api/v1/tasks?owner=me&status=open", headers=care["headers"]).json()["data"]
    assert [t["id"] for t in open_list] == [task["id"]]

    url = f"/api/v1/tasks/{task['id']}"
    started = client.patch(url, headers=care["headers"], json={"version": 1, "status": "IN_PROGRESS"})
    assert started.json()["status"] == "IN_PROGRESS"
    done = client.post(f"{url}/complete", headers=care["headers"]).json()
    assert done["status"] == "DONE" and done["completed_by"] == care["id"] and done["completed_at"]
    event = audit_events(test_engine, "task.complete")[0]
    assert str(event["actor_user_id"]) == care["id"]

    assert client.post(f"{url}/complete", headers=care["headers"]).status_code == 409
    assert client.patch(url, headers=care["headers"], json={"version": 3, "title": "x"}).status_code == 409
    reopened = client.post(f"{url}/reopen", headers=care["headers"]).json()
    assert reopened["status"] == "OPEN" and reopened["completed_at"] is None and reopened["completed_by"] is None
    assert client.post(f"{url}/cancel", headers=ops).json()["status"] == "CANCELLED"
    assert client.get("/api/v1/tasks?owner=me&status=open", headers=care["headers"]).json()["data"] == []


def test_overdue_and_due_filters(client, org_a):
    coord = org_a["coord"]["headers"]
    late = create_task(client, coord, title="Late", due_at=at(hours=-5))
    soon = create_task(client, coord, title="Soon", due_at=at(hours=5), priority="URGENT")
    create_task(client, coord, title="Later", due_at=at(days=10))
    create_task(client, coord, title="Whenever")

    def titles(query):
        response = client.get(f"/api/v1/tasks?{query}", headers=coord)
        assert response.status_code == 200, response.text
        return [t["title"] for t in response.json()["data"]]

    assert titles("overdue=true") == ["Late"]
    assert titles(f"due_before={at(days=1).replace('+00:00', 'Z')}") == ["Late", "Soon"]
    assert titles("sort=-priority")[0] == "Soon"
    assert titles("") == ["Late", "Soon", "Later", "Whenever"]  # by due date, undated last
    detail = client.get(f"/api/v1/tasks/{late['id']}", headers=coord).json()
    assert detail["is_overdue"] is True
    client.post(f"/api/v1/tasks/{late['id']}/complete", headers=coord)
    assert titles("overdue=true") == []
    assert titles("status=done") == ["Late"]
    assert client.get(f"/api/v1/tasks/{soon['id']}", headers=coord).json()["is_overdue"] is False


def test_task_visibility_and_change_rights(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"], "care")
    assign_patient(client, org_a, patient["id"], "care2", assignment_type="SECONDARY")
    unassigned = make_patient(client, org_a, legal_first_name="Nobody", legal_last_name="Else")

    care_task = create_task(client, ops, owner_user_id=org_a["care"]["id"], patient_id=patient["id"])
    private = create_task(client, ops, owner_user_id=org_a["coord"]["id"], patient_id=unassigned["id"])

    care2 = org_a["care2"]["headers"]
    # care2 sees the follow-up on a shared patient but cannot work on someone else's task...
    assert client.get(f"/api/v1/tasks/{care_task['id']}", headers=care2).status_code == 200
    assert client.post(f"/api/v1/tasks/{care_task['id']}/complete", headers=care2).status_code == 403
    # ...and cannot see tasks about patients not assigned to them.
    assert client.get(f"/api/v1/tasks/{private['id']}", headers=care2).status_code == 404
    listed = {t["id"] for t in client.get("/api/v1/tasks", headers=care2).json()["data"]}
    assert listed == {care_task["id"]}
    # Filters cannot widen that.
    assert client.get(f"/api/v1/tasks?patient_id={unassigned['id']}", headers=care2).json()["data"] == []

    # Links must be visible and consistent.
    assert client.post("/api/v1/tasks", headers=care2,
                       json={"title": "x", "patient_id": unassigned["id"]}).status_code == 422
    other_appt = make_appointment(client, org_a, unassigned["id"], staff_key="coord")
    assert client.post("/api/v1/tasks", headers=ops, json={
        "title": "x", "patient_id": patient["id"], "appointment_id": other_appt["id"]}).status_code == 422
    assert client.post("/api/v1/tasks", headers=ops,
                       json={"title": "x", "owner_user_id": org_b["care"]["id"]}).status_code == 422

    # Other organisations and roles without task permissions.
    assert client.get(f"/api/v1/tasks/{care_task['id']}", headers=org_b["ops"]["headers"]).status_code == 404
    assert client.get("/api/v1/tasks", headers=org_a["sysadmin"]["headers"]).status_code == 403


def test_crm_summary_respects_permissions(client, org_a, test_engine):
    ops, care = org_a["ops"]["headers"], org_a["care"]
    patient = make_patient(client, org_a)
    assign_patient(client, org_a, patient["id"])
    make_appointment(client, org_a, patient["id"], start_hours=1)
    make_appointment(client, org_a, patient["id"], start_hours=72)
    other = make_patient(client, org_a, legal_first_name="Other", legal_last_name="Person")
    make_appointment(client, org_a, other["id"], staff_key="care2", start_hours=2)
    create_task(client, ops, owner_user_id=care["id"], due_at=at(hours=-1))
    create_task(client, ops, owner_user_id=org_a["care2"]["id"], patient_id=other["id"])

    mine = client.get("/api/v1/summary", headers=care["headers"]).json()
    assert mine["appointments"]["upcoming_7_days"] == 2      # not care2's appointment with another patient
    assert mine["tasks"] == {"open": 1, "overdue": 1, "due_today": mine["tasks"]["due_today"], "mine_open": 1}
    assert [p["id"] for p in mine["recently_updated_assigned_patients"]] == [patient["id"]]

    everything = client.get("/api/v1/summary", headers=ops).json()
    assert everything["appointments"]["upcoming_7_days"] == 3
    assert everything["tasks"]["open"] == 2
    assert everything["recently_updated_assigned_patients"] == []   # nobody is assigned to the ops admin

    assert client.get("/api/v1/summary", headers=org_a["sysadmin"]["headers"]).status_code == 403
