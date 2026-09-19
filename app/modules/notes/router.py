"""Interactions / notes on a patient."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.database import get_engine
from app.modules.notes import service
from app.modules.notes.schemas import (
    NoteCreate,
    NoteList,
    NoteOut,
    NoteRevisionOut,
    NoteType,
    NoteUpdate,
    RetractRequest,
    Visibility,
)
from app.pagination import page_params
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Notes & interactions"])


@router.post("/patients/{patient_id}/notes", status_code=201, response_model=NoteOut)
def create_note(patient_id: UUID, data: NoteCreate, principal=Depends(require("notes:write")),
                engine=Depends(get_engine)):
    """Record a note, call, visit or message. CLINICAL notes need `notes:read_clinical` as well;
    APP_VISIBLE notes are shown to the patient and they are notified. **Permission:** `notes:write`."""
    with engine.begin() as db:
        note_id = service.create_note(db, principal, patient_id, data)
        return service.find_note(db, principal, note_id)


@router.get("/patients/{patient_id}/notes", response_model=NoteList)
def list_notes(patient_id: UUID, visibility: Visibility | None = None, note_type: NoteType | None = None,
               include_retracted: bool = True, paging=Depends(page_params),
               principal=Depends(require("notes:read")), engine=Depends(get_engine)):
    """Notes you may read, newest first. CLINICAL notes are only listed with `notes:read_clinical`;
    for everyone else they simply do not exist. **Permission:** `notes:read`."""
    with engine.begin() as db:
        return service.list_notes(db, principal, patient_id, paging, visibility, note_type, include_retracted)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: UUID, principal=Depends(require("notes:read")), engine=Depends(get_engine)):
    """One note. Not readable by you: 404. **Permission:** `notes:read`."""
    with engine.begin() as db:
        return service.get_note(db, principal, note_id)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: UUID, data: NoteUpdate, principal=Depends(require("notes:write")),
                engine=Depends(get_engine)):
    """Edit your own note. The previous text is kept (see /revisions). **Permission:** `notes:write` (author)."""
    with engine.begin() as db:
        service.update_note(db, principal, note_id, data.model_dump(exclude_unset=True))
        return service.find_note(db, principal, note_id)


@router.post("/notes/{note_id}/retract", response_model=NoteOut)
def retract_note(note_id: UUID, data: RetractRequest, principal=Depends(require("notes:write")),
                 engine=Depends(get_engine)):
    """Mark your own note as entered in error. It stays on record. **Permission:** `notes:write` (author)."""
    with engine.begin() as db:
        service.retract_note(db, principal, note_id, data.reason)
        return service.find_note(db, principal, note_id)


@router.get("/notes/{note_id}/revisions", response_model=list[NoteRevisionOut])
def note_revisions(note_id: UUID, principal=Depends(require("notes:read")), engine=Depends(get_engine)):
    """Earlier versions of a note, oldest first. **Permission:** `notes:read`."""
    with engine.connect() as db:
        return service.list_revisions(db, principal, note_id)
