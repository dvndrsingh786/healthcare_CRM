"""Roles, permissions, service accounts, scopes and tenant boundaries for users."""
from fastapi.routing import APIRoute

from app.main import app
from app.security import get_principal
from helpers import PASSWORD, audit_events, make_app_user

# The only routes that may be called without credentials.
PUBLIC_ROUTES = {
    "/api/v1/health", "/api/v1/health/ready", "/api/v1/auth/login", "/api/v1/auth/refresh",
    "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm",
}


def uses_dependency(dependant, target):
    return any(d.call is target or uses_dependency(d, target) for d in dependant.dependencies)


def test_every_route_requires_authentication_by_default():
    """Default deny: a new endpoint without an auth dependency makes this test fail."""
    unprotected = [
        route.path for route in app.routes
        if isinstance(route, APIRoute) and route.path not in PUBLIC_ROUTES
        and not route.path.startswith("/api/v1/storage/")  # signed links, checked in test_documents.py
        and not uses_dependency(route.dependant, get_principal)
    ]
    assert unprotected == []


def test_missing_permission_is_forbidden_and_audited(client, org_a, test_engine):
    response = client.post("/api/v1/users", headers=org_a["coord"]["headers"], json={
        "email": "new@northfield.example", "display_name": "New", "role_keys": ["CARE_STAFF"]})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    denied = audit_events(test_engine, "access.denied")
    assert denied[0]["actor_user_id"] is not None
    assert denied[0]["outcome"] == "DENIED"


def test_system_admin_creates_user_with_invitation(client, org_a, sent_messages):
    response = client.post("/api/v1/users", headers=org_a["sysadmin"]["headers"], json={
        "email": "New.Nurse@northfield.example", "display_name": "New Nurse", "job_title": "Nurse",
        "role_keys": ["CARE_STAFF"]})
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["email"] == "new.nurse@northfield.example"
    assert user["roles"] == ["CARE_STAFF"]
    assert "password_hash" not in response.text
    assert sent_messages[0].template_key == "account_invite"

    duplicate = client.post("/api/v1/users", headers=org_a["sysadmin"]["headers"], json={
        "email": "new.nurse@northfield.example", "display_name": "Again", "role_keys": ["CARE_STAFF"]})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_EMAIL"


def test_role_rules(client, org_a):
    admin = org_a["sysadmin"]["headers"]
    care_id = org_a["care"]["id"]

    # A patient role cannot be given to a staff user.
    wrong_type = client.post(f"/api/v1/users/{care_id}/roles", headers=admin, json={"role_key": "APP_USER"})
    assert wrong_type.status_code == 422

    granted = client.post(f"/api/v1/users/{care_id}/roles", headers=admin, json={"role_key": "COORDINATOR"})
    assert granted.json()["roles"] == ["CARE_STAFF", "COORDINATOR"]
    perms = client.get(f"/api/v1/users/{care_id}/permissions", headers=admin).json()["permissions"]
    assert "notes:read_clinical" in perms and "appointments:write" in perms

    revoked = client.delete(f"/api/v1/users/{care_id}/roles/COORDINATOR", headers=admin)
    assert revoked.json()["roles"] == ["CARE_STAFF"]

    own = client.delete(f"/api/v1/users/{org_a['sysadmin']['id']}/roles/SYSTEM_ADMIN", headers=admin)
    assert own.status_code == 403


def test_system_admin_has_no_clinical_access_by_default(client, org_a):
    me = client.get("/api/v1/auth/me", headers=org_a["sysadmin"]["headers"]).json()
    assert not any(p.startswith(("patients:", "notes:", "documents:")) for p in me["permissions"])


def test_users_of_another_organisation_are_invisible(client, org_a, org_b):
    b_admin = org_b["sysadmin"]["headers"]
    a_user = org_a["care"]["id"]

    assert client.get(f"/api/v1/users/{a_user}", headers=b_admin).status_code == 404
    assert client.post(f"/api/v1/users/{a_user}/deactivate", headers=b_admin).status_code == 404
    assert client.post(f"/api/v1/users/{a_user}/roles", headers=b_admin,
                       json={"role_key": "OPS_ADMIN"}).status_code == 404
    emails = [u["email"] for u in client.get("/api/v1/users?page_size=100", headers=b_admin).json()["data"]]
    assert emails and all(email.endswith("@southbank.example") for email in emails)


