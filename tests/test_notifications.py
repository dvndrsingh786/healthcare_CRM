"""Notification outbox: idempotent requests, worker, retries, opt-outs and minimal content."""
import json

from sqlalchemy import text

from app.messaging import ConsoleProvider, ProviderError, set_provider
from helpers import audit_events, make_patient, make_worker


class FailingProvider:
    def __init__(self, temporary=True):
        self.temporary = temporary
        self.calls = 0

    def send(self, message):
        self.calls += 1
        raise ProviderError("PROVIDER_TIMEOUT" if self.temporary else "INVALID_RECIPIENT", temporary=self.temporary)


def request(client, org, patient_id, key=None, **body):
    headers = dict(org["ops"]["headers"])
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/api/v1/notifications", headers=headers, json={
        "patient_id": patient_id, "channel": "EMAIL", "template_key": "appointment_reminder", **body})


def make_due_now(engine):
    with engine.begin() as db:
        db.execute(text("UPDATE notifications SET next_attempt_at = now() WHERE status = 'QUEUED'"))


def test_same_idempotency_key_never_queues_twice(client, org_a):
    patient = make_patient(client, org_a)
    first = request(client, org_a, patient["id"], key="reminder-0001")
    assert first.status_code == 201, first.text
    again = request(client, org_a, patient["id"], key="reminder-0001")
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    different = request(client, org_a, patient["id"], key="reminder-0001", channel="SMS")
    assert different.status_code == 409 and different.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert request(client, org_a, patient["id"], template_key="free_text").status_code == 422
    assert request(client, org_a, patient["id"], body="Your results are ready").status_code == 422


def test_worker_sends_minimal_content(client, org_a, test_engine, sent_messages):
    patient = make_patient(client, org_a, mrn="NF-42")
    notification = request(client, org_a, patient["id"], key="reminder-0002").json()
    worker = make_worker(client, org_a)

    result = client.post("/api/v1/notifications/process", headers=worker).json()
    assert result["sent"] == 1
    sent = client.get(f"/api/v1/notifications/{notification['id']}", headers=org_a["ops"]["headers"]).json()
    assert sent["status"] == "SENT" and sent["provider_message_id"] and sent["attempt_log"][0]["outcome"] == "SENT"

    message = sent_messages[0]
    assert message.to == "maggie@example.com"
    for private in ("Margaret", "Okafor", "NF-42", "1948", "Elm Road"):
        assert private not in message.body and private not in message.subject
    # The outbox row itself holds ids only, no address or text.
    with test_engine.connect() as db:
        row = db.execute(text("SELECT * FROM notifications WHERE id = :id"),
                         {"id": notification["id"]}).mappings().one()
    assert "maggie@" not in json.dumps(dict(row), default=str)

    # Staff tokens cannot run the worker.
    assert client.post("/api/v1/notifications/process", headers=org_a["ops"]["headers"]).status_code == 403


def test_provider_failure_is_recorded_and_retried_without_duplicates(client, org_a, test_engine, sent_messages):
    patient = make_patient(client, org_a)
    appointment_like = request(client, org_a, patient["id"], key="reminder-0003").json()
    worker = make_worker(client, org_a)

    failing = FailingProvider()
    set_provider(failing)
    first = client.post("/api/v1/notifications/process", headers=worker).json()
    assert first == {"processed": 1, "sent": 0, "retry_scheduled": 1, "failed": 0, "skipped": 0}
    url = f"/api/v1/notifications/{appointment_like['id']}"
    state = client.get(url, headers=org_a["ops"]["headers"]).json()
    assert state["status"] == "QUEUED" and state["attempts"] == 1 and state["last_error_code"] == "PROVIDER_TIMEOUT"

    # Backoff: not due yet, so nothing is sent again straight away.
    assert client.post("/api/v1/notifications/process", headers=worker).json()["processed"] == 0
    assert failing.calls == 1

    provider = ConsoleProvider()
    set_provider(provider)
    make_due_now(test_engine)
    assert client.post("/api/v1/notifications/process", headers=worker).json()["sent"] == 1
    final = client.get(url, headers=org_a["ops"]["headers"]).json()
    assert final["status"] == "SENT" and [a["outcome"] for a in final["attempt_log"]] == ["FAILED", "SENT"]
    assert len(provider.sent) == 1


