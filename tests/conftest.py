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
        to_empty = [f'"{table}"' for table in tables if table not in TABLES_TO_KEEP]
        if to_empty:
            # TRUNCATE is not blocked by the append-only row triggers, so tests can reset audit data.
            db.execute(text(f"TRUNCATE {', '.join(to_empty)} CASCADE"))


@pytest.fixture
def client(test_engine):
    # "Whenever an endpoint asks for get_engine, give it the test database."
    app.dependency_overrides[get_engine] = lambda: test_engine
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
