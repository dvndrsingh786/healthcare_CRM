"""Notification outbox: queue in the business transaction, send later from a worker.

Delivery guarantees
- Queuing happens in the same transaction as the business change, so it is all-or-nothing.
- Every row has an idempotency key, unique per organisation. Queuing the same thing twice
  (a retried HTTP request, a double click) returns the existing row instead of a second message.
- The worker leases rows (locked_until) with FOR UPDATE SKIP LOCKED, so parallel workers never
  pick the same row. The provider gets the notification id as ITS idempotency key, so if a worker
  dies after the provider accepted a message, the retry is not delivered twice.
- A provider failure is recorded (notification_attempts, last_error_code) and retried with
  exponential backoff, up to max_attempts; then the row is FAILED. The business record that
  caused it (e.g. the appointment) is never affected.
"""
import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import text

from app.audit import FAILURE, record_event
from app.config import get_settings
from app.errors import ApiError, conflict, invalid, not_found
from app.messaging import OutgoingMessage, ProviderError, get_provider
from app.modules.notifications.templates import TEMPLATES, render
from app.modules.patients.access import check_patient_link, log_denied_access, visible_patient_condition
from app.pagination import order_by, paginate

LEASE = timedelta(minutes=2)
MAX_BACKOFF_SECONDS = 3600


def backoff_seconds(attempts):
    # 1st retry after 30 s, then 60, 120, 240 ... capped at one hour.
    return min(30 * 2 ** (attempts - 1), MAX_BACKOFF_SECONDS)


def load_contact(db, patient_id):
    return db.execute(
        text("""
            SELECT p.id, p.email, p.phone, p.app_user_id, p.status, p.contact_by_email, p.contact_by_sms,
                   p.contact_by_push, o.name AS organisation_name, o.settings
            FROM patients p JOIN organisations o ON o.id = p.organisation_id
            WHERE p.id = :id
        """),
        {"id": patient_id},
    ).mappings().one()


def opted_in(contact, channel):
    return contact[f"contact_by_{channel.lower()}"]


def transactional_overrides_opt_out(contact):
    return contact["settings"].get("notifications", {}).get("transactional_ignores_opt_out", True)


def has_address(db, contact, channel):
    if channel == "EMAIL":
        return bool(contact["email"])
    if channel == "SMS":
        return bool(contact["phone"])
    return bool(contact["app_user_id"]) and bool(active_devices(db, contact["app_user_id"]))


def active_devices(db, user_id):
    return db.execute(
        text("SELECT id, push_token FROM device_tokens WHERE user_id = :u AND revoked_at IS NULL "
             "ORDER BY last_seen_at DESC LIMIT 10"),
        {"u": user_id},
    ).mappings().all()


def insert_notification(db, principal, patient_id, channel, template_key, idempotency_key, reference_type=None,
                        reference_id=None, scheduled_at=None, request_hash=None):
    """Returns (id, created). created is False when the idempotency key already existed."""
    template = TEMPLATES[template_key]
    new_id = db.execute(
        text("""
            INSERT INTO notifications (organisation_id, patient_id, channel, template_key, reference_type,
                                       reference_id, transactional, max_attempts, scheduled_at, next_attempt_at,
                                       idempotency_key, request_hash, created_by)
            VALUES (:org, :patient_id, :channel, :template_key, :reference_type, :reference_id, :transactional,
                    :max_attempts, coalesce(:scheduled_at, now()), coalesce(:scheduled_at, now()),
                    :key, :request_hash, :by)
            ON CONFLICT (organisation_id, idempotency_key) DO NOTHING
            RETURNING id
        """),
        {"org": principal["organisation_id"], "patient_id": patient_id, "channel": channel,
         "template_key": template_key, "reference_type": reference_type, "reference_id": reference_id,
         "transactional": template.transactional, "max_attempts": get_settings().notification_max_attempts,
         "scheduled_at": scheduled_at, "key": idempotency_key, "request_hash": request_hash,
         "by": principal["user_id"]},
    ).scalar()
    if new_id is not None:
        return new_id, True
    existing = db.execute(
        text("SELECT id, request_hash FROM notifications WHERE organisation_id = :org AND idempotency_key = :key"),
        {"org": principal["organisation_id"], "key": idempotency_key},
    ).mappings().one()
    if request_hash is not None and existing["request_hash"] != request_hash:
        raise conflict("This Idempotency-Key was already used for a different request.",
                       code="IDEMPOTENCY_KEY_REUSED")
    return existing["id"], False


