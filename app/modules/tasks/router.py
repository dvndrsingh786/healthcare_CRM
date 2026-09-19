"""CRM tasks / follow-ups."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.database import get_engine
from app.errors import invalid
from app.modules.tasks import service
from app.modules.tasks.schemas import Priority, TaskCreate, TaskList, TaskOut, TaskUpdate
from app.pagination import page_params
from app.schemas import AwareDateTime
from app.security import require, require_any

router = APIRouter(prefix="/api/v1", tags=["Tasks"])

can_read_tasks = require_any("tasks:read_all", "tasks:write")


@router.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(data: TaskCreate, principal=Depends(require("tasks:write")), engine=Depends(get_engine)):
    """Create a follow-up for yourself or another staff member, optionally about a patient or an
    appointment you may see. **Permission:** `tasks:write`."""
    with engine.begin() as db:
        task_id = service.create_task(db, principal, data)
        return service.find_task(db, principal, task_id)


@router.get("/tasks", response_model=TaskList)
def list_tasks(
    owner: str | None = Query(None, description="A staff user id, or `me`"),
    patient_id: UUID | None = None,
    appointment_id: UUID | None = None,
    status: Literal["open", "in_progress", "done", "cancelled", "OPEN", "IN_PROGRESS", "DONE", "CANCELLED"]
    | None = Query(None, description="`open` = OPEN or IN_PROGRESS (work still to do)"),
    priority: Priority | None = None,
    due_before: AwareDateTime | None = None,
    due_after: AwareDateTime | None = None,
    overdue: bool = Query(False, description="Only open tasks whose due time has passed"),
    sort: str | None = Query(None, description="due_at, priority, created_at, updated_at (prefix - for "
                                               "descending). Default due_at"),
    paging=Depends(page_params),
    principal=Depends(can_read_tasks),
    engine=Depends(get_engine),
):
    """Tasks you may see (all tasks with `tasks:read_all`; otherwise yours and those about your
    patients). **Permission:** `tasks:read_all` or `tasks:write`."""
    owner_user_id = None
    if owner == "me":
        owner_user_id = principal["user_id"]
    elif owner:
        try:
            owner_user_id = UUID(owner)
        except ValueError:
            raise invalid("owner must be a user id or 'me'.", field="owner") from None
    with engine.connect() as db:
        return service.list_tasks(db, principal, paging, owner_user_id, patient_id, appointment_id,
                                  status.lower() if status else None,
                                  priority, due_before, due_after, overdue, sort)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: UUID, principal=Depends(can_read_tasks), engine=Depends(get_engine)):
    """One task. **Permission:** `tasks:read_all` or `tasks:write`."""
    with engine.connect() as db:
        return service.find_task(db, principal, task_id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: UUID, data: TaskUpdate, principal=Depends(require("tasks:write")),
                engine=Depends(get_engine)):
    """Edit an open task, reassign it, or move it between OPEN and IN_PROGRESS. Send the `version`
    you read. **Permission:** `tasks:write` (owner, creator or `tasks:read_all`)."""
    with engine.begin() as db:
        service.update_task(db, principal, task_id, data.model_dump(exclude_unset=True))
        return service.find_task(db, principal, task_id)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: UUID, principal=Depends(require("tasks:write")), engine=Depends(get_engine)):
    """Mark done. Records who completed it and when. **Permission:** `tasks:write`."""
    with engine.begin() as db:
        service.complete_task(db, principal, task_id)
        return service.find_task(db, principal, task_id)


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: UUID, principal=Depends(require("tasks:write")), engine=Depends(get_engine)):
    """Reopen a done or cancelled task. **Permission:** `tasks:write`."""
    with engine.begin() as db:
        service.reopen_task(db, principal, task_id)
        return service.find_task(db, principal, task_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: UUID, principal=Depends(require("tasks:write")), engine=Depends(get_engine)):
    """Cancel an open task. **Permission:** `tasks:write`."""
    with engine.begin() as db:
        service.cancel_task(db, principal, task_id)
        return service.find_task(db, principal, task_id)
