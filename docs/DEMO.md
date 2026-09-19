# Demo checklist

Two ways to demonstrate the sprint:

1. **Scripted:** `python scripts/demo.py` runs every workflow below against a running API and
   prints each check (about 30 checks, a few seconds). It creates a new demo patient each run.
2. **By hand in Swagger** (`/docs`), following the steps below. Log in with
   `POST /api/v1/auth/login`, copy `access_token`, click **Authorize**. Switch user by logging in again.

Setup (once): `python migrate.py && python seed.py`, then `uvicorn app.main:app`.
All demo users use the password `DemoPass123!` (demo data only).

## Reviewer sign-off checklist → where it is shown

| Sign-off item (spec §15) | Demo step | Automated tests |
|---|---|---|
| Clean local setup from README | Setup above | CI: `.github/workflows/ci.yml` |
| Migrations and seed run | `python migrate.py`, `python seed.py` | `test_foundation.py::test_migrations_roll_back_and_forward_on_an_empty_database` |
| OpenAPI can be opened and exercised | `/docs` | `test_foundation.py::test_openapi_is_available` |
| Admin/staff/app roles show different access | Step 1 | `test_rbac.py`, `test_patients.py` |
| Cross-user and cross-tenant access denied | Step 2 | `test_patients.py::test_other_organisation_cannot_reach_patients`, `test_app_api.py` |
| Patient CRUD/search/assignment | Step 3 | `test_patients.py`, `test_assignments.py` |
| Appointment lifecycle | Step 4 | `test_appointments.py` |
| Task/follow-up lifecycle | Step 5 | `test_tasks.py` |
| Restricted note not visible to app/support role | Step 6 | `test_notes_and_timeline.py::test_support_role_cannot_see_restricted_clinical_notes` |
| Consent history | Step 7 | `test_consents.py`, `test_app_api.py::test_app_consent_changes_keep_history` |
| Private document access | Step 8 | `test_documents.py` |
| Audit events generated and queryable | Step 9 | `test_audit.py` |
| Notification outbox/retry | Step 10 | `test_notifications.py` |
| Automated tests pass | `pytest` | 92 tests |
| No secrets/sensitive debug data | `git grep`, log sample | `test_audit.py::test_audit_log_has_no_secrets_or_sensitive_payloads`, `test_workflows.py::test_logs_contain_no_tokens_or_personal_data` |
| Known limitations/backlog documented | [BACKLOG.md](BACKLOG.md) | |

## Steps

**1. Roles.** Log in as each user and call `GET /api/v1/auth/me` to compare `permissions`.
`admin@` → `GET /patients` is 403 (no clinical access by default). `nurse@` → `GET /patients`
lists only assigned patients. `coordinator@` → `GET /patients/{id}` shows `date_of_birth: null`,
`sensitive_fields_hidden: true`. `maggie@` → any CRM route is 403.

**2. Cross-user / cross-tenant.** Copy a Northfield patient id. As `ops@southbank.example`,
`GET /patients/{id}` → 404. As `maggie@`, `GET /app/appointments/{id of another patient's appointment}` → 404.
As `admin@`, `GET /audit-events?action=access.denied` shows the attempts.

**3. New patient intake** (as `ops@`). `POST /patients` with a future `date_of_birth` → 422 with
field errors. Valid body → 201. Same name + date of birth again → 409 `POSSIBLE_DUPLICATE`
(resend with `confirm_not_duplicate: true` to override). `POST /patients/{id}/consents` → 201.
`POST /patients/{id}/assignments` with the nurse's id (from `GET /users`) → 201. `GET /patients?search=…`
finds them, `PATCH /patients/{id}` with a stale `version` → 409 `VERSION_CONFLICT`.

**4. Appointment lifecycle** (as `ops@`). `POST /appointments` (times with an offset, e.g.
`2026-10-01T09:30:00+01:00`). A second booking for the same nurse at an overlapping time → 409
`APPOINTMENT_CONFLICT`. `/confirm`, `/reschedule` (with `version`), `/complete` before the start
→ 409 `INVALID_TRANSITION`, `/cancel` with a reason. `GET /appointments/{id}/history` shows each
step. `GET /notifications?reference_id={id}` shows the queued messages. As `maggie@`,
`GET /app/appointments` shows her own appointments without the internal note.

**5. Follow-up task.** As `coordinator@`, `POST /tasks` owned by the nurse, with a due time in the past.
As `nurse@`, `GET /tasks?owner=me&status=open&overdue=true` lists it; `POST /tasks/{id}/complete`
returns `completed_by` and `completed_at`.

**6. Restricted note.** As `nurse@`, `POST /patients/{maggie}/notes` with `visibility: CLINICAL`.
As `coordinator@` (support) and `ops@`: the notes list, `GET /notes/{id}` (404) and
`GET /patients/{id}/timeline` do not show it. As `maggie@`, `GET /app/messages` shows only APP_VISIBLE notes.

**7. Consent history.** As `maggie@`, `POST /app/consents` `{MARKETING_EMAIL, GRANTED, "comms-2026.1"}`,
then WITHDRAWN. As `ops@`, `GET /patients/{maggie}/consents/history` shows both records with
source APP, captured by the patient; the earlier evidence is kept.

**8. Private document.** As `ops@`: `POST /patients/{id}/documents` → `upload_url`;
`curl -X PUT --data-binary @file.pdf -H "Content-Type: application/pdf" http://127.0.0.1:8000<upload_url>`;
`POST /documents/{id}/confirm`; `POST /documents/{id}/download-link` → open `download_url` within
5 minutes. `GET /api/v1/storage/download/{document id}` (no signed token) → 403. As `coordinator@`,
the document endpoints are 403. As `maggie@`, `GET /app/documents` shows the shared care plan.

**9. Audit.** As `admin@`: `GET /audit-events?resource_id={patient id}` (intake steps),
`?action=document.*`, `?outcome=DENIED`. Each search is itself recorded as `audit.search`.

**10. Notifications.** As `ops@`, `POST /notifications` with header `Idempotency-Key: demo-00000001`
twice → the same id (201 then 200). Run the worker (`python manage.py process-notifications`, or
`POST /notifications/process` with the worker's `X-API-Key` printed by `seed.py`), then
`GET /notifications/{id}` → `SENT` with its attempt log. Retry and failure behaviour is
covered by `tests/test_notifications.py` (a failing provider, backoff, crash-after-send, max attempts).

**11. Dashboard.** `GET /summary` as `nurse@` vs `ops@`: counts differ by what each may see.