def queue_patient_notification(db, principal, patient_id, template_key, reference_type, reference_id, event_key):
    """Automatic messages (appointment booked/changed/cancelled...). Goes to every channel the
    patient opted into and can be reached on. If none, a transactional message falls back to one
    reachable channel when the organisation's policy allows it."""
    contact = load_contact(db, patient_id)
    if contact["status"] != "ACTIVE":
        return []
    channels = [c for c in ("PUSH", "EMAIL", "SMS") if opted_in(contact, c) and has_address(db, contact, c)]
    if not channels and TEMPLATES[template_key].transactional and transactional_overrides_opt_out(contact):
        channels = [c for c in ("PUSH", "EMAIL", "SMS") if has_address(db, contact, c)][:1]
    ids = []
    for channel in channels:
        key = f"{reference_type}:{reference_id}:{event_key}:{channel}"
        notification_id, _ = insert_notification(db, principal, patient_id, channel, template_key, key,
                                                 reference_type, reference_id)
        ids.append(notification_id)
    return ids


# ---------- CRM API ----------

def request_hash(data):
    return hashlib.sha256(json.dumps(data.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def create_notification(db, principal, data, idempotency_key):
    """Returns (id, created)."""
    check_patient_link(db, principal, data.patient_id)
    if data.reference_type == "appointment" and data.reference_id is not None:
        belongs = db.execute(text("SELECT 1 FROM appointments WHERE id = :id AND patient_id = :p"),
                             {"id": data.reference_id, "p": data.patient_id}).first()
        if not belongs:
            raise invalid("The appointment does not belong to this patient.", field="reference_id")
    key = f"api:{idempotency_key}" if idempotency_key else f"api:auto-{secrets.token_hex(16)}"
    notification_id, created = insert_notification(
        db, principal, data.patient_id, data.channel, data.template_key, key, data.reference_type,
        data.reference_id, data.scheduled_at, request_hash(data))
    if created:
        record_event(db, principal, "notification.request", "notification", notification_id,
                     metadata={"patient_id": str(data.patient_id), "channel": data.channel,
                               "template_key": data.template_key})
    return notification_id, created


def notification_scope(principal, alias="n"):
    patient_visible, params = visible_patient_condition(principal, f"{alias}.patient_id")
    return f"{alias}.organisation_id = :org AND {patient_visible}", params


def find_notification(db, principal, notification_id):
    condition, params = notification_scope(principal)
    row = db.execute(text(f"SELECT n.* FROM notifications n WHERE n.id = :id AND {condition}"),
                     dict(params, id=notification_id)).mappings().first()
    if row is None:
        log_denied_access(db, principal, "notification", notification_id)
        raise not_found("Notification")
    attempts = db.execute(
        text("SELECT attempt_number, outcome, error_code, attempted_at FROM notification_attempts "
             "WHERE notification_id = :id ORDER BY attempt_number"), {"id": notification_id}).mappings()
    return dict(row, attempt_log=[dict(a) for a in attempts])


def list_notifications(db, principal, paging, patient_id=None, status=None, reference_type=None,
                       reference_id=None, sort=None):
    condition, params = notification_scope(principal)
    conditions = [condition]
    for column, value in {"patient_id": patient_id, "status": status, "reference_type": reference_type,
                          "reference_id": reference_id}.items():
        if value is not None:
            conditions.append(f"n.{column} = :f_{column}")
            params[f"f_{column}"] = value
    where = " AND ".join(conditions)
    sortable = {"created_at": "n.created_at", "updated_at": "n.updated_at"}
    return paginate(db, f"SELECT n.* FROM notifications n WHERE {where} "
                        f"{order_by(sort, sortable, '-created_at', 'n.id')}",
                    f"SELECT count(*) FROM notifications n WHERE {where}", params, paging)


def cancel_notification(db, principal, notification_id):
    find_notification(db, principal, notification_id)
    cancelled = db.execute(
        text("UPDATE notifications SET status = 'CANCELLED', locked_until = NULL "
             "WHERE id = :id AND status = 'QUEUED' RETURNING id"), {"id": notification_id}).first()
    if cancelled is None:
        raise ApiError(409, "INVALID_STATE", "Only queued notifications can be cancelled.")
    record_event(db, principal, "notification.cancel", "notification", notification_id)


# ---------- Worker ----------

def claim_due(engine, organisation_id, limit):
    """Lease up to `limit` due rows of one organisation. Committed immediately, so the lease is
    visible to other workers while we talk to the provider (outside any transaction)."""
    with engine.begin() as db:
        return db.execute(
            text("""
                UPDATE notifications SET status = 'SENDING', attempts = attempts + 1,
                       locked_until = now() + make_interval(secs => :lease)
                WHERE id IN (
                    SELECT id FROM notifications
                    WHERE organisation_id = :org
                      AND ((status = 'QUEUED' AND next_attempt_at <= now())
                           OR (status = 'SENDING' AND locked_until < now()))
                    ORDER BY next_attempt_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """),
            {"org": organisation_id, "limit": limit, "lease": LEASE.total_seconds()},
        ).mappings().all()


def build_messages(db, row):
    """The messages to hand to the provider, or a skip reason. Addresses are read now, not stored."""
    contact = load_contact(db, row["patient_id"])
    channel = row["channel"]
    if contact["status"] != "ACTIVE":
        return None, "PATIENT_NOT_ACTIVE"
    if not opted_in(contact, channel) and not (row["transactional"] and transactional_overrides_opt_out(contact)):
        return None, "OPTED_OUT"
    subject, body = render(row["template_key"], contact["organisation_name"])

    def message(to, key):
        return OutgoingMessage(channel=channel, to=to, template_key=row["template_key"], subject=subject,
                               body=body, idempotency_key=key)

    if channel == "EMAIL":
        return ([message(contact["email"], str(row["id"]))], None) if contact["email"] else (None, "NO_ADDRESS")
    if channel == "SMS":
        return ([message(contact["phone"], str(row["id"]))], None) if contact["phone"] else (None, "NO_ADDRESS")
    devices = active_devices(db, contact["app_user_id"]) if contact["app_user_id"] else []
    if not devices:
        return None, "NO_ADDRESS"
    return [message(d["push_token"], f"{row['id']}:{d['id']}") for d in devices], None


def finish(engine, principal, row, outcome, error_code=None, provider_message_id=None, skip_reason=None, retry=False):
    with engine.begin() as db:
        if outcome == "SENT":
            db.execute(text("UPDATE notifications SET status = 'SENT', sent_at = now(), locked_until = NULL, "
                            "provider_message_id = :pid, last_error_code = NULL WHERE id = :id"),
                       {"pid": provider_message_id, "id": row["id"]})
        elif outcome == "SKIPPED":
            db.execute(text("UPDATE notifications SET status = 'SKIPPED', skip_reason = :reason, locked_until = NULL "
                            "WHERE id = :id"), {"reason": skip_reason, "id": row["id"]})
        elif retry:
            db.execute(text("UPDATE notifications SET status = 'QUEUED', locked_until = NULL, last_error_code = :code, "
                            "next_attempt_at = now() + make_interval(secs => :delay) WHERE id = :id"),
                       {"code": error_code, "delay": backoff_seconds(row["attempts"]), "id": row["id"]})
        else:
            db.execute(text("UPDATE notifications SET status = 'FAILED', locked_until = NULL, last_error_code = :code "
                            "WHERE id = :id"), {"code": error_code, "id": row["id"]})
        db.execute(
            text("""INSERT INTO notification_attempts (notification_id, attempt_number, outcome, error_code,
                                                       provider_message_id)
                    VALUES (:id, :n, :outcome, :code, :pid)"""),
            {"id": row["id"], "n": row["attempts"], "outcome": "FAILED" if outcome == "FAILED" else outcome,
             "code": error_code or skip_reason, "pid": provider_message_id},
        )
        if outcome == "FAILED" and not retry:
            record_event(db, principal, "notification.failed", "notification", row["id"], outcome=FAILURE,
                         organisation_id=row["organisation_id"], metadata={"error_code": error_code})


def process_due(engine, principal, limit=50):
    """Send what is due for the caller's organisation. Returns counts per outcome.
    principal is the worker (service account) and is the audit identity for failures."""
    counts = {"processed": 0, "sent": 0, "retry_scheduled": 0, "failed": 0, "skipped": 0}
    provider = get_provider()
    for row in claim_due(engine, principal["organisation_id"], limit):
        counts["processed"] += 1
        with engine.connect() as db:
            messages, skip_reason = build_messages(db, row)
        if messages is None:
            finish(engine, principal, row, "SKIPPED", skip_reason=skip_reason)
            counts["skipped"] += 1
            continue
        try:
            provider_ids = [provider.send(message) for message in messages]
        except ProviderError as error:
            retry = error.temporary and row["attempts"] < row["max_attempts"]
            finish(engine, principal, row, "FAILED", error_code=error.code, retry=retry)
            counts["retry_scheduled" if retry else "failed"] += 1
            continue
        except Exception:  # an unexpected provider bug must not stop the whole batch
            retry = row["attempts"] < row["max_attempts"]
            finish(engine, principal, row, "FAILED", error_code="PROVIDER_ERROR", retry=retry)
            counts["retry_scheduled" if retry else "failed"] += 1
            continue
        finish(engine, principal, row, "SENT", provider_message_id=provider_ids[0])
        counts["sent"] += 1
    return counts
