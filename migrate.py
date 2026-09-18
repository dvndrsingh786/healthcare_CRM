"""Applies (or rolls back) the database migrations.

Every file in migrations/ is named NNN_description.sql and has two parts:

    ... SQL that makes the change ...
    -- migrate:down
    ... SQL that undoes it ...

Each file runs inside ONE transaction. PostgreSQL can roll back table changes too,
so a migration that fails half way leaves the database exactly as it was.
Applied files are remembered in the schema_migrations table, so each runs only once.

Usage:
    python migrate.py              apply everything that is new
    python migrate.py down         roll back the latest migration
    python migrate.py down 3       roll back the latest 3 migrations
    python migrate.py status       show which migrations are applied
"""
import sys
from pathlib import Path

from sqlalchemy import text

MIGRATIONS_FOLDER = Path(__file__).resolve().parent / "migrations"
DOWN_MARKER = "-- migrate:down"


def migration_files():
    # sorted() puts 001_..., 002_..., 003_... in the right order.
    return sorted(MIGRATIONS_FOLDER.glob("*.sql"))


def split_file(path):
    sql = path.read_text(encoding="utf-8")
    if DOWN_MARKER not in sql:
        raise ValueError(f"{path.name} has no '{DOWN_MARKER}' section.")
    up, down = sql.split(DOWN_MARKER, 1)
    return up, down


def run_script(db, sql):
    # Send the whole file at once (functions contain ';' inside them). Without parameters,
    # psycopg does not treat '%' as a placeholder, so SQL like 'RAISE ... %' works as written.
    db.connection.dbapi_connection.cursor().execute(sql)


def ensure_table(engine):
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))


def applied_names(engine):
    with engine.connect() as db:
        return list(db.execute(text("SELECT name FROM schema_migrations ORDER BY name")).scalars())


def run_migrations(engine, verbose=True):
    ensure_table(engine)
    done = set(applied_names(engine))
    for path in migration_files():
        if path.name in done:
            continue
        up, _ = split_file(path)
        if verbose:
            print(f"Applying {path.name}")
        with engine.begin() as db:
            run_script(db, up)
            db.execute(text("INSERT INTO schema_migrations (name) VALUES (:name)"), {"name": path.name})


def rollback_migrations(engine, steps=1, verbose=True):
    ensure_table(engine)
    by_name = {path.name: path for path in migration_files()}
    for name in reversed(applied_names(engine)[-steps:]):
        _, down = split_file(by_name[name])
        if verbose:
            print(f"Rolling back {name}")
        with engine.begin() as db:
            run_script(db, down)
            db.execute(text("DELETE FROM schema_migrations WHERE name = :name"), {"name": name})


if __name__ == "__main__":
    from app.database import get_engine

    command = sys.argv[1] if len(sys.argv) > 1 else "up"
    engine = get_engine()
    if command == "up":
        run_migrations(engine)
        print("Database is up to date.")
    elif command == "down":
        rollback_migrations(engine, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif command == "status":
        ensure_table(engine)
        done = set(applied_names(engine))
        for path in migration_files():
            print(("[x] " if path.name in done else "[ ] ") + path.name)
    else:
        sys.exit(__doc__)
