"""Consent evidence: history is preserved, current state, validation and effect on messages."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from helpers import at, audit_events, make_patient, make_worker


def record(client, org, patient_id, headers=None, **body):
    return client.post(f"/api/v1/patients/{patient_id}/consents", headers=headers or org["ops"]["headers"], json={
        "consent_type": "CARE_INFORMATION_SHARING", "status": "GRANTED", "source": "PAPER_FORM",
        "policy_version": "sharing-2026.1", **body})


def test_consent_change_preserves_prior_evidence(client, org_a, test_engine):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    granted = record(client, org_a, patient["id"], captured_at=at(days=-3), note="Signed form in post")
    assert granted.status_code == 201, granted.text
    withdrawn = record(client, org_a, patient["id"], status="WITHDRAWN", source="STAFF_VERBAL")
    assert withdrawn.json()["supersedes_id"] == granted.json()["id"]

    current = client.get(f"/api/v1/patients/{patient['id']}/consents", headers=ops).json()
    assert [(c["consent_type"], c["status"]) for c in current] == [("CARE_INFORMATION_SHARING", "WITHDRAWN")]

    history = client.get(f"/api/v1/patients/{patient['id']}/consents/history", headers=ops).json()
    assert [h["status"] for h in history] == ["WITHDRAWN", "GRANTED"]
    first = history[1]
    assert first["source"] == "PAPER_FORM" and first["policy_version"] == "sharing-2026.1"
    assert first["captured_by"] == org_a["ops"]["id"] and first["captured_by_type"] == "STAFF"

    # Evidence cannot be edited or deleted, even directly in the database.
    with pytest.raises(DBAPIError), test_engine.begin() as db:
        db.execute(text("UPDATE consent_records SET status = 'GRANTED' WHERE id = :id"), {"id": first["id"]})
    events = audit_events(test_engine, "consent.record")
    assert [e["metadata"]["status"] for e in events] == ["GRANTED", "WITHDRAWN"]
    assert "Signed form" not in str(events)


def test_expiry_and_validation(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    expired = record(client, org_a, patient["id"], consent_type="RESEARCH_CONTACT", captured_at=at(days=-10),
                     expires_at=at(days=-1))
    assert expired.json()["effective_status"] == "EXPIRED"

    assert record(client, org_a, patient["id"], source="APP").status_code == 422      # staff cannot claim APP
    assert record(client, org_a, patient["id"], captured_at=at(days=2)).status_code == 422
    assert record(client, org_a, patient["id"], consent_type="EVERYTHING").status_code == 422
    assert record(client, org_a, patient["id"], policy_version="").status_code == 422
    assert record(client, org_a, patient["id"], captured_at=at(days=-1), expires_at=at(days=-2)).status_code == 422
    other = make_patient(client, org_b)
    assert record(client, org_a, other["id"]).status_code == 422
    assert client.get(f"/api/v1/patients/{patient['id']}/consents",
                      headers=org_b["ops"]["headers"]).status_code == 404
    assert client.get(f"/api/v1/patients/{patient['id']}/consents",
                      headers=org_a["sysadmin"]["headers"]).status_code == 403
    assert client.get(f"/api/v1/patients/{patient['id']}/consents", headers=ops).status_code == 200


def test_marketing_messages_need_consent(client, org_a):
    ops = org_a["ops"]["headers"]
    patient = make_patient(client, org_a)
    worker = make_worker(client, org_a)

    def send_update(key):
        created = client.post("/api/v1/notifications", headers={**ops, "Idempotency-Key": key}, json={
            "patient_id": patient["id"], "channel": "EMAIL", "template_key": "service_update"}).json()
        client.post("/api/v1/notifications/process", headers=worker)
        return client.get(f"/api/v1/notifications/{created['id']}", headers=ops).json()

    blocked = send_update("update-00001")
    assert blocked["status"] == "SKIPPED" and blocked["skip_reason"] == "NO_CONSENT"
    record(client, org_a, patient["id"], consent_type="MARKETING_EMAIL", source="ELECTRONIC_FORM")
    assert send_update("update-00002")["status"] == "SENT"
