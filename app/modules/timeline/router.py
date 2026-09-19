"""The patient timeline: one chronological list built from appointments, notes, tasks, documents
and consent changes. Each source is included only if the caller has its read permission, and
each uses the same visibility rules as its own endpoint, so restricted entries (e.g. CLINICAL
notes for a coordinator) never appear here either.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.audit import record_event
from app.database import get_engine
from app.modules.patients.access import find_patient, readable_visibilities, visibility_condition
from app.modules.tasks.service import task_scope
from app.pagination import page_params, paginate
from app.schemas import AwareDateTime, Page
from app.security import has, require_any

router = APIRouter(prefix="/api/v1", tags=["Timeline"])

EntryType = Literal["appointment", "note", "task", "document", "consent"]


class TimelineEntry(BaseModel):
    entry_type: EntryType
    id: UUID
    occurred_at: datetime
    title: str
    summary: str | None
    status: str | None
    visibility: str | None
    actor_name: str | None


class Timeline(Page):
    data: list[TimelineEntry]


def sources(principal):
    """(entry_type, SELECT ..., params) for every source the caller may read."""
    parts = []
    if has(principal, "appointments:read"):
        parts.append(("appointment", """
            SELECT 'appointment' AS entry_type, ap.id, ap.starts_at AS occurred_at,
                   replace(ap.appointment_type, '_', ' ') || ' (' || ap.mode || ')' AS title,
                   ap.location AS summary, ap.status, NULL AS visibility, sp.display_name AS actor_name
            FROM appointments ap LEFT JOIN staff_profiles sp ON sp.user_id = ap.staff_user_id
            WHERE ap.patient_id = :patient_id""", {}))
    note_classes = readable_visibilities(principal, "notes:read")
    if note_classes:
        parts.append(("note", f"""
            SELECT 'note' AS entry_type, n.id, n.occurred_at, n.subject AS title, left(n.body, 200) AS summary,
                   n.status, n.visibility, sp.display_name AS actor_name
            FROM notes n LEFT JOIN staff_profiles sp ON sp.user_id = n.author_user_id
            WHERE n.patient_id = :patient_id AND {visibility_condition('n.visibility', note_classes)}""", {}))
    if has(principal, "tasks:read_all") or has(principal, "tasks:write"):
        condition, params = task_scope(principal)
        parts.append(("task", f"""
            SELECT 'task' AS entry_type, t.id, t.created_at AS occurred_at, t.title, NULL AS summary, t.status,
                   NULL AS visibility, sp.display_name AS actor_name
            FROM tasks t LEFT JOIN staff_profiles sp ON sp.user_id = t.owner_user_id
            WHERE t.patient_id = :patient_id AND {condition}""", params))
    document_classes = readable_visibilities(principal, "documents:read")
    if document_classes:
        parts.append(("document", f"""
            SELECT 'document' AS entry_type, d.id, d.uploaded_at AS occurred_at,
                   coalesce(d.title, d.original_filename) AS title, d.category AS summary, d.status, d.visibility,
                   sp.display_name AS actor_name
            FROM documents d LEFT JOIN staff_profiles sp ON sp.user_id = d.uploaded_by
            WHERE d.patient_id = :patient_id AND d.status IN ('AVAILABLE', 'ARCHIVED')
              AND {visibility_condition('d.visibility', document_classes)}""", {}))
    if has(principal, "consents:read"):
        parts.append(("consent", """
            SELECT 'consent' AS entry_type, c.id, c.recorded_at AS occurred_at,
                   replace(c.consent_type, '_', ' ') || ': ' || c.status AS title,
                   'Source: ' || c.source || ', policy ' || c.policy_version AS summary, c.status,
                   NULL AS visibility, sp.display_name AS actor_name
            FROM consent_records c LEFT JOIN staff_profiles sp ON sp.user_id = c.captured_by
            WHERE c.patient_id = :patient_id""", {}))
    return parts


@router.get("/patients/{patient_id}/timeline", response_model=Timeline)
def timeline(
    patient_id: UUID,
    types: list[EntryType] | None = Query(None, description="Only these entry types (repeat the parameter)"),
    occurred_from: AwareDateTime | None = Query(None, alias="from"),
    occurred_before: AwareDateTime | None = Query(None, alias="to"),
    order: Literal["desc", "asc"] = "desc",
    paging=Depends(page_params),
    principal=Depends(require_any("patients:read_all", "patients:read_assigned")),
    engine=Depends(get_engine),
):
    """Chronological history of a patient you may see, newest first by default. Entries you may
    not read (e.g. restricted notes) are left out entirely. **Permission:** can see the patient;
    each entry type additionally needs its own read permission."""
    with engine.begin() as db:
        find_patient(db, principal, patient_id)
        # A timeline read shows a lot of the record at once, so it is audited like a patient read.
        record_event(db, principal, "patient.timeline_read", "patient", patient_id,
                     metadata={"clinical": "CLINICAL" in readable_visibilities(principal, "notes:read")})
        parts = [part for part in sources(principal) if not types or part[0] in types]
        if not parts:
            return {"data": [], "meta": {"page": paging.page, "page_size": paging.page_size, "total": 0,
                                         "total_pages": 0}}
        params = {"patient_id": patient_id, "org": principal["organisation_id"], "caller_id": principal["user_id"]}
        for _, _, part_params in parts:
            params.update(part_params)
        union = " UNION ALL ".join(sql for _, sql, _ in parts)
        where = ["e.occurred_at IS NOT NULL"]
        if occurred_from:
            where.append("e.occurred_at >= :occurred_from")
            params["occurred_from"] = occurred_from
        if occurred_before:
            where.append("e.occurred_at < :occurred_before")
            params["occurred_before"] = occurred_before
        base = f"FROM ({union}) e WHERE {' AND '.join(where)}"
        direction = "DESC" if order == "desc" else "ASC"
        return paginate(db, f"SELECT e.* {base} ORDER BY e.occurred_at {direction}, e.id {direction}",
                        f"SELECT count(*) {base}", params, paging)
