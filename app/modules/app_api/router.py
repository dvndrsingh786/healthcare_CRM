"""The patient app's API boundary (/api/v1/app/...).

- Only patient-app sessions (scope `app`, permission `app:self`) can call these routes; CRM tokens
  are refused, and app tokens are refused on every CRM route.
- There is never a patient id in the URL: everything is looked up from the caller's own record.
- Dedicated response models: no internal notes, staff ids, MRN, audit fields or CRM-only records.
- Calls are rate limited per user (APP_RATE_LIMIT_PER_MINUTE).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.database import get_engine
from app.modules.app_api import service
from app.modules.app_api.schemas import DeviceOut, DeviceRegister
from app.modules.appointments.schemas import AppAppointmentList, AppAppointmentOut
from app.modules.consents import service as consents
from app.modules.consents.schemas import AppConsentChange, AppConsentOut
from app.modules.documents import service as documents
from app.modules.documents.schemas import AppDocumentList, DownloadLink
from app.modules.notes.schemas import AppMessageList
from app.modules.notes.service import list_app_messages
from app.modules.patients import service as patients
from app.modules.patients.schemas import AppProfileOut, AppProfileUpdate
from app.pagination import page_params
from app.security import app_principal

router = APIRouter(prefix="/api/v1/app", tags=["Patient app"])


@router.get("/profile", response_model=AppProfileOut)
def get_profile(principal=Depends(app_principal), engine=Depends(get_engine)):
    """Your own patient profile."""
    with engine.connect() as db:
        return patients.find_own_patient(db, principal)


@router.patch("/profile", response_model=AppProfileOut)
def update_profile(data: AppProfileUpdate, principal=Depends(app_principal), engine=Depends(get_engine)):
    """Change your preferred name, phone, language and which channels we may contact you on.
    Legal name, date of birth and address are changed by the care team after checking them."""
    with engine.begin() as db:
        return patients.update_own_profile(db, principal, data.model_dump(exclude_unset=True))


@router.get("/appointments", response_model=AppAppointmentList)
def my_appointments(when: Literal["upcoming", "past"] = "upcoming", paging=Depends(page_params),
                    principal=Depends(app_principal), engine=Depends(get_engine)):
    """Your appointments: upcoming (soonest first) or past (latest first). Internal staff notes
    and CRM-only appointments are never included."""
    with engine.connect() as db:
        patient = patients.find_own_patient(db, principal)
        return service.list_own_appointments(db, patient["id"], paging, when)


@router.get("/appointments/{appointment_id}", response_model=AppAppointmentOut)
def my_appointment(appointment_id: UUID, principal=Depends(app_principal), engine=Depends(get_engine)):
    """One of your appointments. Anything else is 404."""
    with engine.connect() as db:
        patient = patients.find_own_patient(db, principal)
        return service.get_own_appointment(db, principal, patient["id"], appointment_id)


@router.get("/messages", response_model=AppMessageList)
def my_messages(paging=Depends(page_params), principal=Depends(app_principal), engine=Depends(get_engine)):
    """Messages and notes your care team shared with you, newest first."""
    with engine.connect() as db:
        patient = patients.find_own_patient(db, principal)
        return list_app_messages(db, patient["id"], paging)


@router.get("/consents", response_model=list[AppConsentOut])
def my_consents(principal=Depends(app_principal), engine=Depends(get_engine)):
    """The current state of your consents. `changeable_in_app` says which ones you can change here."""
    with engine.connect() as db:
        patient = patients.find_own_patient(db, principal)
        return [consents.app_view(row) for row in consents.current_consents(db, patient["id"])]


@router.post("/consents", status_code=201, response_model=AppConsentOut,
             responses={200: {"model": AppConsentOut, "description": "Already in this state: nothing recorded"}})
def change_consent(data: AppConsentChange, response: Response, principal=Depends(app_principal),
                   engine=Depends(get_engine)):
    """Give or withdraw an app-managed consent (app terms, marketing email/SMS, research contact).
    A new record is added; earlier ones stay as evidence. Sending the current state again changes
    nothing (200), so retries are safe. Other consents are recorded by your care team."""
    with engine.begin() as db:
        patient = patients.find_own_patient(db, principal, lock=True)
        row, created = consents.app_change_consent(db, principal, patient["id"], data)
        if not created:
            response.status_code = 200
        return consents.app_view(row)


@router.get("/documents", response_model=AppDocumentList)
def my_documents(paging=Depends(page_params), principal=Depends(app_principal), engine=Depends(get_engine)):
    """Documents your care team shared with you."""
    with engine.connect() as db:
        patient = patients.find_own_patient(db, principal)
        return service.list_own_documents(db, patient["id"], paging)


@router.post("/documents/{document_id}/download-link", response_model=DownloadLink)
def my_document_link(document_id: UUID, principal=Depends(app_principal), engine=Depends(get_engine)):
    """A short-lived download link for one of your shared documents. Audited."""
    with engine.begin() as db:
        document = documents.find_app_document(db, principal, document_id)
        return documents.create_download_link(db, principal, document, app=True)


@router.post("/devices", status_code=201, response_model=DeviceOut)
def register_device(data: DeviceRegister, principal=Depends(app_principal), engine=Depends(get_engine)):
    """Register this device for push notifications (call again after the token changes)."""
    with engine.begin() as db:
        return service.get_device(db, service.register_device(db, principal, data))


@router.get("/devices", response_model=list[DeviceOut])
def my_devices(principal=Depends(app_principal), engine=Depends(get_engine)):
    """Devices registered for your push notifications."""
    with engine.connect() as db:
        return service.list_devices(db, principal)


@router.delete("/devices/{device_id}", status_code=204)
def revoke_device(device_id: UUID, principal=Depends(app_principal), engine=Depends(get_engine)):
    """Stop push notifications to a device (e.g. a lost phone)."""
    with engine.begin() as db:
        service.revoke_device(db, principal, device_id)
    return Response(status_code=204)
