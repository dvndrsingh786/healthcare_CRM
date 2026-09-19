from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from app.schemas import Name, Out, Page, Password, Phone, SearchBody, StrictModel

RoleKey = Annotated[str, StringConstraints(pattern=r"^[A-Z_]{2,40}$")]
UserType = Literal["STAFF", "PATIENT", "SERVICE"]
UserStatus = Literal["ACTIVE", "INACTIVE"]


class StaffProfile(Out):
    display_name: str | None
    job_title: str | None
    phone: str | None


class TeamRef(Out):
    id: UUID
    name: str


class UserResponse(Out):
    id: UUID
    email: str
    user_type: UserType
    status: UserStatus
    mfa_enabled: bool
    last_login_at: datetime | None
    roles: list[str]
    teams: list[TeamRef]
    profile: StaffProfile
    created_at: datetime
    updated_at: datetime


class UserList(Page):
    data: list[UserResponse]


class UserCreate(StrictModel):
    email: EmailStr
    display_name: Name
    job_title: Name | None = None
    phone: Phone | None = None
    role_keys: list[RoleKey] = Field(min_length=1, max_length=10)
    # Optional. Without a password the user gets an invitation to set their own.
    password: Password | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "email": "nurse.jones@example.org", "display_name": "Sam Jones", "job_title": "Community Nurse",
        "phone": "+44 7700 900123", "role_keys": ["CARE_STAFF"],
    }]}}


class UserUpdate(StrictModel):
    display_name: Name | None = None
    job_title: Name | None = None
    phone: Phone | None = None

    model_config = {"json_schema_extra": {"examples": [
        {"job_title": "Senior community nurse", "phone": "+44 7700 900222"},
    ]}}


class RoleGrant(StrictModel):
    role_key: RoleKey

    model_config = {"json_schema_extra": {"examples": [{"role_key": "COORDINATOR"}]}}


class RoleResponse(Out):
    id: UUID
    key: str
    name: str
    description: str
    for_user_type: UserType
    is_system: bool
    permissions: list[str]


class PermissionsResponse(Out):
    user_id: UUID
    permissions: list[str]


class TeamCreate(StrictModel):
    name: Name
    service: Name | None = None

    model_config = {"json_schema_extra": {"examples": [
        {"name": "District Nursing North", "service": "Community nursing"},
    ]}}


class TeamResponse(Out):
    id: UUID
    name: str
    service: str | None
    active: bool
    member_count: int = 0


class TeamMemberAdd(StrictModel):
    user_id: UUID

    model_config = {"json_schema_extra": {"examples": [{"user_id": "5f1d7c3e-8b2a-4e61-a0c4-7d9e2b6f1a33"}]}}


class ServiceAccountCreate(StrictModel):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{3,40}$")]
    role_keys: list[RoleKey] = Field(min_length=1, max_length=5)
    # Keys always expire. Rotate before the expiry date.
    expires_in_days: int = Field(90, ge=1, le=365)

    model_config = {"json_schema_extra": {"examples": [
        {"name": "outbox-worker", "role_keys": ["NOTIFICATION_WORKER"], "expires_in_days": 90},
    ]}}


class KeyRotate(StrictModel):
    expires_in_days: int = Field(90, ge=1, le=365)

    model_config = {"json_schema_extra": {"examples": [{"expires_in_days": 90}]}}


class ApiKeyResponse(Out):
    id: UUID
    prefix: str
    expires_at: datetime
    # Shown ONCE. Only its hash is stored, so it cannot be shown again.
    api_key: str


class ServiceAccountResponse(Out):
    user: UserResponse
    key: ApiKeyResponse


class UserSearch(SearchBody):
    search: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = Field(
        None, description="Matches email or display name")
    user_type: Literal["STAFF", "SERVICE"] | None = None
    status: UserStatus | None = None
    role: Annotated[str, StringConstraints(max_length=40)] | None = None
    sort: Annotated[str, StringConstraints(max_length=40)] | None = Field(
        None, description="email, display_name, created_at (prefix - for descending)")

    model_config = {"json_schema_extra": {"examples": [
        {"search": "nadia", "status": "ACTIVE", "role": "CARE_STAFF", "page": 1, "page_size": 25},
    ]}}
