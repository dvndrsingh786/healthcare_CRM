"""Writes rows to the append-only audit_events table.

Two ways to record an event:
- record_event(db, ...)          inside the SAME transaction as the change, so the change and
                                 its audit event are saved together or not at all.
- record_event_now(engine, ...)  in its OWN transaction, for failures and denials. Those requests
                                 end with an error (which rolls back the main transaction), but
                                 the security event must still be kept.

We store which fields changed, never their values, and metadata is filtered so that
passwords, tokens and personal/health data cannot be written here by mistake.
"""
import json

from sqlalchemy import text

from app.context import current_client
from app.logging_setup import is_sensitive_key

SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
DENIED = "DENIED"


def safe_metadata(metadata):
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if not is_sensitive_key(key)}


def _params(actor, action, resource_type, resource_id, outcome, changed_fields, metadata, organisation_id):
    client = current_client()
    if organisation_id is None and actor is not None:
        organisation_id = actor["organisation_id"]
    return {
        "organisation_id": organisation_id,
        "actor_user_id": actor["user_id"] if actor else None,
        "actor_type": actor["user_type"] if actor else "ANONYMOUS",
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "outcome": outcome,
        "changed_fields": sorted(changed_fields) if changed_fields else None,
        "metadata": json.dumps(safe_metadata(metadata), default=str),
        "ip_address": client["ip_address"],
        "user_agent": client["user_agent"],
        "request_id": client["request_id"],
    }


INSERT_SQL = text("""
    INSERT INTO audit_events
        (organisation_id, actor_user_id, actor_type, action, resource_type, resource_id,
         outcome, changed_fields, metadata, ip_address, user_agent, request_id)
    VALUES
        (:organisation_id, :actor_user_id, :actor_type, :action, :resource_type, :resource_id,
         :outcome, :changed_fields, CAST(:metadata AS JSONB), :ip_address, :user_agent, :request_id)
""")


def record_event(db, actor, action, resource_type=None, resource_id=None, outcome=SUCCESS,
                 changed_fields=None, metadata=None, organisation_id=None):
    """actor is the current principal (see app/security.py), or None for anonymous events."""
    db.execute(INSERT_SQL, _params(actor, action, resource_type, resource_id, outcome,
                                   changed_fields, metadata, organisation_id))


def record_event_now(engine, actor, action, resource_type=None, resource_id=None, outcome=FAILURE,
                     changed_fields=None, metadata=None, organisation_id=None):
    with engine.begin() as db:
        record_event(db, actor, action, resource_type, resource_id, outcome,
                     changed_fields, metadata, organisation_id)


def changed_fields(old, new):
    """Names of the fields whose value is different. Values themselves are not returned."""
    return [key for key, value in new.items() if old.get(key) != value]
