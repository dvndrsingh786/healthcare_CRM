"""Notification requests, status queries and the outbox worker endpoint."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.database import get_engine
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationCreate,
    NotificationDetail,
    NotificationList,
    NotificationStatus,
    ProcessResult,
)
from app.pagination import page_params
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Notifications"])


@router.post("/notifications", status_code=201, response_model=NotificationDetail,
             responses={200: {"model": NotificationDetail,
                              "description": "Same Idempotency-Key: the existing request"}})
def create_notification(
    data: NotificationCreate,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{8,100}$",
                                         description="Recommended. Retrying with the same key never sends twice"),
    principal=Depends(require("notifications:send")),
    engine=Depends(get_engine),
):
    """Queue a message to a patient you may see. **Permission:** `notifications:send`.

    Messages are template-based; SMS/push/email texts never include clinical details.
    With the same `Idempotency-Key` the first request is returned (200) and nothing new is queued;
    the same key with a different body is 409 `IDEMPOTENCY_KEY_REUSED`.
    """
    with engine.begin() as db:
        notification_id, created = service.create_notification(db, principal, data, idempotency_key)
        if not created:
            response.status_code = 200
        return service.find_notification(db, principal, notification_id)


@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    patient_id: UUID | None = None,
    status: NotificationStatus | None = None,
    reference_type: str | None = Query(None, max_length=30),
    reference_id: UUID | None = None,
    sort: str | None = Query(None, description="created_at, updated_at (prefix - for descending)"),
    paging=Depends(page_params),
    principal=Depends(require("notifications:read")),
    engine=Depends(get_engine),
):
    """Delivery status of messages to patients you may see. **Permission:** `notifications:read`."""
    with engine.connect() as db:
        return service.list_notifications(db, principal, paging, patient_id, status, reference_type, reference_id,
                                          sort)


@router.get("/notifications/{notification_id}", response_model=NotificationDetail)
def get_notification(notification_id: UUID, principal=Depends(require("notifications:read")),
                     engine=Depends(get_engine)):
    """One message with its delivery attempts. **Permission:** `notifications:read`."""
    with engine.connect() as db:
        return service.find_notification(db, principal, notification_id)


@router.post("/notifications/{notification_id}/cancel", response_model=NotificationDetail)
def cancel_notification(notification_id: UUID, principal=Depends(require("notifications:send")),
                        engine=Depends(get_engine)):
    """Stop a message that is still queued. **Permission:** `notifications:send`."""
    with engine.begin() as db:
        service.cancel_notification(db, principal, notification_id)
        return service.find_notification(db, principal, notification_id)


@router.post("/notifications/process", response_model=ProcessResult)
def process_notifications(limit: int = Query(50, ge=1, le=500),
                          principal=Depends(require("notifications:process")), engine=Depends(get_engine)):
    """Send due messages of your organisation (outbox worker). Safe to run in parallel and to retry.

    **Permission:** `notifications:process` (the NOTIFICATION_WORKER service account, via `X-API-Key`).
    Also available as `python manage.py process-notifications`.
    """
    return service.process_due(engine, principal, limit)
