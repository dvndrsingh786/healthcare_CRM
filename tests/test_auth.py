"""Login, tokens, revocation, rate limiting and password reset (spec section 11)."""
from sqlalchemy import text

from helpers import PASSWORD, audit_events, auth, login

ME = "/api/v1/auth/me"


def test_login_succeeds_with_valid_credentials(client, org_a):
    tokens = login(client, org_a["ops"]["email"])
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == "crm"
    assert tokens["expires_in"] == 15 * 60

    me = client.get(ME, headers=auth(tokens)).json()
    assert me["email"] == org_a["ops"]["email"]
    assert me["roles"] == ["OPS_ADMIN"]
    assert "patients:write" in me["permissions"]


def test_login_fails_safely_with_invalid_credentials(client, org_a, test_engine):
    wrong_password = client.post("/api/v1/auth/login",
                                 json={"email": org_a["ops"]["email"], "password": "WrongPass999"})
    unknown_email = client.post("/api/v1/auth/login",
                                json={"email": "nobody@northfield.example", "password": PASSWORD})

    # Same status, code and message: the response does not reveal which emails have accounts.
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert "access_token" not in response.text
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]

    failures = [e for e in audit_events(test_engine, "auth.login") if e["outcome"] == "FAILURE"]
    assert len(failures) == 2
    assert "WrongPass999" not in str(failures)


def test_login_is_rate_limited(client, org_a):
    # Every attempt counts, successful or not: 5 per minute per IP + email (LOGIN_RATE_LIMIT_PER_MINUTE).
    body = {"email": "guessing@northfield.example", "password": "WrongPass999"}
    statuses = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]

    blocked = client.post("/api/v1/auth/login", json=body)
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert "retry-after" in blocked.headers
    # Other accounts are not locked out by someone guessing this one.
    assert client.post("/api/v1/auth/login",
                       json={"email": org_a["ops"]["email"], "password": PASSWORD}).status_code == 200


def test_protected_endpoint_rejects_missing_or_garbage_token(client, org_a):
    assert client.get(ME).json()["error"]["code"] == "UNAUTHENTICATED"
    response = client.get(ME, headers={"Authorization": "Bearer at_not-a-real-token-at-all"})
    assert response.status_code == 401


def test_logout_revokes_access_and_refresh_token(client, org_a):
    tokens = login(client, org_a["care"]["email"])
    assert client.post("/api/v1/auth/logout", headers=auth(tokens)).status_code == 204

    assert client.get(ME, headers=auth(tokens)).status_code == 401
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 401


def test_expired_access_token_is_rejected(client, org_a, test_engine):
    tokens = login(client, org_a["care"]["email"])
    with test_engine.begin() as db:
        db.execute(text("UPDATE sessions SET access_expires_at = now() - interval '1 second'"))
    assert client.get(ME, headers=auth(tokens)).status_code == 401


def test_refresh_rotates_tokens_and_reuse_revokes_the_session(client, org_a, test_engine):
    first = login(client, org_a["care"]["email"])
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    assert second["access_token"] != first["access_token"]
    assert client.get(ME, headers=auth(first)).status_code == 401   # old access token replaced
    assert client.get(ME, headers=auth(second)).status_code == 200

    # Someone replays the OLD refresh token: the session is treated as stolen and revoked.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert client.get(ME, headers=auth(second)).status_code == 401
    assert audit_events(test_engine, "auth.refresh_reuse")[0]["outcome"] == "DENIED"


def test_deactivated_user_is_logged_out_immediately(client, org_a):
    care_headers = org_a["care"]["headers"]
    response = client.post(f"/api/v1/users/{org_a['care']['id']}/deactivate",
                           headers=org_a["sysadmin"]["headers"])
    assert response.json()["status"] == "INACTIVE"
    assert client.get(ME, headers=care_headers).status_code == 401
    assert client.post("/api/v1/auth/login",
                       json={"email": org_a["care"]["email"], "password": PASSWORD}).status_code == 401


def test_mfa_enabled_account_needs_second_factor(client, org_a, test_engine):
    with test_engine.begin() as db:
        db.execute(text("UPDATE users SET mfa_enabled = true WHERE id = :id"), {"id": org_a["coord"]["id"]})
    response = client.post("/api/v1/auth/login", json={"email": org_a["coord"]["email"], "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MFA_REQUIRED"


def test_password_reset_flow(client, org_a, sent_messages, test_engine):
    old_tokens = login(client, org_a["coord"]["email"])

    # Unknown email: same answer, nothing sent.
    assert client.post("/api/v1/auth/password-reset/request",
                       json={"email": "ghost@northfield.example"}).status_code == 202
    assert sent_messages == []

    assert client.post("/api/v1/auth/password-reset/request",
                       json={"email": org_a["coord"]["email"]}).status_code == 202
    code = sent_messages[0].body.split(": ")[1].split()[0]

    # Only the hash is stored in the database.
    with test_engine.connect() as db:
        stored = db.execute(text("SELECT token_hash FROM password_resets")).scalar_one()
    assert code not in stored

    confirm = client.post("/api/v1/auth/password-reset/confirm",
                          json={"token": code, "new_password": "BrandNewPass42"})
    assert confirm.status_code == 204
    # Single use, and every old session is ended.
    again = client.post("/api/v1/auth/password-reset/confirm", json={"token": code, "new_password": "Another123x"})
    assert again.json()["error"]["code"] == "INVALID_TOKEN"
    assert client.get(ME, headers=auth(old_tokens)).status_code == 401
    login(client, org_a["coord"]["email"], "BrandNewPass42")


def test_audit_log_never_contains_passwords_or_tokens(client, org_a, test_engine):
    tokens = login(client, org_a["ops"]["email"])
    client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    client.post("/api/v1/auth/login", json={"email": org_a["ops"]["email"], "password": "WrongPass999"})

    everything = str(audit_events(test_engine))
    for secret in (PASSWORD, "WrongPass999", tokens["access_token"], tokens["refresh_token"]):
        assert secret not in everything
