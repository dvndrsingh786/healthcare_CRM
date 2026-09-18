"""Login, token refresh/rotation, logout, password reset.

Design (see docs/ARCHITECTURE.md):
- Opaque random tokens, stored only as SHA-256 hashes, so revocation is immediate
  (a revoked session fails on the very next request) and nothing sensitive sits in a JWT.
- Access token: short-lived (ACCESS_TOKEN_MINUTES). Refresh token: rotated on every use.
  Re-using an old refresh token revokes the whole session (it was probably stolen).
- MFA-ready: users.mfa_enabled exists. When it is true, password login alone is refused with
  MFA_REQUIRED; the second-factor step is the next-sprint work item.
"""
from sqlalchemy import text

from app import metrics
from app.audit import DENIED, FAILURE, SUCCESS, record_event, record_event_now
from app.config import get_settings
from app.errors import ApiError
from app.messaging import OutgoingMessage, get_provider
from app.security import hash_password, hash_token, new_token, unauthenticated, verify_password

# Used when the email does not exist, so a wrong email takes as long as a wrong password.
# Otherwise an attacker could time the response to learn which emails have accounts.
FAKE_PASSWORD_HASH = hash_password("not-a-real-password-0")

INVALID_LOGIN = "Invalid email or password."


def actor(user):
    return {"user_id": user["id"], "organisation_id": user["organisation_id"], "user_type": user["user_type"]}


def issue_session(db, user, ip_address=None, user_agent=None):
    settings = get_settings()
    access_token, refresh_token = new_token("at_"), new_token("rt_")
    scope = "app" if user["user_type"] == "PATIENT" else "crm"
    session_id = db.execute(
        text("""
            INSERT INTO sessions (user_id, organisation_id, scope, access_token_hash, access_expires_at,
                                  refresh_token_hash, refresh_expires_at, ip_address, user_agent)
            VALUES (:user_id, :org, :scope, :access_hash, now() + make_interval(mins => :access_minutes),
                    :refresh_hash, now() + make_interval(days => :refresh_days), :ip, :agent)
            RETURNING id
        """),
        {"user_id": user["id"], "org": user["organisation_id"], "scope": scope,
         "access_hash": hash_token(access_token), "access_minutes": settings.access_token_minutes,
         "refresh_hash": hash_token(refresh_token), "refresh_days": settings.refresh_token_days,
         "ip": ip_address, "agent": user_agent},
    ).scalar_one()
    return session_id, token_response(access_token, refresh_token, scope)


def token_response(access_token, refresh_token, scope):
    settings = get_settings()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "scope": scope,
        "expires_in": settings.access_token_minutes * 60,
        "refresh_expires_in": settings.refresh_token_days * 86400,
    }


def login(engine, email, password, ip_address, user_agent):
    with engine.begin() as db:
        user = db.execute(
            text("""
                SELECT users.id, users.organisation_id, users.user_type, users.password_hash, users.mfa_enabled
                FROM users JOIN organisations ON organisations.id = users.organisation_id
                WHERE lower(users.email) = lower(:email)
                  AND users.status = 'ACTIVE' AND organisations.status = 'ACTIVE'
                  AND users.user_type IN ('STAFF', 'PATIENT')
            """),
            {"email": email},
        ).mappings().first()

        password_ok = verify_password(password, user["password_hash"] if user and user["password_hash"]
                                      else FAKE_PASSWORD_HASH)
        if user is None or not user["password_hash"] or not password_ok:
            if user is not None:
                db.execute(text("UPDATE users SET failed_login_count = failed_login_count + 1 WHERE id = :id"),
                           {"id": user["id"]})
            failed = True
        else:
            failed = False

    if failed:
        metrics.increment("auth_login_failed_total")
        # Its own transaction: the failure is kept even though the request ends with 401.
        # We do not store the email that was tried (it may be a typo of someone else's address).
        record_event_now(engine, actor(user) if user else None, "auth.login", "user",
                         user["id"] if user else None, outcome=FAILURE,
                         metadata={"reason": "bad_credentials"})
        raise ApiError(401, "INVALID_CREDENTIALS", INVALID_LOGIN)

    if user["mfa_enabled"]:
        record_event_now(engine, actor(user), "auth.login", "user", user["id"], outcome=DENIED,
                         metadata={"reason": "mfa_required"})
        raise ApiError(401, "MFA_REQUIRED", "A second authentication factor is required for this account.")

    with engine.begin() as db:
        db.execute(text("UPDATE users SET last_login_at = now(), failed_login_count = 0 WHERE id = :id"),
                   {"id": user["id"]})
        session_id, tokens = issue_session(db, user, ip_address, user_agent)
        record_event(db, actor(user), "auth.login", "session", session_id)
    return tokens


