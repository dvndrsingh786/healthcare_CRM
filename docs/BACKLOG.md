# Known limitations and next-sprint backlog

Prioritised security and data integrity first, as the sprint specification asks.

## P1: before any production use with real patient data

| # | Item | Why / current state |
|---|---|---|
| 1 | **Plug in a real malware scanner** | `app/storage.py` has the hook, but the default `NoScanner` marks files `NOT_SCANNED` and they can be downloaded. Connect ClamAV or a cloud AV service, and decide whether NOT_SCANNED files may be downloaded at all. |
| 2 | **Object-storage adapter** (S3/Azure/GCS, private bucket, server-side encryption) | Only `LocalStorage` exists, which needs a single instance or shared disk. The adapter interface is five methods. |
| 3 | **Second MFA factor (TOTP/WebAuthn) and SSO/OIDC** | `mfa_enabled` blocks password-only login (`MFA_REQUIRED`), but there is no way to complete a second factor yet. `users.idp_subject` is the SSO hook. Mandatory MFA for staff is recommended. |
| 4 | **Separate database roles and row-level security** | The app should connect as a non-owner DML-only user (migrations as the owner). PostgreSQL RLS on `organisation_id` would add defence in depth to the application-level tenant filter. |
| 5 | **Retention, anonymisation and legal-hold jobs** | `organisations.settings.retention` holds placeholders only. Nothing deletes or anonymises data yet (safe, but not compliant with a retention policy). Includes audit-log and notification retention. |
| 6 | **Field-level encryption design** | Decide with the organisation's threat model whether MRN, date of birth, address and push tokens need application-level encryption on top of storage encryption. |
| 7 | **Threat model, penetration test, backup/restore drill** | Not done in sprint 1. |

## P2: data integrity and operations

| # | Item | Why / current state |
|---|---|---|
| 8 | Archiving a patient should cancel future appointments and open tasks | Today archiving blocks new bookings and edits, and queued messages are skipped, but existing future appointments stay SCHEDULED. |
| 9 | Clean up abandoned uploads | Upload intents never confirmed stay `PENDING_UPLOAD` (and may leave a file). A job should reject them after a few hours and delete the file. |
| 10 | Purge the `rate_limits` table | One small row per key is kept forever. Add a periodic `DELETE … WHERE window_ends_at < now() - interval '1 day'`, or move rate limits to Redis. |
| 11 | Emergency contacts are hard-deleted | Deletion is audited but the row is removed. Confirm the policy; switch to soft delete if contacts must be kept. |
| 12 | Identity-change requests from the app | Patients cannot change their legal name, date of birth or address in the app (by design). A "request a change" flow for staff to verify and apply is the next step. |
| 13 | Signing-key rotation with key ids | Rotating `SECRET_KEY` invalidates document links issued in the last few minutes; a `kid` in the token would allow overlap. |
| 14 | Revoke push devices on logout / sign-out everywhere | Devices are revocable by the user and replaced when a token changes owner, but logout does not remove them. |
| 15 | Metrics exporter, dashboards and alerts | `app/metrics.py` is only a hook. See [RUNBOOK.md](RUNBOOK.md#monitoring) for the alerts to create. |
| 16 | Cursor pagination for long histories | Timeline, audit and notification lists use page/offset, which is fine at sprint-1 volumes. |
| 17 | Load and performance testing | Indexes were checked with `EXPLAIN`, not under load. Needs agreed volumes. |

## P3: product features (from the specification's next-sprint list)

- Custom role administration and a break-glass access workflow with heightened audit and approval (the tables already support organisation-specific roles).
- Real email/SMS/push providers, delivery webhooks, template governance and localisation, preference centre.
- Advanced scheduling: recurring appointments, availability, capacity, waitlist, and automatic reminders (the `appointment_reminder` template exists; nothing schedules it yet).
- Data-subject workflows (access/export requests).
- Interoperability (e.g. FHIR) once concrete external systems are known.
- Reporting/analytics with de-identified data.

## Known limitations (by design for sprint 1)

- The notification provider is a console stand-in: messages are "sent" in-process and not delivered.
- The test suite needs a PostgreSQL user that can create databases and set `session_replication_role` (a superuser such as the default `postgres`); the application itself does not.
- `seed.py` writes demo data with a shared demo password. It refuses to run when `ENVIRONMENT=production`.
- Compliance: the design supports privacy and security obligations but does not certify GDPR, UK GDPR, NHS DSPT, HIPAA or any other framework.
