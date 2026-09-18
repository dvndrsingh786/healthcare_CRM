from fastapi import APIRouter, Depends

from app.database import get_engine
from app.modules.organisations import service
from app.modules.organisations.schemas import OrganisationResponse, OrganisationUpdate
from app.security import crm_principal, require

router = APIRouter(prefix="/api/v1/organisation", tags=["Organisation"])


@router.get("", response_model=OrganisationResponse)
def get_organisation(principal=Depends(crm_principal), engine=Depends(get_engine)):
    """Your own organisation and its settings. **Auth:** any CRM user."""
    with engine.connect() as db:
        return service.get_organisation(db, principal)


@router.patch("", response_model=OrganisationResponse)
def update_organisation(data: OrganisationUpdate, principal=Depends(require("org:manage")),
                        engine=Depends(get_engine)):
    """Change name, time zone or policy settings (retention, notification rules).
    **Permission:** `org:manage`."""
    changes = data.model_dump(exclude_unset=True)
    if "settings" in changes:
        changes["settings"] = {section: {k: v for k, v in values.items() if v is not None}
                               for section, values in changes["settings"].items() if values}
    with engine.begin() as db:
        service.update_organisation(db, principal, changes)
        return service.get_organisation(db, principal)
