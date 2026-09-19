"""Health endpoints, the error envelope, request IDs, security headers and migrations."""
from sqlalchemy import text

from app.database import database_url, make_engine
from migrate import migration_files, rollback_migrations, run_migrations


def test_health_and_readiness(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").json() == {"status": "ready"}


def test_unknown_route_uses_error_envelope_with_request_id(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    # The same request ID is in the body and the header, so support can find the log lines.
    assert error["request_id"] == response.headers["x-request-id"]


def test_safe_client_request_id_is_kept_and_unsafe_one_replaced(client):
    kept = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123-def"})
    assert kept.headers["x-request-id"] == "abc-123-def"
    replaced = client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    assert replaced.headers["x-request-id"] != "<script>"


def test_security_headers_are_set(client):
    headers = client.get("/api/v1/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cache-control"] == "no-store"
    assert "default-src 'none'" in headers["content-security-policy"]


def test_openapi_is_available(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Healthcare CRM API"


def test_migrations_roll_back_and_forward_on_an_empty_database(test_engine):
    """Down then up again on a scratch copy proves the rollback/forward strategy works."""
    from uuid import uuid4

    from sqlalchemy import create_engine

    name = "hcrm_migr_" + uuid4().hex[:12]
    admin = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    engine = make_engine(database_url(name))
    try:
        run_migrations(engine, verbose=False)
        rollback_migrations(engine, steps=len(migration_files()), verbose=False)
        with engine.connect() as db:
            tables = db.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )).scalars().all()
        assert tables == ["schema_migrations"]
        run_migrations(engine, verbose=False)
        with engine.connect() as db:
            applied = db.execute(text("SELECT count(*) FROM schema_migrations")).scalar()
        assert applied == len(migration_files())
    finally:
        engine.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_empty_settings_fall_back_to_safe_defaults(monkeypatch):
    """STORAGE_DIR= (empty, as in .env.example) must not mean "the current folder"."""
    from app.config import PROJECT_FOLDER, get_settings

    monkeypatch.setenv("STORAGE_DIR", "")
    monkeypatch.setenv("SIGNED_URL_SECONDS", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.storage_dir == PROJECT_FOLDER / "storage"
        assert settings.signed_url_seconds == 300
    finally:
        get_settings.cache_clear()


def test_every_request_body_is_documented_with_a_valid_example():
    """Spec 5 and 13: OpenAPI documents example payloads. Each example must also pass validation,
    so the documentation cannot drift from the real rules."""
    from app.main import app
    from helpers import api_routes

    bodies = [route for route in api_routes(app) if route.body_field is not None]
    assert len(bodies) > 35
    for route in bodies:
        model = route.body_field.field_info.annotation
        examples = (model.model_config.get("json_schema_extra") or {}).get("examples")
        assert examples, f"{route.path} ({model.__name__}) has no example"
        for example in examples:
            model.model_validate(example)
