# Healthcare CRM API

Backend for a healthcare CRM and its dedicated patient app: staff access and roles, patient
records, assignments, appointments, tasks, notes with visibility controls, consent history,
private documents, a notification outbox, and a searchable audit log.

- **Stack:** Python 3.11+, FastAPI, PostgreSQL 16/17, SQLAlchemy Core (hand-written parameterised SQL), pytest
- **API:** REST/JSON under `/api/v1`, 100 endpoints, OpenAPI at `/docs` (also committed as [docs/openapi.json](docs/openapi.json))
- **Docs:** [Manual testing guide](docs/MANUAL_TESTING.md) · [Architecture](docs/ARCHITECTURE.md) · [Demo checklist](docs/DEMO.md) · [Runbook](docs/RUNBOOK.md) · [Known limitations & backlog](docs/BACKLOG.md) · [Handover](docs/HANDOVER.md)

## Prerequisites

- Python 3.11 or newer
- PostgreSQL 16 or 17 with the standard contrib extensions (`pg_trgm`, `btree_gist`; included in the
  official installers and Docker image). The database user needs to own the database.
  For the test suite it must also be able to create databases (the default `postgres` user can).
- Or Docker, for the database (and optionally the API)

## Setup

```bash
git clone https://github.com/dvndrsingh786/healthcare_CRM.git
cd healthcare_CRM
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt

cp .env.example .env              # then fill in DB_PASSWORD and SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"    # a value for SECRET_KEY
```

Start PostgreSQL, either your own install or `docker compose up -d db` (uses the values from `.env`).
Then create the database if needed (Docker creates it for you):

```bash
psql -U postgres -c "CREATE DATABASE healthcare_crm"
```

## Migrate, seed, run

```bash
python migrate.py                 # apply all migrations (python migrate.py status / down [n])
python seed.py                    # demo organisations, users and data (development only)
uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
python manage.py process-notifications --loop    # the notification worker, in a second terminal
```

Everything in Docker instead: `docker compose up -d --build`, then
`docker compose run --rm api python migrate.py` and `docker compose run --rm api python seed.py`.

### Demo users (created by `seed.py`, demo data only)

Password for all of them: `DemoPass123!` (override with `SEED_PASSWORD`).

| Role | Login | Can |
|---|---|---|
| System Admin | `admin@northfield.example` | settings, users, roles, audit. **No** patient access |
| CRM / Operations Admin | `ops@northfield.example` | all patients (demographics), appointments, tasks, messages. No clinical notes |
| Care Staff | `nurse@northfield.example`, `nurse2@…` | assigned patients only, clinical notes, appointment outcomes |
| Coordinator / Support | `coordinator@northfield.example` | patients without sensitive fields, scheduling, follow-ups. No clinical notes, no documents |
| Patient (app) | `maggie@northfield.example` | only her own profile, appointments, messages, consents, documents |
| Other tenant | `ops@southbank.example` etc. | a second organisation, for cross-tenant checks |

`seed.py` also prints an API key for the `outbox-worker` service account (shown once).

In Swagger (`/docs`): call `POST /api/v1/auth/login`, copy `access_token`, click **Authorize**.

**Trying it by hand?** Follow the [manual testing guide](docs/MANUAL_TESTING.md): how to log in, what each
role can do, and realistic scenarios (booking → reschedule → cancel, a new patient, restricted notes,
documents, consent) with copy-paste request bodies and the expected results.

## Tests and checks

```bash
pytest                 # 94 tests; creates a throwaway database hcrm_test_<random>, drops it at the end
ruff check .           # lint (includes security rules)
mypy                   # type checks
python scripts/demo.py # walks through every required workflow against a running, seeded API
```

The same checks run on every push in GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Operator commands

```bash
python manage.py create-organisation --name "Northfield Health" --slug northfield --admin-email admin@org.example
python manage.py process-notifications [--loop] [--interval 10]
python manage.py export-openapi [docs/openapi.json]
```

There is no public sign-up: organisations and their first System Admin are created by the operator.

## Project layout

```
app/
  main.py              app, middleware and routers
  config.py            settings from environment variables
  security.py          passwords, tokens, principal, permission checks
  audit.py             append-only audit events
  storage.py           private file storage, signed links, malware-scan hook
  messaging.py         email/SMS/push provider abstraction
  modules/<module>/    router.py (thin HTTP) · schemas.py (allow-lists) · service.py (rules + SQL)
    auth, users, organisations, patients, assignments, appointments, tasks, notes, consents,
    documents, timeline, notifications, summary, audit, app_api (the patient app), health
migrations/            numbered SQL files with up and down sections
tests/                 pytest (API + integration)
scripts/demo.py        scripted demo of the required workflows
seed.py, manage.py     demo data and operator commands
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Set DB_PASSWORD in your .env file` | Copy `.env.example` to `.env` and fill it in. |
| `SECRET_KEY must be at least 32 characters` | Generate one with the command above. |
| `connection refused` / readiness returns 503 | PostgreSQL is not running, or `DB_HOST`/`DB_PORT` are wrong. |
| `permission denied to create extension` | The migration needs `pg_trgm` and `btree_gist`. Run as the database owner, or have an admin run `CREATE EXTENSION pg_trgm; CREATE EXTENSION btree_gist;` once. |
| Tests fail with `permission denied to create database` | The test user needs `CREATEDB` (the default `postgres` user has it). |
| `429 RATE_LIMITED` on login while testing | Five attempts per minute per email and IP (`LOGIN_RATE_LIMIT_PER_MINUTE`). Wait a minute. |
| `Demo data already exists` | `seed.py` runs once. Drop and recreate the database, then migrate and seed again. |
| Times rejected with "Include a UTC offset" | Send ISO 8601 with an offset or `Z`, e.g. `2026-10-01T09:30:00+01:00`. In a query string, encode `+` as `%2B` or use `Z`. |
| Uploads return 415 | `PUT` the file with `Content-Type` equal to the `mime_type` declared in the upload intent. |
