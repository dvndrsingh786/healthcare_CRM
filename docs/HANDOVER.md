# End-of-sprint handover

Filled in from the specification's handover template (§17).

| Field | Status |
|---|---|
| **Branch / PR** | `main` on [github.com/dvndrsingh786/healthcare_CRM](https://github.com/dvndrsingh786/healthcare_CRM), one commit per sprint day (foundation → identity & access → patients → appointments/tasks/outbox → notes/consent/documents/timeline → app API/audit → hardening → handover). |
| **Environment tested** | Windows 11, Python 3.14, PostgreSQL 17 (local). CI: Ubuntu, Python 3.12, PostgreSQL 17 (GitHub Actions, green). End-to-end demo (`scripts/demo.py`) run against a live `uvicorn` server with seeded data. |
| **Database migration version** | `008_create_notes_consents_documents.sql` (8 migrations, all with tested down sections). |
| **Implemented modules** | auth, users & RBAC (incl. teams, service accounts), organisations, patients (+ emergency contacts, app accounts), assignments & caseload, appointments, tasks, notes/interactions, consent, documents & private storage, timeline, notifications (outbox, worker, devices), CRM summary, audit search, patient app API, health. 98 endpoints. |
| **Automated test result** | `pytest`: 92 passed. `ruff check .`: clean. `mypy`: no issues (77 files). All mandatory scenarios in spec §11 have a named test (see [DEMO.md](DEMO.md)). |
| **API documentation location** | Swagger UI at `/docs` (development), `docs/openapi.json` (committed; regenerate with `python manage.py export-openapi`). Each endpoint documents its permission and possible error codes; the main create endpoints include request examples. |
| **Demo credentials / seed users** | Created by `python seed.py`: `admin@`, `ops@`, `nurse@`, `nurse2@`, `coordinator@` and patient `maggie@northfield.example`, plus the same staff at `@southbank.example`. Demo password `DemoPass123!` (demo only; override with `SEED_PASSWORD`). |
| **Known issues** | None open against the specification. Limitations by design are listed in [BACKLOG.md](BACKLOG.md#known-limitations-by-design-for-sprint-1). |
| **Security/privacy follow-ups** | Before production: real malware scanner, object-storage adapter, MFA second factor, separate database roles + RLS, retention jobs, field-level encryption decision, threat model and pen test ([BACKLOG.md](BACKLOG.md) P1). |
| **Recommended next task** | P1 items 1–3 (scanner, object storage, MFA), then item 8 (archiving a patient cancels future appointments). |

## Where to start reading

1. [README.md](../README.md): setup, commands, troubleshooting.
2. [ARCHITECTURE.md](ARCHITECTURE.md): modules, permission strategy, audit, storage, notifications, app boundary.
3. `app/modules/patients/access.py`: the object-level rule most modules reuse.
4. `app/security.py`: authentication, scopes and permission checks.
5. `tests/`: each file reads as a specification of its module.

## Mandatory test scenarios (spec §11)

| Scenario | Test |
|---|---|
| Login succeeds/fails safely; rate limiting | `test_auth.py` |
| Revoked/expired token rejected | `test_auth.py` |
| Support role cannot access restricted clinical notes | `test_notes_and_timeline.py::test_support_role_cannot_see_restricted_clinical_notes` |
| App user A cannot retrieve/infer patient B by guessed UUID | `test_app_api.py::test_app_user_cannot_reach_crm_or_another_patient`, `::test_app_user_sees_only_own_app_visible_appointments` |
| Organisation A cannot access organisation B data | `test_rbac.py::test_users_of_another_organisation_are_invisible`, `test_patients.py::test_other_organisation_cannot_reach_patients` (and a cross-tenant case in every module's tests) |
| Patient create rejects bad DOB/contact data and omissions; identifier conflicts | `test_patients.py::test_create_rejects_bad_and_missing_data`, `::test_duplicate_rules` |
| Invalid appointment transitions; cancel/reschedule audited | `test_appointments.py::test_invalid_transitions_are_refused`, `::test_lifecycle_with_history_audit_and_notification` |
| Task completion records actor and timestamp | `test_tasks.py::test_follow_up_lifecycle` |
| Consent update preserves prior evidence | `test_consents.py::test_consent_change_preserves_prior_evidence` |
| Document download needs current authorisation | `test_documents.py::test_download_requires_current_authorisation` |
| Audit log holds no passwords, tokens or document bodies | `test_audit.py::test_audit_log_has_no_secrets_or_sensitive_payloads` |
| Notification retry idempotent; provider failure recorded | `test_notifications.py` (retry/backoff, crash after send, max attempts) |
| Max page size; filters cannot bypass scope | `test_rbac.py::test_pagination_has_a_maximum_page_size`, `test_patients.py::test_care_staff_only_see_assigned_patients`, `test_tasks.py::test_task_visibility_and_change_rights` |
| Migrations apply to an empty database; suite passes from clean state | `test_foundation.py::test_migrations_roll_back_and_forward_on_an_empty_database`; CI |
