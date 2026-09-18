"""Authentication. Login, refresh and password reset are public but rate limited."""
from fastapi import APIRouter, Depends, Request, Response

from app.config import get_settings
from app.context import current_client
from app.database import get_engine
from app.modules.auth import service
from app.modules.auth.schemas import (
    Accepted,
    LoginRequest,
    MeResponse,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenResponse,
)
from app.rate_limit import check_rate_limit
from app.security import get_principal

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def client_ip():
    return current_client()["ip_address"] or "unknown"


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, engine=Depends(get_engine)):
    """Exchange email + password for an access token and a refresh token.

    **Public.** Rate limited per IP+email (`LOGIN_RATE_LIMIT_PER_MINUTE`) and per IP.
    Staff get `scope: crm`, patients get `scope: app`.
    Errors: `INVALID_CREDENTIALS` (401, same message for unknown email and wrong password),
    `MFA_REQUIRED` (401), `RATE_LIMITED` (429).
    """
    limit = get_settings().login_rate_limit_per_minute
    check_rate_limit(engine, f"login:{client_ip()}:{data.email.lower()}", limit)
    check_rate_limit(engine, f"login-ip:{client_ip()}", limit * 10)
    client = current_client()
    return service.login(engine, data.email, data.password, client["ip_address"], client["user_agent"])


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, engine=Depends(get_engine)):
    """Swap a refresh token for a NEW access + refresh token pair (rotation).

    **Public**, rate limited per IP. The old refresh token stops working. Presenting an old
    refresh token again revokes the whole session (`UNAUTHENTICATED`).
    """
    check_rate_limit(engine, f"refresh:{client_ip()}", 30)
    return service.refresh(engine, data.refresh_token)


@router.post("/logout", status_code=204)
def logout(principal=Depends(get_principal), engine=Depends(get_engine)):
    """Revoke the current session. The access and refresh tokens stop working immediately.

    **Auth:** any logged-in user.
    """
    with engine.begin() as db:
        service.logout(db, principal)
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def logout_all(principal=Depends(get_principal), engine=Depends(get_engine)):
    """Revoke every session of the current user (all devices). **Auth:** any logged-in user."""
    with engine.begin() as db:
        service.logout_everywhere(db, principal)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
def me(principal=Depends(get_principal), engine=Depends(get_engine)):
    """The current user, their organisation, roles and effective permissions. **Auth:** any logged-in user."""
    with engine.connect() as db:
        return service.current_user(db, principal)


@router.post("/password-reset/request", status_code=202, response_model=Accepted)
def request_password_reset(data: PasswordResetRequest, engine=Depends(get_engine)):
    """Send a one-time reset code by email. **Public**, rate limited.

    Always answers 202, whether or not the email has an account (no account enumeration).
    """
    check_rate_limit(engine, f"reset:{client_ip()}:{data.email.lower()}", 3)
    service.request_password_reset(engine, data.email)
    return {"status": "accepted"}


@router.post("/password-reset/confirm", status_code=204)
def confirm_password_reset(data: PasswordResetConfirm, engine=Depends(get_engine)):
    """Set a new password with the reset code. Ends every session of that user.

    **Public**, rate limited. Error `INVALID_TOKEN` (400) for an unknown, used or expired code.
    """
    check_rate_limit(engine, f"reset-confirm:{client_ip()}", 10)
    service.confirm_password_reset(engine, data.token, data.new_password)
    return Response(status_code=204)


@router.post("/change-password", status_code=204)
def change_password(data: PasswordChange, request: Request,
                    principal=Depends(get_principal), engine=Depends(get_engine)):
    """Change your own password. Other sessions are ended. **Auth:** any logged-in user."""
    check_rate_limit(engine, f"change-password:{principal['user_id']}", 5)
    service.change_password(engine, principal, data.current_password, data.new_password)
    return Response(status_code=204)
