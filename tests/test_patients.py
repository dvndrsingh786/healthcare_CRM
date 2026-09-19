"""Patients: create/validate/duplicates, read/search, update with versions, archive, emergency
contacts, the patient app's own profile, and who may see which patient."""
import json

from helpers import audit_events, make_app_user, make_patient, patient_body


def fields_in_error(response):
    return {item["field"] for item in response.json()["error"].get("fields", [])}


def test_create_patient_with_emergency_contact(client, org_a, test_engine):
    response = client.post("/api/v1/patients", headers=org_a["ops"]["headers"], json=patient_body(
        mrn="NF-100245", preferred_name="Maggie",
        emergency_contacts=[{"name": "David Okafor", "relationship": "Son", "phone": "+44 7700 900789",
                             "is_next_of_kin": True}]))
    assert response.status_code == 201, response.text
    patient = response.json()
    assert patient["status"] == "ACTIVE" and patient["version"] == 1
    assert patient["date_of_birth"] == "1948-03-14" and patient["mrn"] == "NF-100245"
    assert patient["sensitive_fields_hidden"] is False
    assert "organisation_id" not in patient and "created_by" not in patient

    contacts = client.get(f"/api/v1/patients/{patient['id']}/emergency-contacts",
                          headers=org_a["ops"]["headers"]).json()
    assert [c["name"] for c in contacts] == ["David Okafor"]

    created = audit_events(test_engine, "patient.create")
    assert len(created) == 1 and created[0]["resource_id"] == patient["id"]
    assert created[0]["metadata"]["emergency_contacts"] == 1


def test_create_rejects_bad_and_missing_data(client, org_a):
    ops = org_a["ops"]["headers"]
    bad = client.post("/api/v1/patients", headers=ops, json=patient_body(
        date_of_birth="2999-01-01", phone="call me", email="not-an-email", legal_first_name="R2D2"))
    assert bad.status_code == 422
    assert {"date_of_birth", "phone", "email", "legal_first_name"} <= fields_in_error(bad)
    # The submitted values are never echoed back.
    assert "2999-01-01" not in bad.text and "call me" not in bad.text

    assert client.post("/api/v1/patients", headers=ops,
                       json=patient_body(date_of_birth="14/03/1948")).status_code == 422

    missing = client.post("/api/v1/patients", headers=ops, json={"legal_first_name": "Ann"})
    assert {"legal_last_name", "date_of_birth"} <= fields_in_error(missing)

    # Fields the client may not set are rejected, not silently ignored.
    extra = client.post("/api/v1/patients", headers=ops, json=patient_body(organisation_id=org_a["id"]))
    assert extra.status_code == 422

    unreachable = client.post("/api/v1/patients", headers=ops, json=patient_body(
        emergency_contacts=[{"name": "No Way", "relationship": "Friend"}]))
    assert unreachable.status_code == 422


