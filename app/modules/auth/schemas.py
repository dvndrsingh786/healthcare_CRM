from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from app.schemas import Out, Password, StrictModel

Token = Annotated[str, StringConstraints(min_length=20, max_length=200)]


class LoginRequest(StrictModel):
    email: EmailStr
    # No strength rules here: we only compare it. Length limit stops huge inputs to Argon2.
    password: str = Field(min_length=1, max_length=128)

    model_config = {"json_schema_extra": {"examples": [
        {"email": "ops.admin@northfield.example", "password": "DemoPass123!"}]}}


class TokenResponse(Out):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"]
    scope: Literal["crm", "app"]
    expires_in: int = Field(description="Seconds until the access token expires")
    refresh_expires_in: int = Field(description="Seconds until the refresh token expires")


class RefreshRequest(StrictModel):
    refresh_token: Token

    model_config = {"json_schema_extra": {"examples": [{"refresh_token": "rt_4mWq9Zb2Lr7Xc1Vn8Ty3Hs6Kd0Pf5Ga"}]}}


class PasswordResetRequest(StrictModel):
    email: EmailStr

    model_config = {"json_schema_extra": {"examples": [{"email": "nurse@northfield.example"}]}}


class PasswordResetConfirm(StrictModel):
    token: Token
    new_password: Password

    model_config = {"json_schema_extra": {"examples": [
        {"token": "pr_9Kf2Ls7Qw1Xe4Rt8Yu3Io6Pa0Sd5Fg", "new_password": "Harbour-Lantern-58"},
    ]}}


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password

    model_config = {"json_schema_extra": {"examples": [
        {"current_password": "DemoPass123!", "new_password": "Harbour-Lantern-58"},
    ]}}


class OrganisationRef(Out):
    id: UUID
    name: str
    timezone: str


class MeResponse(Out):
    id: UUID
    email: str
    user_type: Literal["STAFF", "PATIENT", "SERVICE"]
    display_name: str | None
    mfa_enabled: bool
    last_login_at: datetime | None
    scope: Literal["crm", "app"]
    organisation: OrganisationRef
    roles: list[str]
    permissions: list[str]


class Accepted(Out):
    status: Literal["accepted"] = "accepted"
