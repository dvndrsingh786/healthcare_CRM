"""Shared test setup.

The tests never touch your real database. At the start we create a brand new, empty
database called hcrm_test_<random>, apply all migrations to it, and drop it at the end.
Before every test we empty the tables, so each test starts from a clean state.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.database import database_url, get_engine, make_engine
from app.main import app
from migrate import run_migrations

# Tables whose rows come from migrations (fixed reference data), so they are kept.
TABLES_TO_KEEP = {"schema_migrations", "permissions", "roles", "role_permissions"}


@pytest.fixture(scope="session")
def test_engine():
    name = "hcrm_test_" + uuid4().hex[:12]
    # CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    admin = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))

    engine = make_engine(database_url(name))
    run_migrations(engine, verbose=False)
    yield engine

    engine.dispose()
    with admin.connect() as db:
        db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def clean_tables(test_engine):
    with test_engine.begin() as db:
        tables = db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )).scalars().all()
        # "replica" mode pauses triggers for this transaction only: foreign-key checks and the
        # append-only guards on audit/consent tables. That lets us wipe everything quickly while
        # keeping the built-in roles and permissions that migrations inserted.
        # (Needs a superuser, like the default "postgres" user; the API itself never does this.)
        db.execute(text("SET LOCAL session_replication_role = replica"))
        for table in tables:
            if table not in TABLES_TO_KEEP:
                db.execute(text(f'DELETE FROM "{table}"'))
        db.execute(text("DELETE FROM roles WHERE organisation_id IS NOT NULL"))


@pytest.fixture
def client(test_engine):
    # "Whenever an endpoint asks for get_engine, give it the test database."
    app.dependency_overrides[get_engine] = lambda: test_engine
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# Two separate organisations. Many tests use "org_b" to try to reach "org_a" data.
@pytest.fixture
def org_a(client, test_engine):
    from helpers import make_organisation
    return make_organisation(client, test_engine, "northfield")


@pytest.fixture
def org_b(client, test_engine):
    from helpers import make_organisation
    return make_organisation(client, test_engine, "southbank")


@pytest.fixture
def sent_messages():
    """Everything the (fake) email/SMS/push provider 'sent' during the test."""
    from app.messaging import ConsoleProvider, set_provider
    provider = ConsoleProvider()
    set_provider(provider)
    yield provider.sent
    set_provider(ConsoleProvider())
