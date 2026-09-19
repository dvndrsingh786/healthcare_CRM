"""Staff users, roles, teams and service accounts (CRM side).

Patients' app accounts are managed from the patient record (see the patients module).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.database import get_engine
from app.errors import invalid
from app.modules.auth.service import send_password_reset
from app.modules.users import service
from app.modules.users.schemas import (
    ApiKeyResponse,
    KeyRotate,
    PermissionsResponse,
    RoleGrant,
    RoleResponse,
    ServiceAccountCreate,
    ServiceAccountResponse,
    TeamCreate,
    TeamMemberAdd,
    TeamResponse,
    UserCreate,
    UserList,
    UserResponse,
    UserSearch,
    UserStatus,
    UserUpdate,
)
from app.pagination import page_params
from app.security import require

router = APIRouter(prefix="/api/v1", tags=["Users & RBAC"])


@router.get("/users", response_model=UserList)
def list_users(
    user_type: Literal["STAFF", "SERVICE"] | None = None,
    status: UserStatus | None = None,
    search: str | None = Query(None, include_in_schema=False),
    role: str | None = Query(None, max_length=40),
    sort: str | None = Query(None, description="email, display_name, created_at (prefix - for descending)"),
    paging=Depends(page_params),
    principal=Depends(require("users:read")),
    engine=Depends(get_engine),
):
    """List staff and service accounts of your organisation. To search by name or email use
    `POST /users/search` (keeps the search text out of the URL). **Permission:** `users:read`."""
    if search is not None:
        # Refuse rather than ignore, so an old client does not silently get an unfiltered list.
        raise invalid("Search text must not be sent in the URL. Use POST /api/v1/users/search.", field="search")
    with engine.connect() as db:
        return service.list_users(db, principal, paging, user_type, status, role, None, sort)


@router.post("/users/search", response_model=UserList)
def search_users(data: UserSearch, principal=Depends(require("users:read")), engine=Depends(get_engine)):
    """Search staff and service accounts by email or display name, with the same filters as
    `GET /users`. The search text is sent in the body, never in the URL. **Permission:** `users:read`."""
    with engine.connect() as db:
        return service.list_users(db, principal, data.paging(), data.user_type, data.status, data.role,
                                  data.search, data.sort)


@router.post("/users", status_code=201, response_model=UserResponse)
def create_user(data: UserCreate, principal=Depends(require("users:manage", "roles:manage")),
                engine=Depends(get_engine)):
    """Create a staff user with a profile and roles. **Permission:** `users:manage` + `roles:manage`.

    Without `password`, the user is emailed a one-time code to set their own (invitation).
    Only a System Admin can grant `SYSTEM_ADMIN`. Duplicate email: 409 `DUPLICATE_EMAIL`.
    """
    with engine.begin() as db:
        user_id = service.create_staff_user(db, principal, data)
        if data.password is None:
            send_password_reset(db, user_id, data.email, template_key="account_invite")
        return service.get_user(db, principal, user_id)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, principal=Depends(require("users:read")), engine=Depends(get_engine)):
    """One staff user or service account. **Permission:** `users:read`."""
    with engine.connect() as db:
        return service.get_user(db, principal, user_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, data: UserUpdate, principal=Depends(require("users:manage")),
                engine=Depends(get_engine)):
    """Update a staff profile (display name, job title, phone). **Permission:** `users:manage`."""
    with engine.begin() as db:
        service.update_user(db, principal, user_id, data.model_dump(exclude_unset=True))
        return service.get_user(db, principal, user_id)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(user_id: UUID, principal=Depends(require("users:manage")), engine=Depends(get_engine)):
    """Deactivate a user. Their sessions and API keys are revoked immediately.
    You cannot deactivate yourself. **Permission:** `users:manage`."""
    with engine.begin() as db:
        service.set_status(db, principal, user_id, "INACTIVE")
        return service.get_user(db, principal, user_id)


@router.post("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(user_id: UUID, principal=Depends(require("users:manage")), engine=Depends(get_engine)):
    """Re-activate a user. **Permission:** `users:manage`."""
    with engine.begin() as db:
        service.set_status(db, principal, user_id, "ACTIVE")
        return service.get_user(db, principal, user_id)


@router.post("/users/{user_id}/roles", response_model=UserResponse)
def grant_role(user_id: UUID, data: RoleGrant, principal=Depends(require("roles:manage")),
               engine=Depends(get_engine)):
    """Give a role to a user. The role must match the user type (staff/service).
    You cannot change your own roles. **Permission:** `roles:manage`."""
    with engine.begin() as db:
        service.grant_role(db, principal, user_id, data.role_key)
        return service.get_user(db, principal, user_id)


@router.delete("/users/{user_id}/roles/{role_key}", response_model=UserResponse)
def revoke_role(user_id: UUID, role_key: str, principal=Depends(require("roles:manage")),
                engine=Depends(get_engine)):
    """Remove a role from a user. **Permission:** `roles:manage`."""
    with engine.begin() as db:
        service.revoke_role(db, principal, user_id, role_key)
        return service.get_user(db, principal, user_id)


@router.get("/users/{user_id}/permissions", response_model=PermissionsResponse)
def user_permissions(user_id: UUID, principal=Depends(require("users:read")), engine=Depends(get_engine)):
    """The effective permissions of a user (union of their roles). **Permission:** `users:read`."""
    with engine.connect() as db:
        return {"user_id": user_id, "permissions": service.effective_permissions(db, principal, user_id)}


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(principal=Depends(require("users:read")), engine=Depends(get_engine)):
    """Built-in roles (and, later, custom roles of your organisation) with their permissions.
    **Permission:** `users:read`."""
    with engine.connect() as db:
        return service.list_roles(db, principal)


# ---------- Teams ----------

@router.get("/teams", response_model=list[TeamResponse])
def list_teams(principal=Depends(require("users:read")), engine=Depends(get_engine)):
    """Teams / services of your organisation. **Permission:** `users:read`."""
    with engine.connect() as db:
        return service.list_teams(db, principal)


@router.post("/teams", status_code=201, response_model=TeamResponse)
def create_team(data: TeamCreate, principal=Depends(require("assignments:manage")), engine=Depends(get_engine)):
    """Create a team. Duplicate name: 409. **Permission:** `assignments:manage`."""
    with engine.begin() as db:
        team_id = service.create_team(db, principal, data.name, data.service)
        return dict(service.find_team(db, principal, team_id), member_count=0)


@router.post("/teams/{team_id}/members", status_code=204)
def add_team_member(team_id: UUID, data: TeamMemberAdd, principal=Depends(require("assignments:manage")),
                    engine=Depends(get_engine)):
    """Add an active staff member to a team. **Permission:** `assignments:manage`."""
    with engine.begin() as db:
        service.add_team_member(db, principal, team_id, data.user_id)
    return Response(status_code=204)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
def remove_team_member(team_id: UUID, user_id: UUID, principal=Depends(require("assignments:manage")),
                       engine=Depends(get_engine)):
    """Remove a staff member from a team. **Permission:** `assignments:manage`."""
    with engine.begin() as db:
        service.remove_team_member(db, principal, team_id, user_id)
    return Response(status_code=204)


# ---------- Service accounts ----------

@router.post("/service-accounts", status_code=201, response_model=ServiceAccountResponse)
def create_service_account(data: ServiceAccountCreate,
                           principal=Depends(require("users:manage", "roles:manage")),
                           engine=Depends(get_engine)):
    """Create a machine account with narrowly scoped service roles and an expiring API key.

    The key is returned **once**; send it as `X-API-Key`. It acts under its own audit identity.
    **Permission:** `users:manage` + `roles:manage`.
    """
    with engine.begin() as db:
        user_id, raw_key, key = service.create_service_account(db, principal, data)
        return {"user": service.get_user(db, principal, user_id), "key": dict(key, api_key=raw_key)}


@router.post("/service-accounts/{user_id}/rotate-key", response_model=ApiKeyResponse)
def rotate_key(user_id: UUID, data: KeyRotate, principal=Depends(require("users:manage")),
               engine=Depends(get_engine)):
    """Issue a new API key and revoke the old one(s). **Permission:** `users:manage`."""
    with engine.begin() as db:
        raw_key, key = service.rotate_api_key(db, principal, user_id, data.expires_in_days)
        return dict(key, api_key=raw_key)


@router.delete("/service-accounts/{user_id}/keys", status_code=204)
def revoke_keys(user_id: UUID, principal=Depends(require("users:manage")), engine=Depends(get_engine)):
    """Revoke every API key of a service account. **Permission:** `users:manage`."""
    with engine.begin() as db:
        service.revoke_api_keys(db, principal, user_id)
    return Response(status_code=204)
