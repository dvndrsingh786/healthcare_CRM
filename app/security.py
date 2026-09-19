"""Passwords, tokens, "who is calling?" and permission checks.

The caller is described by a small dict called the *principal*:

    {"user_id", "organisation_id", "user_type", "email", "scope", "session_id",
     "api_key_id", "permissions"}

Rules enforced here (default deny):
- No valid credentials -> 401 UNAUTHENTICATED.
- CRM endpoints accept only 'crm' scope (staff sessions and service-account API keys).
- App endpoints accept only 'app' scope (patient sessions).
- Missing permission -> 403 FORBIDDEN, and the denial is written to the audit log.

A valid token is never enough on its own: object-level checks (organisation, assignment,
ownership, visibility) happen again in each module's service layer.
"""
import hashlib
import secrets

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import text

from app.audit import DENIED, record_event_now
from app.config import get_settings
from app.database import get_engine
from app.errors import ApiError, forbidden
from app.rate_limit import check_rate_limit

# ---------- Passwords ----------

# Argon2id: a slow, salted hashing algorithm made for passwords. We never store the password.
password_hasher = PasswordHash.recommended()


def hash_password(password):
    return password_hasher.hash(password)


def verify_password(password, password_hash):
    return password_hasher.verify(password, password_hash)


# ---------- Tokens ----------

def new_token(prefix=""):
    # 32 random bytes: impossible to guess.
    return prefix + secrets.token_urlsafe(32)


def hash_token(token):
    # Tokens are already random, so a fast SHA-256 is enough. Only this hash is stored.
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- Who is calling? ----------

bearer_scheme = HTTPBearer(auto_error=False, description="Access token from POST /api/v1/auth/login")
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False,
                              description="Service-account API key (machine-to-machine)")


def unauthenticated(message="Your session is invalid or has expired. Please log in again."):
    return ApiError(401, "UNAUTHENTICATED", message, headers={"WWW-Authenticate": "Bearer"})


def load_permissions(db, user_id, user_type):
    return frozenset(db.execute(
        text("""
            SELECT DISTINCT role_permissions.permission_key
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id
            JOIN role_permissions ON role_permissions.role_id = roles.id
            WHERE user_roles.user_id = :user_id
              -- A role only counts for the kind of user it was made for.
              AND roles.for_user_type = :user_type
        """),
        {"user_id": user_id, "user_type": user_type},
    ).scalars())


def principal_from_session(db, access_token):
    row = db.execute(
        text("""
            SELECT sessions.id AS session_id, sessions.scope, users.id AS user_id,
                   users.organisation_id, users.user_type, users.email
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            JOIN organisations ON organisations.id = users.organisation_id
            WHERE sessions.access_token_hash = :token_hash
              AND sessions.revoked_at IS NULL
              AND sessions.access_expires_at > now()
              AND users.status = 'ACTIVE'
              AND organisations.status = 'ACTIVE'
        """),
        {"token_hash": hash_token(access_token)},
    ).mappings().first()
    if row is None:
        return None
    principal = dict(row)
    principal["api_key_id"] = None
    return principal


def principal_from_api_key(db, api_key):
    row = db.execute(
        text("""
            SELECT api_keys.id AS api_key_id, users.id AS user_id, users.organisation_id,
                   users.user_type, users.email
            FROM api_keys
            JOIN users ON users.id = api_keys.user_id
            JOIN organisations ON organisations.id = users.organisation_id
            WHERE api_keys.key_hash = :key_hash
              AND api_keys.revoked_at IS NULL
              AND api_keys.expires_at > now()
              AND users.user_type = 'SERVICE'
              AND users.status = 'ACTIVE'
              AND organisations.status = 'ACTIVE'
        """),
        {"key_hash": hash_token(api_key)},
    ).mappings().first()
    if row is None:
        return None
    db.execute(text("UPDATE api_keys SET last_used_at = now() WHERE id = :id"), {"id": row["api_key_id"]})
    principal = dict(row)
    principal["session_id"] = None
    principal["scope"] = "crm"
    return principal


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_scheme),
    engine=Depends(get_engine),
):
    """Any authenticated caller (staff, patient or service account)."""
    if credentials is None and not api_key:
        raise unauthenticated("Authentication required. Send 'Authorization: Bearer <access token>'.")

    with engine.begin() as db:
        if credentials is not None:
            principal = principal_from_session(db, credentials.credentials)
        else:
            principal = principal_from_api_key(db, api_key)
        if principal is None:
            raise unauthenticated()
        principal["permissions"] = load_permissions(db, principal["user_id"], principal["user_type"])
    return principal


def _deny(engine, principal, request, reason):
    record_event_now(engine, principal, "access.denied", outcome=DENIED,
                     metadata={"method": request.method, "route": request.url.path, "reason": reason})
    return forbidden()


def crm_principal(request: Request, principal=Depends(get_principal), engine=Depends(get_engine)):
    """Staff or service account. Patient-app sessions are rejected here."""
    if principal["scope"] != "crm":
        raise _deny(engine, principal, request, "app_scope_on_crm_route")
    return principal


def require(*permissions):
    """CRM endpoint that needs ALL of the given permissions.

        principal = Depends(require("patients:write"))
    """
    def check(request: Request, principal=Depends(crm_principal), engine=Depends(get_engine)):
        missing = [key for key in permissions if key not in principal["permissions"]]
        if missing:
            raise _deny(engine, principal, request, "missing_permission:" + ",".join(missing))
        return principal

    check.required_permissions = permissions
    return check


def require_any(*permissions):
    """CRM endpoint that needs AT LEAST ONE of the given permissions."""
    def check(request: Request, principal=Depends(crm_principal), engine=Depends(get_engine)):
        if not any(key in principal["permissions"] for key in permissions):
            raise _deny(engine, principal, request, "missing_permission:" + "|".join(permissions))
        return principal

    check.required_permissions = permissions
    return check


def app_principal(request: Request, principal=Depends(get_principal), engine=Depends(get_engine)):
    """Patient app endpoint: 'app' scope and the app:self permission. Also rate limited per user."""
    if principal["scope"] != "app" or "app:self" not in principal["permissions"]:
        raise _deny(engine, principal, request, "crm_scope_on_app_route")
    check_rate_limit(engine, f"app:{principal['user_id']}", get_settings().app_rate_limit_per_minute)
    return principal


def has(principal, permission):
    return permission in principal["permissions"]


def principal_for_user(db, user_id, scope):
    """Rebuild a principal from a user id (used by signed download links, which must re-check
    the user's CURRENT status and permissions). None if the user can no longer act."""
    row = db.execute(
        text("""
            SELECT users.id AS user_id, users.organisation_id, users.user_type, users.email
            FROM users JOIN organisations ON organisations.id = users.organisation_id
            WHERE users.id = :id AND users.status = 'ACTIVE' AND organisations.status = 'ACTIVE'
        """),
        {"id": user_id},
    ).mappings().first()
    if row is None or scope != ("app" if row["user_type"] == "PATIENT" else "crm"):
        return None
    principal = dict(row, scope=scope, session_id=None, api_key_id=None)
    principal["permissions"] = load_permissions(db, row["user_id"], row["user_type"])
    return principal