def test_worker_crash_after_provider_accepted_does_not_send_twice(client, org_a, test_engine):
    from app.messaging import OutgoingMessage

    patient = make_patient(client, org_a)
    notification = request(client, org_a, patient["id"], key="reminder-0004").json()
    worker = make_worker(client, org_a)
    provider = ConsoleProvider()
    set_provider(provider)

    # A worker leased the row, the provider accepted the message, then the worker died.
    provider.send(OutgoingMessage("EMAIL", "maggie@example.com", "appointment_reminder", "s", "b",
                                  idempotency_key=notification["id"]))
    with test_engine.begin() as db:
        db.execute(text("UPDATE notifications SET status = 'SENDING', attempts = 1, "
                        "locked_until = now() - interval '1 second' WHERE id = :id"), {"id": notification["id"]})

    # The expired lease is picked up again; the provider sees the same key and does not deliver twice.
    assert client.post("/api/v1/notifications/process", headers=worker).json()["sent"] == 1
    assert len(provider.sent) == 1


def test_permanent_failure_and_max_attempts(client, org_a, test_engine):
    patient = make_patient(client, org_a)
    notification = request(client, org_a, patient["id"], key="reminder-0005").json()
    worker = make_worker(client, org_a)
    set_provider(FailingProvider(temporary=False))
    assert client.post("/api/v1/notifications/process", headers=worker).json()["failed"] == 1
    failed = client.get(f"/api/v1/notifications/{notification['id']}", headers=org_a["ops"]["headers"]).json()
    assert failed["status"] == "FAILED" and failed["last_error_code"] == "INVALID_RECIPIENT"
    event = audit_events(test_engine, "notification.failed")[0]
    assert event["actor_type"] == "SERVICE"

    other = request(client, org_a, patient["id"], key="reminder-0006").json()
    set_provider(FailingProvider())
    for _ in range(5):
        make_due_now(test_engine)
        client.post("/api/v1/notifications/process", headers=worker)
    exhausted = client.get(f"/api/v1/notifications/{other['id']}", headers=org_a["ops"]["headers"]).json()
    assert exhausted["status"] == "FAILED" and exhausted["attempts"] == 5
    set_provider(ConsoleProvider())


def test_opt_out_and_transactional_policy(client, org_a, sent_messages):
    patient = make_patient(client, org_a)  # SMS is off by default
    worker = make_worker(client, org_a)
    marketing = request(client, org_a, patient["id"], key="news-0001", channel="SMS", template_key="service_update")
    reminder = request(client, org_a, patient["id"], key="reminder-0007", channel="SMS")
    client.post("/api/v1/notifications/process", headers=worker)

    ops = org_a["ops"]["headers"]
    skipped = client.get(f"/api/v1/notifications/{marketing.json()['id']}", headers=ops).json()
    assert skipped["status"] == "SKIPPED" and skipped["skip_reason"] == "OPTED_OUT"
    # Transactional messages follow the organisation policy (default: sent despite the opt-out).
    assert client.get(f"/api/v1/notifications/{reminder.json()['id']}", headers=ops).json()["status"] == "SENT"

    client.patch("/api/v1/organisation", headers=org_a["sysadmin"]["headers"],
                 json={"settings": {"notifications": {"transactional_ignores_opt_out": False}}})
    blocked = request(client, org_a, patient["id"], key="reminder-0008", channel="SMS")
    client.post("/api/v1/notifications/process", headers=worker)
    assert client.get(f"/api/v1/notifications/{blocked.json()['id']}", headers=ops).json()["status"] == "SKIPPED"


def test_notifications_are_scoped(client, org_a, org_b):
    patient = make_patient(client, org_a)
    notification = request(client, org_a, patient["id"], key="reminder-0009").json()
    assert client.get(f"/api/v1/notifications/{notification['id']}",
                      headers=org_b["ops"]["headers"]).status_code == 404
    assert client.post("/api/v1/notifications", headers=org_b["ops"]["headers"], json={
        "patient_id": patient["id"], "channel": "EMAIL", "template_key": "new_message"}).status_code == 422
    # Another organisation's worker never processes our outbox.
    other_worker = make_worker(client, org_b)
    assert client.post("/api/v1/notifications/process", headers=other_worker).json()["processed"] == 0
    cancelled = client.post(f"/api/v1/notifications/{notification['id']}/cancel", headers=org_a["ops"]["headers"])
    assert cancelled.json()["status"] == "CANCELLED"
