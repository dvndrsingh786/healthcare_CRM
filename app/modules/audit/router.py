"""Audit log search for administrators / security review.

The log is append-only (a database trigger rejects UPDATE and DELETE), holds field names and ids
rather than personal data, and every search of it is itself audited.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.audit import record_event
from app.database import get_engine
from app.pagination import order_by, page_params, paginate
from app.schemas import AwareDateTime, Page
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Audit"])


class AuditEventOut(BaseModel):
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    changed_fields: list[str] | None
    metadata: dict
    ip_address: str | None
    user_agent: str | None
    request_id: str | None


class AuditEventList(Page):
    data: list[AuditEventOut]


@router.get("/audit-events", response_model=AuditEventList)
def search_audit_events(
    actor_user_id: UUID | None = None,
    action: str | None = Query(None, max_length=60, description="Exact action, or a prefix ending in * "
                                                                "(e.g. patient.* or access.denied)"),
    resource_type: str | None = Query(None, max_length=40),
    resource_id: str | None = Query(None, max_length=64),
    outcome: Literal["SUCCESS", "FAILURE", "DENIED"] | None = None,
    occurred_from: AwareDateTime | None = Query(None, alias="from"),
    occurred_before: AwareDateTime | None = Query(None, alias="to"),
    sort: str | None = Query(None, description="occurred_at (prefix - for newest first, the default)"),
    paging=Depends(page_params),
    principal=Depends(require("audit:read")),
    engine=Depends(get_engine),
):
    """Filter your organisation's audit events by actor, action, resource, outcome and time.
    This search is itself recorded as `audit.search`. **Permission:** `audit:read`."""
    conditions = ["a.organisation_id = :org"]
    params = {"org": principal["organisation_id"]}
    filters = {"actor_user_id": actor_user_id, "resource_type": resource_type, "resource_id": resource_id,
               "outcome": outcome}
    for column, value in filters.items():
        if value is not None:
            conditions.append(f"a.{column} = :f_{column}")
            params[f"f_{column}"] = value
    if action:
        if action.endswith("*"):
            conditions.append("a.action LIKE :f_action")
            params["f_action"] = action[:-1].replace("%", r"\%").replace("_", r"\_") + "%"
        else:
            conditions.append("a.action = :f_action")
            params["f_action"] = action
    if occurred_from:
        conditions.append("a.occurred_at >= :occurred_from")
        params["occurred_from"] = occurred_from
    if occurred_before:
        conditions.append("a.occurred_at < :occurred_before")
        params["occurred_before"] = occurred_before
    where = " AND ".join(conditions)

    with engine.begin() as db:
        page = paginate(db, f"SELECT a.* FROM audit_events a WHERE {where} "
                            f"{order_by(sort, {'occurred_at': 'a.occurred_at'}, '-occurred_at', 'a.id')}",
                        f"SELECT count(*) FROM audit_events a WHERE {where}", params, paging)
        record_event(db, principal, "audit.search", metadata={
            "filters": {k: str(v) for k, v in {**filters, "action": action, "from": occurred_from,
                                               "to": occurred_before}.items() if v is not None},
            "results": page["meta"]["total"]})
    return page
