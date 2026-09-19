"""CRM dashboard counts. Every number is computed with the same visibility rules as the
matching list endpoint, so the dashboard never reveals more than the caller could list."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from app.database import get_engine
from app.modules.appointments.service import appointment_scope, organisation_timezone
from app.modules.patients.access import ASSIGNED_TO_CALLER
from app.modules.tasks.service import task_scope
from app.security import has, require

router = APIRouter(prefix="/api/v1", tags=["CRM summary"])


class AppointmentCounts(BaseModel):
    today: int
    upcoming_7_days: int


class TaskCounts(BaseModel):
    open: int
    overdue: int
    due_today: int
    mine_open: int


class RecentPatient(BaseModel):
    id: UUID
    display_name: str
    status: str
    updated_at: datetime


class Summary(BaseModel):
    timezone: str
    appointments: AppointmentCounts | None
    tasks: TaskCounts | None
    recently_updated_assigned_patients: list[RecentPatient] | None


@router.get("/summary", response_model=Summary)
def summary(principal=Depends(require("summary:read")), engine=Depends(get_engine)):
    """Today's and upcoming appointments, open/overdue tasks, and your recently updated assigned
    patients. "Today" is the organisation's local day. A section you have no permission for is
    `null`. **Permission:** `summary:read`."""
    with engine.connect() as db:
        tz = organisation_timezone(db, principal["organisation_id"])
        # Midnight today and tomorrow in the organisation's time zone, as UTC instants.
        day = "date_trunc('day', now() AT TIME ZONE :tz) AT TIME ZONE :tz"
        result = {"timezone": tz, "appointments": None, "tasks": None, "recently_updated_assigned_patients": None}

        if has(principal, "appointments:read"):
            condition, params = appointment_scope(principal)
            result["appointments"] = db.execute(text(f"""
                SELECT count(*) FILTER (WHERE ap.starts_at >= {day} AND ap.starts_at < {day} + interval '1 day'
                                        AND ap.status <> 'CANCELLED') AS today,
                       count(*) FILTER (WHERE ap.starts_at >= now() AND ap.starts_at < now() + interval '7 days'
                                        AND ap.status IN ('SCHEDULED', 'CONFIRMED')) AS upcoming_7_days
                FROM appointments ap WHERE {condition}
            """), dict(params, tz=tz)).mappings().one()

        if has(principal, "tasks:read_all") or has(principal, "tasks:write"):
            condition, params = task_scope(principal)
            result["tasks"] = db.execute(text(f"""
                SELECT count(*) AS open,
                       count(*) FILTER (WHERE t.due_at < now()) AS overdue,
                       count(*) FILTER (WHERE t.due_at >= {day} AND t.due_at < {day} + interval '1 day') AS due_today,
                       count(*) FILTER (WHERE t.owner_user_id = :caller_id) AS mine_open
                FROM tasks t WHERE {condition} AND t.status IN ('OPEN', 'IN_PROGRESS')
            """), dict(params, tz=tz)).mappings().one()

        if has(principal, "patients:read_all") or has(principal, "patients:read_assigned"):
            rows = db.execute(text(f"""
                SELECT p.id, coalesce(p.preferred_name, p.legal_first_name) || ' ' || p.legal_last_name
                           AS display_name, p.status, p.updated_at
                FROM patients p
                WHERE p.organisation_id = :org AND p.status <> 'ARCHIVED'
                  AND p.updated_at > now() - interval '7 days' AND {ASSIGNED_TO_CALLER.format(alias='p')}
                ORDER BY p.updated_at DESC LIMIT 10
            """), {"org": principal["organisation_id"], "caller_id": principal["user_id"]}).mappings().all()
            result["recently_updated_assigned_patients"] = [dict(r) for r in rows]
    return result
