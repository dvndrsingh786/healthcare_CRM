# Runbook

Operating notes for deploying and running the API. Sprint 1 has not been deployed to a shared
environment yet; this is the intended setup and the checks to make before the first deployment.

## Components

| Component | Command | Notes |
|---|---|---|
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers` (or the Docker image) | Stateless; run 2+ instances behind a TLS-terminating load balancer. |
| Notification worker | `python manage.py process-notifications --loop --interval 10` | Safe to run several (rows are leased with `SKIP LOCKED`). Or call `POST /api/v1/notifications/process` from a scheduler with the NOTIFICATION_WORKER API key. |
| PostgreSQL 16/17 | managed service recommended | Needs `pg_trgm` and `btree_gist`. Encryption at rest, automated backups, point-in-time recovery. |
| File storage | `STORAGE_DIR` (local adapter) | Must be private and on persistent, encrypted storage, never served by a web server. For multiple API instances use shared storage or an object-store adapter (backlog). |

## Deploying a new version

1. Build and test: CI must be green (lint, mypy, tests, clean migration).
2. Back up the database (or confirm the point-in-time recovery window).
3. `python migrate.py`. Each migration runs in one transaction; a failure leaves the schema unchanged.
   Check `python migrate.py status`.
4. Roll out the API instances, then the worker.
5. Check `GET /api/v1/health/ready` on each instance and watch 5xx/429 rates.

**Rollback:** redeploy the previous version. Roll back a schema change only if it is not
compatible with that version: `python migrate.py down 1` (the down section drops what the
migration added, including data in new tables, so take a backup first).

## Configuration and secrets

All settings are environment variables (see `.env.example`, names only). In deployed
environments they come from the platform's secret store, never from a committed file.

| Setting | Notes |
|---|---|
| `ENVIRONMENT=production` | Turns off `/docs` and `/openapi.json` and turns on HSTS. Also stops `seed.py`. |
| `DB_*` | Use a dedicated application database user. It needs DML on all tables and must **not** be a superuser (only the test suite needs superuser, to wipe tables between tests). Run migrations with the schema owner. |
| `SECRET_KEY` | ≥ 32 random characters. Signs document links only (sessions are opaque tokens in the database). |
| `CORS_ORIGINS` | Exact origins of the CRM web app; empty means browsers cannot call the API. |
| `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS` | 15 minutes and 14 days by default. |
| `LOGIN_RATE_LIMIT_PER_MINUTE`, `APP_RATE_LIMIT_PER_MINUTE` | Abuse controls. |
| `MAX_UPLOAD_BYTES`, `SIGNED_URL_SECONDS`, `STORAGE_DIR` | Document limits and storage. |
| `NOTIFICATION_MAX_ATTEMPTS` | Delivery attempts before a message is FAILED. |

### Rotating secrets

- **`SECRET_KEY`:** set the new value and restart. The only effect is that document links issued in the last few minutes stop working (users request a new link).
- **Database password:** create the new password, update the secret, restart the API and worker, then remove the old password.
- **Service-account API keys:** `POST /api/v1/service-accounts/{id}/rotate-key` (the old key stops immediately), update the worker's secret. Keys always expire (max 365 days); rotate before `expires_at`.
- **User sessions:** a user can end all their sessions (`POST /auth/logout-all`); deactivating a user or resetting their password revokes their sessions and keys at once.
- **Suspected leak of a refresh token:** reuse is detected automatically and the session is revoked (`auth.refresh_reuse` in the audit log).

## TLS and network

- Terminate TLS at the load balancer (TLS 1.2+); the API sends HSTS in production. Use `--proxy-headers` only behind a trusted proxy, so client IPs (rate limits, audit) are correct.
- Keep PostgreSQL on a private network; require TLS for database connections in managed environments.
- The storage routes (`/api/v1/storage/...`) are public by design (signed tokens) and rate limited per IP.

## Monitoring

- **Liveness:** `GET /api/v1/health`. **Readiness:** `GET /api/v1/health/ready` (checks the database; 503 when it is unreachable).
- **Logs:** one JSON line per request (`request_id`, method, path, status, duration) plus application events. Query strings, tokens, signed links and personal-data keys are never logged. Ship stdout to the log platform.
- **Correlation:** every response has `X-Request-ID`; the same id is in error bodies, logs and audit events. Clients may send their own (8–64 safe characters).
- **Metrics hook:** `app/metrics.py` counts requests by status class, durations and rate-limit hits. Connect it to Prometheus/StatsD (backlog).
- **Alerts to set up:** 5xx rate, readiness failures, `429` spikes on login (credential stuffing), `access.denied` spikes, `auth.refresh_reuse` events, notifications stuck in QUEUED or growing FAILED counts, and service-account keys close to expiry.

Useful queries (read-only):

```sql
-- security events in the last hour
SELECT action, outcome, count(*) FROM audit_events
WHERE occurred_at > now() - interval '1 hour' AND outcome <> 'SUCCESS' GROUP BY 1, 2;

-- outbox health
SELECT status, count(*), min(next_attempt_at) FROM notifications GROUP BY status;

-- API keys expiring within 14 days
SELECT u.email, k.prefix, k.expires_at FROM api_keys k JOIN users u ON u.id = k.user_id
WHERE k.revoked_at IS NULL AND k.expires_at < now() + interval '14 days';
```

## Common tasks

| Task | How |
|---|---|
| New organisation | `python manage.py create-organisation --name … --slug … --admin-email …` |
| Invite staff | System Admin: `POST /api/v1/users` without a password (they get a one-time code by email) |
| Leaver | `POST /api/v1/users/{id}/deactivate`: sessions and keys are revoked immediately |
| Patient app access | `POST /api/v1/patients/{id}/app-account` (invitation email) |
| Stuck notifications | Check the worker is running; `GET /api/v1/notifications?status=FAILED`; failures carry `last_error_code` |
| Investigate an incident | `GET /api/v1/audit-events` by actor, resource, action or time; match `request_id` with the logs |

## Incident response (security)

1. Contain: deactivate affected users or service accounts (revokes sessions and keys immediately); rotate `SECRET_KEY` if document links may have leaked; rotate the database password if credentials leaked.
2. Investigate with the audit log (append-only) and request-correlated logs.
3. Assess whether personal or health data was affected and follow the organisation's breach-notification procedure (jurisdiction-specific; this project does not certify any framework).
4. Record the follow-up in the backlog.

## Backups and data lifecycle

Use managed PostgreSQL backups with point-in-time recovery, and back up the document storage
with the same retention. Restore drills, retention/anonymisation jobs and legal hold are
backlog items; nothing in the application hard-deletes health records.