def test_pagination_has_a_maximum_page_size(client, org_a):
    response = client.get("/api/v1/users?page_size=101", headers=org_a["sysadmin"]["headers"])
    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "page_size"

    page = client.get("/api/v1/users?page_size=2&sort=-email", headers=org_a["sysadmin"]["headers"]).json()
    assert len(page["data"]) == 2
    assert page["meta"]["total"] == 5
    assert client.get("/api/v1/users?sort=password_hash",
                      headers=org_a["sysadmin"]["headers"]).status_code == 422


def test_service_account_uses_scoped_expiring_api_key(client, org_a, test_engine):
    admin = org_a["sysadmin"]["headers"]
    created = client.post("/api/v1/service-accounts", headers=admin, json={
        "name": "outbox-worker", "role_keys": ["NOTIFICATION_WORKER"], "expires_in_days": 30})
    assert created.status_code == 201, created.text
    account_id = created.json()["user"]["id"]
    key_headers = {"X-API-Key": created.json()["key"]["api_key"]}

    me = client.get("/api/v1/auth/me", headers=key_headers).json()
    assert me["user_type"] == "SERVICE"
    assert me["permissions"] == ["notifications:process"]
    # Narrow scope: it cannot read users.
    assert client.get("/api/v1/users", headers=key_headers).status_code == 403
    # A staff role cannot be given to a service account.
    assert client.post(f"/api/v1/users/{account_id}/roles", headers=admin,
                       json={"role_key": "OPS_ADMIN"}).status_code == 422
    # Service accounts cannot log in with a password.
    assert client.post("/api/v1/auth/login", json={"email": me["email"], "password": PASSWORD}).status_code != 200

    rotated = client.post(f"/api/v1/service-accounts/{account_id}/rotate-key", headers=admin, json={})
    assert client.get("/api/v1/auth/me", headers=key_headers).status_code == 401
    new_headers = {"X-API-Key": rotated.json()["api_key"]}
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 200

    assert client.delete(f"/api/v1/service-accounts/{account_id}/keys", headers=admin).status_code == 204
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 401
    # Its actions are audited under its own identity.
    assert any(e["actor_type"] == "STAFF" for e in audit_events(test_engine, "service_account.create"))


def test_patient_app_token_cannot_call_crm_endpoints(client, org_a, test_engine):
    patient = make_app_user(client, test_engine, org_a["id"], "pat@northfield.example")
    assert client.get("/api/v1/organisation", headers=patient["headers"]).status_code == 403
    assert client.get("/api/v1/users", headers=patient["headers"]).status_code == 403


def test_organisation_settings(client, org_a):
    admin = org_a["sysadmin"]["headers"]
    response = client.patch("/api/v1/organisation", headers=admin, json={
        "timezone": "Europe/Dublin", "settings": {"retention": {"patient_records_years": 10}}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Europe/Dublin"
    assert body["settings"]["retention"]["patient_records_years"] == 10
    assert body["settings"]["retention"]["audit_events_years"] == 8   # other values kept

    assert client.patch("/api/v1/organisation", headers=admin, json={"timezone": "Mars/Base"}).status_code == 422
    assert client.patch("/api/v1/organisation", headers=org_a["ops"]["headers"],
                        json={"name": "Hacked"}).status_code == 403


def test_teams(client, org_a, org_b):
    ops = org_a["ops"]["headers"]
    team = client.post("/api/v1/teams", headers=ops, json={"name": "District Nursing", "service": "Community"})
    assert team.status_code == 201
    team_id = team.json()["id"]
    assert client.post(f"/api/v1/teams/{team_id}/members", headers=ops,
                       json={"user_id": org_a["care"]["id"]}).status_code == 204
    # Staff of another organisation cannot be added.
    assert client.post(f"/api/v1/teams/{team_id}/members", headers=ops,
                       json={"user_id": org_b["care"]["id"]}).status_code == 422
    assert client.post("/api/v1/teams", headers=ops, json={"name": "District Nursing"}).status_code == 409