def refresh(engine, refresh_token):
    token_hash = hash_token(refresh_token)
    settings = get_settings()

    with engine.begin() as db:
        session = db.execute(
            text("""
                SELECT sessions.id, sessions.scope, users.id AS user_id, users.organisation_id, users.user_type
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                JOIN organisations ON organisations.id = users.organisation_id
                WHERE sessions.refresh_token_hash = :hash
                  AND sessions.revoked_at IS NULL
                  AND sessions.refresh_expires_at > now()
                  AND users.status = 'ACTIVE' AND organisations.status = 'ACTIVE'
                FOR UPDATE OF sessions
            """),
            {"hash": token_hash},
        ).mappings().first()

        if session is not None:
            access_token, new_refresh_token = new_token("at_"), new_token("rt_")
            db.execute(
                text("""
                    UPDATE sessions SET
                        access_token_hash = :access_hash,
                        access_expires_at = now() + make_interval(mins => :access_minutes),
                        previous_refresh_hash = refresh_token_hash,
                        refresh_token_hash = :refresh_hash,
                        last_refreshed_at = now()
                    WHERE id = :id
                """),
                {"id": session["id"], "access_hash": hash_token(access_token),
                 "access_minutes": settings.access_token_minutes, "refresh_hash": hash_token(new_refresh_token)},
            )
            user = {"id": session["user_id"], "organisation_id": session["organisation_id"],
                    "user_type": session["user_type"]}
            record_event(db, actor(user), "auth.refresh", "session", session["id"])
            return token_response(access_token, new_refresh_token, session["scope"])

        # Not a current refresh token. Is it one that was already swapped out? Then it was replayed.
        reused = db.execute(
            text("""
                UPDATE sessions SET revoked_at = now(), revoked_reason = 'refresh_token_reuse'
                FROM users
                WHERE users.id = sessions.user_id
                  AND sessions.previous_refresh_hash = :hash AND sessions.revoked_at IS NULL
                RETURNING sessions.id, users.id AS user_id, users.organisation_id, users.user_type
            """),
            {"hash": token_hash},
        ).mappings().first()

    if reused is not None:
        user = {"id": reused["user_id"], "organisation_id": reused["organisation_id"],
                "user_type": reused["user_type"]}
        record_event_now(engine, actor(user), "auth.refresh_reuse", "session", reused["id"], outcome=DENIED)
    raise unauthenticated("The refresh token is invalid, expired or revoked. Please log in again.")


def logout(db, principal):
    if principal["session_id"] is None:
        raise ApiError(400, "BAD_REQUEST", "API keys cannot log out. Revoke the key instead.")
    db.execute(
        text("UPDATE sessions SET revoked_at = now(), revoked_reason = 'logout' WHERE id = :id"),
        {"id": principal["session_id"]},
    )
    record_event(db, principal, "auth.logout", "session", principal["session_id"])


def logout_everywhere(db, principal):
    db.execute(
        text("UPDATE sessions SET revoked_at = now(), revoked_reason = 'logout_all' "
             "WHERE user_id = :id AND revoked_at IS NULL"),
        {"id": principal["user_id"]},
    )
    record_event(db, principal, "auth.logout_all", "user", principal["user_id"])


def current_user(db, principal):
    user = db.execute(
        text("""
            SELECT users.id, users.email, users.user_type, users.status, users.mfa_enabled, users.last_login_at,
                   organisations.id AS organisation_id, organisations.name AS organisation_name,
                   organisations.timezone AS organisation_timezone,
                   staff_profiles.display_name
            FROM users
            JOIN organisations ON organisations.id = users.organisation_id
            LEFT JOIN staff_profiles ON staff_profiles.user_id = users.id
            WHERE users.id = :id
        """),
        {"id": principal["user_id"]},
    ).mappings().one()
    from app.modules.users.service import user_roles

    return {
        "id": user["id"],
        "email": user["email"],
        "user_type": user["user_type"],
        "display_name": user["display_name"],
        "mfa_enabled": user["mfa_enabled"],
        "last_login_at": user["last_login_at"],
        "scope": principal["scope"],
        "organisation": {"id": user["organisation_id"], "name": user["organisation_name"],
                         "timezone": user["organisation_timezone"]},
        "roles": user_roles(db, user["id"]),
        "permissions": sorted(principal["permissions"]),
    }