def test_duplicate_rules(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    make_patient(client, org_a, mrn="NF-1")

    same_mrn = client.post("/api/v1/patients", headers=ops, json=patient_body(
        mrn="NF-1", legal_first_name="Other", confirm_not_duplicate=True))
    assert same_mrn.status_code == 409
    assert same_mrn.json()["error"]["code"] == "DUPLICATE_IDENTIFIER"

    same_person = client.post("/api/v1/patients", headers=ops, json=patient_body(legal_last_name="OKAFOR"))
    assert same_person.status_code == 409
    assert same_person.json()["error"]["code"] == "POSSIBLE_DUPLICATE"
    # After checking, staff can confirm it is a different person.
    assert client.post("/api/v1/patients", headers=ops,
                       json=patient_body(confirm_not_duplicate=True)).status_code == 201

    # MRNs are unique per organisation only, and duplicates are not checked across organisations.
    make_patient(client, org_b, mrn="NF-1")


def test_update_uses_versions(client, org_a, test_engine):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    url = f"/api/v1/patients/{patient['id']}"

    updated = client.patch(url, headers=ops, json={"version": 1, "phone": "+44 7700 900000", "contact_by_sms": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["phone"] == "+44 7700 900000" and updated.json()["version"] == 2

    stale = client.patch(url, headers=ops, json={"version": 1, "preferred_name": "Mags"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"

    cleared = client.patch(url, headers=ops, json={"version": 2, "legal_last_name": None})
    assert cleared.status_code == 422

    events = audit_events(test_engine, "patient.update")
    assert events[0]["changed_fields"] == ["contact_by_sms", "phone"]
    # Only field names are audited, never the new values.
    assert "900000" not in json.dumps(events, default=str)


def test_search_filter_sort_and_pagination(client, org_a):
    ops = org_a["ops"]["headers"]
    make_patient(client, org_a, legal_first_name="Alice", legal_last_name="Brown", email="alice@example.com")
    make_patient(client, org_a, legal_first_name="Bob", legal_last_name="Smith", mrn="NF-777")
    carl = make_patient(client, org_a, legal_first_name="Carl", legal_last_name="Smithson")
    client.patch(f"/api/v1/patients/{carl['id']}", headers=ops, json={"version": 1, "status": "INACTIVE"})

    def names(query):
        response = client.get(f"/api/v1/patients?{query}", headers=ops)
        assert response.status_code == 200, response.text
        return [p["legal_first_name"] for p in response.json()["data"]]

    def found(**body):
        response = client.post("/api/v1/patients/search", headers=ops, json=body)
        assert response.status_code == 200, response.text
        return [p["legal_first_name"] for p in response.json()["data"]]

    assert sorted(found(search="smith")) == ["Bob", "Carl"]
    assert found(search="alice@") == ["Alice"]
    assert found(search="NF-77") == ["Bob"]
    assert found(search="smith", status="ACTIVE") == ["Bob"]
    assert found(search="smith", sort="-legal_last_name", page_size=1) == ["Carl"]
    assert names("status=inactive") == ["Carl"]
    assert names("sort=legal_last_name") == ["Alice", "Bob", "Carl"]
    # A search for "%" must not match everything.
    assert found(search="%%") == []
    # The search body has the same limits as the query string.
    assert client.post("/api/v1/patients/search", headers=ops, json={"page_size": 500}).status_code == 422
    assert client.post("/api/v1/patients/search", headers=ops, json={"search": "x"}).status_code == 422

    page = client.get("/api/v1/patients?page_size=2&sort=legal_last_name", headers=ops).json()
    assert page["meta"]["total"] == 3 and page["meta"]["total_pages"] == 2
    assert client.get("/api/v1/patients?page_size=500", headers=ops).status_code == 422
    assert client.get("/api/v1/patients?sort=mrn", headers=ops).status_code == 422
    assert client.get("/api/v1/patients?status=deleted", headers=ops).status_code == 422


def test_coordinator_does_not_see_sensitive_fields(client, org_a):
    patient = make_patient(client, org_a, mrn="NF-9")
    coord = org_a["coord"]["headers"]
    seen = client.get(f"/api/v1/patients/{patient['id']}", headers=coord).json()
    assert seen["legal_last_name"] == "Okafor"
    assert seen["sensitive_fields_hidden"] is True
    assert seen["date_of_birth"] is None and seen["mrn"] is None and seen["postcode"] is None
    # Nor can they find a patient by MRN, or sort by date of birth.
    assert client.post("/api/v1/patients/search", headers=coord, json={"search": "NF-9"}).json()["data"] == []
    assert client.get("/api/v1/patients?sort=date_of_birth", headers=coord).status_code == 422


def test_care_staff_only_see_assigned_patients(client, org_a, test_engine):
    care = org_a["care"]
    mine = make_patient(client, org_a, legal_first_name="Mine")
    other = make_patient(client, org_a, legal_first_name="Other")
    client.post(f"/api/v1/patients/{mine['id']}/assignments", headers=org_a["ops"]["headers"],
                json={"staff_user_id": care["id"], "assignment_type": "PRIMARY"})

    listed = client.get("/api/v1/patients", headers=care["headers"]).json()
    assert [p["legal_first_name"] for p in listed["data"]] == ["Mine"]
    assert client.get(f"/api/v1/patients/{mine['id']}", headers=care["headers"]).status_code == 200

    # Not assigned: 404, exactly like an id that does not exist, and the attempt is audited.
    hidden = client.get(f"/api/v1/patients/{other['id']}", headers=care["headers"])
    assert hidden.status_code == 404
    denied = audit_events(test_engine, "access.denied")
    assert denied[-1]["resource_id"] == other["id"]

    # Filters cannot widen the scope.
    widened = client.get(f"/api/v1/patients?assigned_staff_id={org_a['care2']['id']}&status=active",
                         headers=care["headers"]).json()
    assert widened["data"] == []


def test_system_admin_and_app_users_cannot_use_patient_crm(client, org_a, test_engine):
    patient = make_patient(client, org_a)
    assert client.get("/api/v1/patients", headers=org_a["sysadmin"]["headers"]).status_code == 403
    app_user = make_app_user(client, test_engine, org_a["id"], "pat@northfield.example", patient["id"])
    assert client.get(f"/api/v1/patients/{patient['id']}", headers=app_user["headers"]).status_code == 403


def test_other_organisation_cannot_reach_patients(client, org_a, org_b):
    patient = make_patient(client, org_a, legal_first_name="Private")
    url = f"/api/v1/patients/{patient['id']}"
    b_ops = org_b["ops"]["headers"]

    assert client.get(url, headers=b_ops).status_code == 404
    assert client.patch(url, headers=b_ops, json={"version": 1, "phone": "+44 7700 900111"}).status_code == 404
    assert client.post(f"{url}/archive", headers=b_ops, json={"reason": "test"}).status_code == 404
    assert client.get(f"{url}/emergency-contacts", headers=b_ops).status_code == 404
    assert client.get(f"{url}/assignments", headers=b_ops).status_code == 404
    assert client.post("/api/v1/patients/search", headers=b_ops, json={"search": "Private"}).json()["data"] == []


def test_archive_and_restore(client, org_a, test_engine):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    url = f"/api/v1/patients/{patient['id']}"
    app_user = make_app_user(client, test_engine, org_a["id"], "pat@northfield.example", patient["id"])

    assert client.post(f"{url}/archive", headers=org_a["coord"]["headers"], json={"reason": "Moved"}).status_code == 403
    archived = client.post(f"{url}/archive", headers=ops, json={"reason": "Moved out of area"})
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"

    # Hidden from the default list, still found with status=archived, and read-only.
    assert client.get("/api/v1/patients", headers=ops).json()["data"] == []
    assert len(client.get("/api/v1/patients?status=archived", headers=ops).json()["data"]) == 1
    assert client.patch(url, headers=ops, json={"version": 2, "phone": "+44 7700 900111"}).status_code == 409
    # The patient's app session stops working immediately.
    assert client.get("/api/v1/app/profile", headers=app_user["headers"]).status_code == 401

    restored = client.post(f"{url}/restore", headers=ops)
    assert restored.json()["status"] == "ACTIVE" and restored.json()["archived_at"] is None
    assert client.post(f"{url}/restore", headers=ops).status_code == 409


def test_emergency_contacts(client, org_a):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    url = f"/api/v1/patients/{patient['id']}/emergency-contacts"

    first = client.post(url, headers=ops, json={"name": "Ann", "relationship": "Daughter", "email": "ann@example.com",
                                                "priority": 2})
    assert first.status_code == 201, first.text
    client.post(url, headers=ops, json={"name": "Ben", "relationship": "Neighbour", "phone": "+44 7700 900222"})
    assert [c["name"] for c in client.get(url, headers=ops).json()] == ["Ben", "Ann"]

    contact_url = f"{url}/{first.json()['id']}"
    assert client.patch(contact_url, headers=ops, json={"priority": 1}).json()["priority"] == 1
    # Removing the only way to reach them is refused.
    assert client.patch(contact_url, headers=ops, json={"email": None}).status_code == 422
    assert client.patch(contact_url, headers=ops, json={"name": None}).status_code == 422
    assert client.post(url, headers=org_a["coord"]["headers"],
                       json={"name": "X", "relationship": "Y", "phone": "+44 7700 900333"}).status_code == 403

    assert client.delete(contact_url, headers=ops).status_code == 204
    assert client.delete(contact_url, headers=ops).status_code == 404


def test_app_account_invite(client, org_a, sent_messages):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    url = f"/api/v1/patients/{patient['id']}/app-account"

    invited = client.post(url, headers=ops, json={"email": "maggie.app@example.com"})
    assert invited.status_code == 201, invited.text
    assert invited.json()["has_app_account"] is True
    assert sent_messages[-1].template_key == "account_invite"
    assert client.post(url, headers=ops, json={"email": "again@example.com"}).json()["error"]["code"] \
        == "APP_ACCOUNT_EXISTS"


def test_app_user_sees_and_edits_only_own_profile(client, org_a, test_engine):
    alice = make_patient(client, org_a, legal_first_name="Alice", legal_last_name="Able")
    bob = make_patient(client, org_a, legal_first_name="Bob", legal_last_name="Baker")
    alice_app = make_app_user(client, test_engine, org_a["id"], "alice@northfield.example", alice["id"])
    make_app_user(client, test_engine, org_a["id"], "bob@northfield.example", bob["id"])

    profile = client.get("/api/v1/app/profile", headers=alice_app["headers"])
    assert profile.status_code == 200
    assert profile.json()["legal_first_name"] == "Alice"
    assert "mrn" not in profile.json() and "id" not in profile.json()

    updated = client.patch("/api/v1/app/profile", headers=alice_app["headers"],
                           json={"preferred_name": "Al", "contact_by_sms": True})
    assert updated.json()["preferred_name"] == "Al"
    # Legal details are changed by staff only.
    assert client.patch("/api/v1/app/profile", headers=alice_app["headers"],
                        json={"legal_last_name": "Changed"}).status_code == 422
    # Bob's record is unchanged, and Alice has no way to name it.
    assert client.get(f"/api/v1/patients/{bob['id']}", headers=alice_app["headers"]).status_code == 403
    bob_now = client.get(f"/api/v1/patients/{bob['id']}", headers=org_a["ops"]["headers"]).json()
    assert bob_now["preferred_name"] is None

    # Staff tokens cannot use the app endpoints.
    assert client.get("/api/v1/app/profile", headers=org_a["ops"]["headers"]).status_code == 403


def test_reads_are_audited_without_personal_data(client, org_a, test_engine):
    patient = make_patient(client, org_a, mrn="NF-555")
    client.get(f"/api/v1/patients/{patient['id']}", headers=org_a["ops"]["headers"])
    reads = audit_events(test_engine, "patient.read")
    assert len(reads) == 1 and reads[0]["metadata"] == {"sensitive": True}

    everything = json.dumps(audit_events(test_engine), default=str)
    for value in ("Okafor", "Margaret", "1948-03-14", "NF-555", "Elm Road", "maggie@example.com"):
        assert value not in everything


def test_search_text_never_goes_in_the_url(client, org_a):
    """Spec 6.6: no sensitive values in query strings. Names, emails and phone numbers are
    searched through POST bodies; a search in the URL is refused, not silently ignored."""
    make_patient(client, org_a)
    ops = org_a["ops"]["headers"]
    for url in ("/api/v1/patients?search=Okafor", "/api/v1/users?search=nurse"):
        response = client.get(url, headers=ops)
        assert response.status_code == 422 and response.json()["error"]["fields"][0]["field"] == "search"
        assert "/search" in response.json()["error"]["message"]
    users = client.post("/api/v1/users/search", headers=ops, json={"search": "care", "sort": "email"}).json()
    assert {u["email"] for u in users["data"]} == {"care@northfield.example", "care2@northfield.example"}
