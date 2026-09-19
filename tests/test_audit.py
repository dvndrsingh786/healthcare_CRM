"""Audit log: searchable, append-only, scoped, and free of secrets and sensitive payloads."""
import json
import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from helpers import PASSWORD, PDF, audit_events, login, make_patient, upload_and_confirm


def test_audit_search_filters_and_is_itself_audited(client, org_a, org_b, test_engine):
    admin = org_a["sysadmin"]["headers"]
    patient = make_patient(client, org_a)
    client.get(f"/api/v1/patients/{patient['id']}", headers=org_a["ops"]["headers"])
    client.post("/api/v1/users", headers=org_a["coord"]["headers"], json={})  # denied

    def search(query, headers=admin):
        response = client.get(f"/api/v1/audit-events?{query}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    created = search("action=patient.create")["data"]
    assert [e["resource_id"] for e in created] == [patient["id"]]
    assert {e["action"] for e in search("action=patient.*")["data"]} == {"patient.create", "patient.read"}
    assert search(f"resource_id={patient['id']}&resource_type=patient")["meta"]["total"] == 2
    denied = search("outcome=DENIED")["data"]
    assert denied and all(e["action"] == "access.denied" for e in denied)
    assert search(f"actor_user_id={org_a['ops']['id']}")["meta"]["total"] >= 2
    assert search("from=2999-01-01T00:00:00Z")["data"] == []

    searches = audit_events(test_engine, "audit.search")
    assert len(searches) == 6 and searches[0]["metadata"]["filters"] == {"action": "patient.create"}

    # Other organisations see none of it; roles without audit:read cannot search.
    assert search("action=patient.create", headers=org_b["sysadmin"]["headers"])["data"] == []
    assert client.get("/api/v1/audit-events", headers=org_a["ops"]["headers"]).status_code == 403
    assert client.get("/api/v1/audit-events?page_size=1000", headers=admin).status_code == 422


def test_audit_log_is_append_only(client, org_a, test_engine):
    make_patient(client, org_a)
    with pytest.raises(DBAPIError), test_engine.begin() as db:
        db.execute(text("UPDATE audit_events SET action = 'nothing'"))
    with pytest.raises(DBAPIError), test_engine.begin() as db:
        db.execute(text("DELETE FROM audit_events"))


def test_audit_log_has_no_secrets_or_sensitive_payloads(client, org_a, test_engine, sent_messages):
    """Mandatory scenario: no password, access token, raw document body or similar payloads."""
    ops = org_a["ops"]["headers"]
    tokens = login(client, org_a["ops"]["email"])
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
    client.post("/api/v1/auth/login", json={"email": org_a["ops"]["email"], "password": "Wrong-password-123"})
    client.post("/api/v1/auth/password-reset/request", json={"email": org_a["care"]["email"]})
    reset_token = re.search(r"pr_[A-Za-z0-9_-]+", sent_messages[-1].body).group()

    patient = make_patient(client, org_a, mrn="NF-9000")
    client.post(f"/api/v1/patients/{patient['id']}/notes", headers=ops, json={
        "subject": "Call", "body": "Discussed her new heart medication dosage.", "visibility": "INTERNAL"})
    upload_and_confirm(client, ops, patient["id"])
    client.post(f"/api/v1/patients/{patient['id']}/consents", headers=ops, json={
        "consent_type": "DATA_PROCESSING", "status": "GRANTED", "source": "STAFF_VERBAL",
        "policy_version": "v1", "note": "Daughter present as witness"})

    everything = json.dumps(audit_events(test_engine), default=str)
    forbidden_values = [PASSWORD, "Wrong-password-123", tokens["access_token"], tokens["refresh_token"],
                        refreshed["access_token"], refreshed["refresh_token"], reset_token,
                        PDF.decode(errors="ignore")[:40], "heart medication", "Daughter present",
                        "Margaret", "Okafor", "1948-03-14", "NF-9000", "maggie@example.com"]
    for value in forbidden_values:
        assert value not in everything, value
    assert "auth.login" in everything and "document.upload" in everything
