"""CRM tasks / follow-ups.

Who sees a task:
- tasks:read_all       -> every task of the organisation
- otherwise            -> tasks you own or created, and tasks about patients you may see
Who may change a task: tasks:write, and either tasks:read_all or being its owner/creator.
(Care staff can see follow-ups on their patients but only work on their own.)

Status rules: OPEN <-> IN_PROGRESS (PATCH), OPEN/IN_PROGRESS -> DONE (complete) or CANCELLED,
DONE/CANCELLED -> OPEN (reopen). Completion always records completed_at and completed_by.
"""
from sqlalchemy import text

from app.audit import changed_fields, record_event
from app.errors import ApiError, conflict, forbidden, invalid, not_found
from app.modules.appointments.service import appointment_scope
from app.modules.patients.access import check_patient_link, log_denied_access, visible_patient_condition
from app.modules.users.service import active_staff
from app.pagination import order_by, paginate
from app.security import has

OPEN_STATUSES = ("OPEN", "IN_PROGRESS")

TASK_SELECT = """
    SELECT t.*, sp.display_name AS owner_display_name,
           coalesce(t.status IN ('OPEN', 'IN_PROGRESS') AND t.due_at < now(), false) AS is_overdue
    FROM tasks t
    LEFT JOIN staff_profiles sp ON sp.user_id = t.owner_user_id
"""

EDITABLE_COLUMNS = {"title", "description", "owner_user_id", "priority", "due_at", "status"}
PRIORITY_ORDER = "CASE t.priority WHEN 'URGENT' THEN 4 WHEN 'HIGH' THEN 3 WHEN 'NORMAL' THEN 2 ELSE 1 END"


def task_scope(principal, alias="t"):
    params = {"org": principal["organisation_id"], "caller_id": principal["user_id"]}
    if has(principal, "tasks:read_all"):
        return f"{alias}.organisation_id = :org", params
    patient_visible, patient_params = visible_patient_condition(principal, f"{alias}.patient_id")
    params.update(patient_params)
    return (f"{alias}.organisation_id = :org AND ({alias}.owner_user_id = :caller_id "
            f"OR {alias}.created_by = :caller_id OR ({alias}.patient_id IS NOT NULL AND {patient_visible}))", params)


def find_task(db, principal, task_id, lock=False):
    condition, params = task_scope(principal)
    row = db.execute(text(f"{TASK_SELECT} WHERE t.id = :id AND {condition}" + (" FOR UPDATE OF t" if lock else "")),
                     dict(params, id=task_id)).mappings().first()
    if row is None:
        log_denied_access(db, principal, "task", task_id)
        raise not_found("Task")
    return row


def find_task_to_change(db, principal, task_id):
    task = find_task(db, principal, task_id, lock=True)
    caller = str(principal["user_id"])
    if not (has(principal, "tasks:read_all") or caller in (str(task["owner_user_id"]), str(task["created_by"]))):
        raise forbidden("Only the task owner, its creator or a coordinator can change this task.")
    return task


def check_owner(db, principal, owner_user_id):
    try:
        active_staff(db, principal["organisation_id"], owner_user_id)
    except ApiError as error:
        raise invalid("The owner must be an active staff member of your organisation.",
                      field="owner_user_id") from error


def resolve_links(db, principal, patient_id, appointment_id):
    """The patient and appointment must be ones the caller can see, and must match each other."""
    if appointment_id is not None:
        condition, params = appointment_scope(principal)
        appointment = db.execute(
            text(f"SELECT ap.id, ap.patient_id FROM appointments ap WHERE ap.id = :id AND {condition}"),
            dict(params, id=appointment_id)).mappings().first()
        if appointment is None:
            log_denied_access(db, principal, "appointment", appointment_id)
            raise invalid("No such appointment in your organisation, or you do not have access to it.",
                          field="appointment_id")
        if patient_id is not None and str(patient_id) != str(appointment["patient_id"]):
            raise invalid("The appointment belongs to a different patient.", field="appointment_id")
        patient_id = appointment["patient_id"]
    elif patient_id is not None:
        check_patient_link(db, principal, patient_id)
    return patient_id


def create_task(db, principal, data):
    owner = data.owner_user_id or principal["user_id"]
    check_owner(db, principal, owner)
    patient_id = resolve_links(db, principal, data.patient_id, data.appointment_id)
    task_id = db.execute(
        text("""
            INSERT INTO tasks (organisation_id, patient_id, appointment_id, owner_user_id, title, description,
                               priority, due_at, created_by, updated_by)
            VALUES (:org, :patient_id, :appointment_id, :owner, :title, :description, :priority, :due_at, :by, :by)
            RETURNING id
        """),
        {"org": principal["organisation_id"], "patient_id": patient_id, "appointment_id": data.appointment_id,
         "owner": owner, "title": data.title, "description": data.description, "priority": data.priority,
         "due_at": data.due_at, "by": principal["user_id"]},
    ).scalar_one()
    record_event(db, principal, "task.create", "task", task_id,
                 metadata={"owner_user_id": str(owner), "patient_id": str(patient_id) if patient_id else None})
    return task_id