# ---------- Password reset ----------

def send_password_reset(db, user_id, email, template_key="password_reset"):
    """Create a reset token and send it straight to the user.

    This deliberately bypasses the notification outbox: the outbox is stored in the database,
    and the raw token must never be stored anywhere. Only its hash is kept.
    """
    token = new_token("pr_")
    db.execute(
        text("""
            INSERT INTO password_resets (user_id, token_hash, expires_at)
            VALUES (:user_id, :hash, now() + make_interval(mins => :minutes))
        """),
        {"user_id": user_id, "hash": hash_token(token), "minutes": get_settings().password_reset_minutes},
    )
    get_provider().send(OutgoingMessage(
        channel="EMAIL", to=email, template_key=template_key,
        subject="Set your password" if template_key == "account_invite" else "Reset your password",
        body=f"Use this code to set a new password: {token}\nIt expires soon. If you did not ask for this, "
             "ignore this message.",
        idempotency_key=hash_token(token)[:32],
    ))


def request_password_reset(engine, email):
    """Always behaves the same, whether or not the email exists (no account enumeration)."""
    with engine.begin() as db:
        user = db.execute(
            text("""
                SELECT users.id, users.email, users.organisation_id, users.user_type
                FROM users JOIN organisations ON organisations.id = users.organisation_id
                WHERE lower(users.email) = lower(:email) AND users.status = 'ACTIVE'
                  AND organisations.status = 'ACTIVE' AND users.user_type IN ('STAFF', 'PATIENT')
            """),
            {"email": email},
        ).mappings().first()
        if user is None:
            return
        send_password_reset(db, user["id"], user["email"])
        record_event(db, actor(user), "auth.password_reset_request", "user", user["id"])


def confirm_password_reset(engine, token, new_password):
    new_hash = hash_password(new_password)
    with engine.begin() as db:
        reset = db.execute(
            text("""
                SELECT password_resets.id, users.id AS user_id, users.organisation_id, users.user_type
                FROM password_resets JOIN users ON users.id = password_resets.user_id
                WHERE password_resets.token_hash = :hash AND password_resets.used_at IS NULL
                  AND password_resets.expires_at > now() AND users.status = 'ACTIVE'
                FOR UPDATE OF password_resets
            """),
            {"hash": hash_token(token)},
        ).mappings().first()
        if reset is None:
            raise ApiError(400, "INVALID_TOKEN", "This reset code is invalid or has expired.")

        db.execute(text("UPDATE password_resets SET used_at = now() WHERE user_id = :id AND used_at IS NULL"),
                   {"id": reset["user_id"]})
        db.execute(text("UPDATE users SET password_hash = :hash, failed_login_count = 0 WHERE id = :id"),
                   {"hash": new_hash, "id": reset["user_id"]})
        # A new password logs the account out everywhere.
        db.execute(text("UPDATE sessions SET revoked_at = now(), revoked_reason = 'password_reset' "
                        "WHERE user_id = :id AND revoked_at IS NULL"), {"id": reset["user_id"]})
        user = {"id": reset["user_id"], "organisation_id": reset["organisation_id"],
                "user_type": reset["user_type"]}
        record_event(db, actor(user), "auth.password_reset", "user", reset["user_id"], outcome=SUCCESS,
                     changed_fields=["password"])


def change_password(engine, principal, current_password, new_password):
    with engine.connect() as db:
        current_hash = db.execute(text("SELECT password_hash FROM users WHERE id = :id"),
                                  {"id": principal["user_id"]}).scalar_one()
    if not current_hash or not verify_password(current_password, current_hash):
        record_event_now(engine, principal, "auth.password_change", "user", principal["user_id"],
                         metadata={"reason": "wrong_current_password"})
        raise ApiError(400, "INVALID_CREDENTIALS", "The current password is not correct.")

    with engine.begin() as db:
        db.execute(text("UPDATE users SET password_hash = :hash WHERE id = :id"),
                   {"hash": hash_password(new_password), "id": principal["user_id"]})
        # Keep this session, end all the others.
        db.execute(text("UPDATE sessions SET revoked_at = now(), revoked_reason = 'password_change' "
                        "WHERE user_id = :id AND revoked_at IS NULL AND id IS DISTINCT FROM :session_id"),
                   {"id": principal["user_id"], "session_id": principal["session_id"]})
        record_event(db, principal, "auth.password_change", "user", principal["user_id"],
                     changed_fields=["password"])