def list_tasks(db, principal, paging, owner_user_id=None, patient_id=None, appointment_id=None, status=None,
               priority=None, due_before=None, due_after=None, overdue=False, sort=None):
    condition, params = task_scope(principal)
    conditions = [condition]
    for column, value in {"owner_user_id": owner_user_id, "patient_id": patient_id,
                          "appointment_id": appointment_id, "priority": priority}.items():
        if value is not None:
            conditions.append(f"t.{column} = :f_{column}")
            params[f"f_{column}"] = value
    if status == "open":
        conditions.append("t.status IN ('OPEN', 'IN_PROGRESS')")
    elif status is not None:
        conditions.append("t.status = :f_status")
        params["f_status"] = status.upper()
    if overdue:
        conditions.append("t.status IN ('OPEN', 'IN_PROGRESS') AND t.due_at < now()")
    if due_before is not None:
        conditions.append("t.due_at < :due_before")
        params["due_before"] = due_before
    if due_after is not None:
        conditions.append("t.due_at >= :due_after")
        params["due_after"] = due_after

    where = " AND ".join(conditions)
    sortable = {"due_at": "t.due_at", "created_at": "t.created_at", "updated_at": "t.updated_at",
                "priority": PRIORITY_ORDER}
    return paginate(db, f"{TASK_SELECT} WHERE {where} {order_by(sort, sortable, 'due_at', 't.id')}",
                    f"SELECT count(*) FROM tasks t WHERE {where}", params, paging)


def update_task(db, principal, task_id, changes):
    version = changes.pop("version")
    old = find_task_to_change(db, principal, task_id)
    if old["status"] not in OPEN_STATUSES:
        raise ApiError(409, "INVALID_STATE", "Reopen the task before editing it.")
    if old["version"] != version:
        raise conflict("This task was changed by someone else. Reload it and try again.", code="VERSION_CONFLICT")
    changes = {column: value for column, value in changes.items() if column in EDITABLE_COLUMNS}
    if changes.get("owner_user_id") is not None:
        check_owner(db, principal, changes["owner_user_id"])
    changed = changed_fields(old, changes)
    if not changed:
        return
    sets = ", ".join(f"{column} = :{column}" for column in changed)
    db.execute(text(f"UPDATE tasks SET {sets}, version = version + 1, updated_by = :by WHERE id = :id"),
               dict({c: changes[c] for c in changed}, by=principal["user_id"], id=task_id))
    record_event(db, principal, "task.update", "task", task_id, changed_fields=changed)


def complete_task(db, principal, task_id):
    task = find_task_to_change(db, principal, task_id)
    if task["status"] not in OPEN_STATUSES:
        raise ApiError(409, "INVALID_TRANSITION", f"A {task['status']} task cannot be completed.")
    db.execute(text("UPDATE tasks SET status = 'DONE', completed_at = now(), completed_by = :by, "
                    "version = version + 1, updated_by = :by WHERE id = :id"),
               {"by": principal["user_id"], "id": task_id})
    record_event(db, principal, "task.complete", "task", task_id, changed_fields=["status"])


def cancel_task(db, principal, task_id):
    task = find_task_to_change(db, principal, task_id)
    if task["status"] not in OPEN_STATUSES:
        raise ApiError(409, "INVALID_TRANSITION", f"A {task['status']} task cannot be cancelled.")
    db.execute(text("UPDATE tasks SET status = 'CANCELLED', version = version + 1, updated_by = :by WHERE id = :id"),
               {"by": principal["user_id"], "id": task_id})
    record_event(db, principal, "task.cancel", "task", task_id, changed_fields=["status"])


def reopen_task(db, principal, task_id):
    task = find_task_to_change(db, principal, task_id)
    if task["status"] in OPEN_STATUSES:
        raise ApiError(409, "INVALID_TRANSITION", "The task is already open.")
    db.execute(text("UPDATE tasks SET status = 'OPEN', completed_at = NULL, completed_by = NULL, "
                    "version = version + 1, updated_by = :by WHERE id = :id"),
               {"by": principal["user_id"], "id": task_id})
    record_event(db, principal, "task.reopen", "task", task_id, changed_fields=["status"],
                 metadata={"from_status": task["status"]})
