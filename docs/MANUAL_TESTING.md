# Manual testing guide

A step-by-step guide for trying the system by hand, with realistic scenarios. No programming needed.
There are two ways to test, and the same scenarios work in both:

- **The CRM web app** (the staff screens): http://localhost:3000 with Docker, or http://localhost:5173
  with `npm run dev`. The easiest way: see [Testing in the web app](#testing-in-the-web-app) below.
- **Swagger** (the interactive API page at http://127.0.0.1:8000/docs): every endpoint, for checking
  the API directly. The rest of this guide describes the Swagger steps.

For the short reviewer checklist see [DEMO.md](DEMO.md). To run all checks automatically:
`python scripts/demo.py`.

## Before you start

The API must be running with the demo data. Either:

- **With Docker** (nothing else to install): follow the
  [Quick start with Docker](../README.md#quick-start-with-docker-easiest-way-to-try-it) in the README, or
- **Without Docker** (Python and PostgreSQL installed):
  ```
  python migrate.py
  python seed.py          (only once, on an empty database)
  uvicorn app.main:app
  ```

Open **http://127.0.0.1:8000/docs** in your browser.

## Demo users

Password for all of them: **`DemoPass123!`**

| Email | Role | What they can do |
|---|---|---|
| `admin@northfield.example` | System Admin | Organisation settings, staff accounts, roles, audit log. **No patient access.** |
| `ops@northfield.example` | Operations Admin | All patients, appointments, tasks, documents, messages. No clinical notes. |
| `nurse@northfield.example` | Care Staff (Nadia Nurse) | Only patients assigned to her; clinical notes; records appointment outcomes. |
| `nurse2@northfield.example` | Care Staff (Noah Nurse) | Same, for his patients (through the District Nursing team). |
| `coordinator@northfield.example` | Coordinator / Support | Scheduling and follow-ups. No date of birth/address, no clinical notes, no documents. |
| `maggie@northfield.example` | Patient (Margaret "Maggie" Okafor) | The patient app only: her own profile, appointments, messages, consents, documents. |
| `ops@southbank.example` (and `admin@`, `nurse@`…) | Staff of a **second organisation** | Used to prove one organisation cannot see another's data. |

The demo data also contains patients Arthur Pembroke and Priya Shah, a team, appointments,
tasks, notes, consents and a shared care-plan document.

## Testing in the web app

Sign in at http://localhost:3000 (Docker) with a demo user and the password `DemoPass123!`. In
development builds the login page lists the demo accounts under **Demo accounts**: click one to fill
it in. Each role sees a different menu; everything is still enforced by the API.

**Scenario 1 (appointment from booking to cancellation) in the web app**

1. Sign in as `ops@northfield.example`. Open **Appointments**, move to a future week with **>**,
   and click an empty time slot. The booking form opens with that time filled in.
2. Choose the patient (type part of the name), the staff member **Nadia Nurse**, a location and an
   internal note. Click **Book**. The appointment opens on the right, status **Scheduled**.
   - Booking the same nurse at an overlapping time is refused with a clear message.
3. Click **Reschedule**, change the time or length, add a reason. The history at the bottom shows it.
4. Click **Cancel**, give a reason. The appointment is now **Cancelled** and cannot be changed.
5. Sign out (top right menu) and sign in as `nurse@northfield.example`: the appointment is on the
   patient's **Appointments** tab, and the nurse has no **Book** or **Cancel** buttons.
6. Sign in as `admin@northfield.example`: **Audit log**, action `appointment.*`, **Search**.

**Other scenarios in the web app**

| Scenario | Where |
|---|---|
| 2. New patient | **Patients → New patient**. Leave a required field empty (refused), give a future date of birth (refused), then save. Save the same name and birth date again: **Possible duplicate** warning. On the patient: **Consent → Record consent**, **Care team → Assign** the nurse. |
| 3. Who can see what | Sign in as each demo user and compare the menu and the **Patients** list. The coordinator sees no date of birth or address; the System Admin sees no patients at all. |
| 4. Clinical notes | As the nurse: patient → **Notes → Add note**, "Who can see it" = **Clinical**. As the coordinator the note is not listed. **Edit** your own note: **Earlier versions** keeps the old text. |
| 5. Messages | As ops: patient → **Messages → Send message**. With Docker the worker sends it within seconds (**Sent**). |
| 6. Follow-up task | **Tasks → New task**, owner Nadia Nurse, due in the past. As the nurse: **My tasks** with **Overdue only**, then the ✓ button. |
| 7. Consent history | Patient → **Consent**: current state on top, every change kept below. |
| 8. Documents | Patient → **Documents → Upload** (a PDF, PNG or JPEG), then the download button. The coordinator has no Documents tab. |
| 9. Admin | As `admin@`: **Users & roles** (create, roles, deactivate), **Service accounts** (key shown once), **Audit log**, **Organisation**. |

## How to log in (Swagger)

1. In the **Auth** section open **`POST /api/v1/auth/login`** and click **Try it out**.
2. Replace the body with:
   ```json
   {"email": "ops@northfield.example", "password": "DemoPass123!"}
   ```
3. Click **Execute**. In the response, copy the value of **`access_token`** (starts with `at_`, without quotes).
4. Scroll to the top, click **Authorize** (padlock), paste the token into **HTTPBearer → Value**
   (just the token, no "Bearer"), click **Authorize**, then **Close**.
5. Check: **`GET /api/v1/auth/me`** → shows who you are, your roles and permissions.

**Switching user:** Authorize → **Logout**, then log in as someone else and paste the new token.

**Leave the second box (APIKeyHeader) empty.** It is for machine accounts, such as the
notification worker (see [Notifications](#scenario-5-messages-to-the-patient)), not for people.

**Tips**

- Tokens last **15 minutes**. On **401 UNAUTHENTICATED**, log in again.
- Five wrong passwords in a minute gives **429 RATE_LIMITED**. Wait a minute.
- Times must be **in the future** and include a time zone, e.g. `2027-03-15T10:00:00+00:00` or `...Z`.
  The dates in the examples below may need moving forward.
- Most ids (patients, users, appointments) come from an earlier response: copy the `id` value.
- Every error has the same shape: `{"error": {"code": ..., "message": ..., "request_id": ...}}`.

## Scenario 1: an appointment from booking to cancellation

In a real clinic, **staff book the appointments** and the patient sees them in the app.
The System Admin has no access to patients or appointments. The Ops Admin sees everyone's schedule.

**1. Find the ids.** Log in as **`ops@`**.

- `GET /api/v1/patients`: copy the `id` of **Margaret Okafor** (MAGGIE_ID).
- `GET /api/v1/users`: copy the `id` of **Nadia Nurse** (NURSE_ID).

**2. Book a home visit.** `POST /api/v1/appointments`:

```json
{"patient_id": "MAGGIE_ID", "staff_user_id": "NURSE_ID",
 "starts_at": "2027-03-22T10:00:00+00:00", "ends_at": "2027-03-22T10:45:00+00:00",
 "timezone": "Europe/London", "appointment_type": "HOME_VISIT",
 "location": "Patient's home", "patient_instructions": "Have your medication list ready",
 "internal_note": "Key safe code with the office"}
```

Expected: **201**, `"status": "SCHEDULED"`, `"version": 1`. Copy the appointment `id` (APPOINTMENT_ID).

- Book the **same nurse at an overlapping time** → **409 `APPOINTMENT_CONFLICT`** (no double booking).
- Book with a time in the past, or without a time zone (`+00:00` or `Z`) → **422**.

**3. The patient sees it in the app.** Log in as **`maggie@`**.

- `GET /api/v1/app/appointments`: the visit is listed with the instructions, but **not** the internal note.
- `GET /api/v1/patients`: **403**. The patient cannot use staff screens.

**4. Reschedule.** Log in as **`ops@`**. `POST /api/v1/appointments/APPOINTMENT_ID/reschedule`:

```json
{"version": 1, "starts_at": "2027-03-23T14:00:00+00:00",
 "ends_at": "2027-03-23T14:45:00+00:00", "reason": "Nurse on training"}
```

Expected: **200**, `"version": 2`. Send the same request again (still `"version": 1`) →
**409 `VERSION_CONFLICT`**: someone changed it since you read it.

**5. The nurse checks her schedule.** Log in as **`nurse@`**.

- `GET /api/v1/appointments`: her appointments (for her patients or booked with her), including this one.
- `GET /api/v1/staff/NURSE_ID/caseload`: the patients she is responsible for.
- `POST /api/v1/appointments/APPOINTMENT_ID/complete` → **409 `INVALID_TRANSITION`**. An outcome can only be recorded once the visit has started.
- `POST /api/v1/appointments/APPOINTMENT_ID/cancel` → **403**. Nurses record outcomes but do not book or cancel.

**6. Ops checks the nurse's schedule.** Log in as **`ops@`**.

- `GET /api/v1/appointments?staff_user_id=NURSE_ID`.
- The same request as **`admin@`** → **403**. The System Admin has no clinical access (by design).

**7. Cancel.** As **`ops@`**, `POST /api/v1/appointments/APPOINTMENT_ID/cancel`:

```json
{"reason": "Patient admitted to hospital"}
```

Then try `/confirm` or `/reschedule` on it → **409**. A cancelled appointment is final.

**8. History, messages and audit.**

- As `ops@`: `GET /api/v1/appointments/APPOINTMENT_ID/history` → CREATED, RESCHEDULED, CANCELLED, each with who, when and why.
- As `ops@`: `GET /api/v1/notifications?reference_id=APPOINTMENT_ID` → the messages queued for Maggie (booked, rescheduled, cancelled).
- As `admin@`: `GET /api/v1/audit-events?resource_id=APPOINTMENT_ID` → the audit trail.

## Scenario 2: a new patient arrives

Log in as **`ops@`**.

1. `POST /api/v1/patients` with a date of birth in the future → **422** with the field named:
   ```json
   {"legal_first_name": "Rosa", "legal_last_name": "Martin", "date_of_birth": "2999-01-01"}
   ```
2. The same with `"date_of_birth": "1950-05-05"`, `"phone": "+44 7700 900111"` → **201**. Copy the id (ROSA_ID).
3. Send it again → **409 `POSSIBLE_DUPLICATE`**. To register a different person with the same name and birthday, add `"confirm_not_duplicate": true`.
4. Find her: `POST /api/v1/patients/search` with `{"search": "martin"}`. Search text goes in the body, never in the URL.
5. Record consent: `POST /api/v1/patients/ROSA_ID/consents`
   ```json
   {"consent_type": "DATA_PROCESSING", "status": "GRANTED", "source": "PAPER_FORM", "policy_version": "privacy-2026.1"}
   ```
6. Assign the nurse: `POST /api/v1/patients/ROSA_ID/assignments`
   ```json
   {"staff_user_id": "NURSE_ID", "assignment_type": "PRIMARY"}
   ```
7. Log in as **`nurse@`**: `GET /api/v1/patients/ROSA_ID` now works. Before step 6 it was **404**.
8. As `admin@`: `GET /api/v1/audit-events?resource_id=ROSA_ID` → patient.create, consent.record, assignment.create.

## Scenario 3: who can see what

| Try this | As | Expected |
|---|---|---|
| `GET /api/v1/patients` | `ops@` | All 3 demo patients (plus any you added) |
| `GET /api/v1/patients` | `nurse@` | Only her assigned patients |
| `GET /api/v1/patients/MAGGIE_ID` | `coordinator@` | Name and contact shown; `date_of_birth`, address and MRN are `null` |
| `GET /api/v1/patients` | `admin@` | **403** |
| `GET /api/v1/patients/MAGGIE_ID` | `ops@southbank.example` | **404**: another organisation cannot even tell the patient exists |
| `GET /api/v1/patients/{id of Arthur Pembroke}` | `nurse@` | **404**: not her patient |
| any `/api/v1/patients...` route | `maggie@` | **403**: patients only use `/api/v1/app/...` |

As `admin@`, `GET /api/v1/audit-events?outcome=DENIED` lists these blocked attempts.

## Scenario 4: the nurse's visit notes

1. As **`nurse@`**: `POST /api/v1/patients/MAGGIE_ID/notes`
   ```json
   {"subject": "Wound check", "body": "Heel improving, dressing changed.", "visibility": "CLINICAL"}
   ```
   Also add one with `"visibility": "APP_VISIBLE"` and `"subject": "See you next week"`.
2. As **`coordinator@`**: `GET /api/v1/patients/MAGGIE_ID/notes`. The CLINICAL note is **not** listed,
   `GET /api/v1/notes/{its id}` → **404**, and it is not on `GET /api/v1/patients/MAGGIE_ID/timeline`.
3. As **`maggie@`**: `GET /api/v1/app/messages` shows only the APP_VISIBLE note.
4. As **`nurse@`**: edit the note with `PATCH /api/v1/notes/{id}` (send `"version": 1` and a new `body`).
   `GET /api/v1/notes/{id}/revisions` still shows the original text.

## Scenario 5: messages to the patient

1. As **`ops@`**: `POST /api/v1/notifications`, with the header **Idempotency-Key** set to `test-00000001`:
   ```json
   {"patient_id": "MAGGIE_ID", "channel": "EMAIL", "template_key": "appointment_reminder"}
   ```
   → **201**. Send exactly the same again → **200** with the **same id**: no duplicate message.
2. Send them: in a terminal run `python manage.py process-notifications`.
3. `GET /api/v1/notifications/{id}` → status **SENT** with its attempt log.
   (Sending is simulated in this environment; nothing actually leaves the machine.)

## Scenario 6: follow-up task

1. As **`coordinator@`**: `POST /api/v1/tasks`
   ```json
   {"title": "Call about new equipment", "patient_id": "MAGGIE_ID", "owner_user_id": "NURSE_ID",
    "due_at": "2026-01-01T09:00:00Z", "priority": "HIGH"}
   ```
2. As **`nurse@`**: `GET /api/v1/tasks?owner=me&status=open&overdue=true` → it is listed as overdue.
3. `POST /api/v1/tasks/{id}/complete` → `completed_by` is the nurse and `completed_at` is set.

## Scenario 7: consent history

1. As **`maggie@`**: `POST /api/v1/app/consents` with
   `{"consent_type": "MARKETING_EMAIL", "status": "GRANTED", "policy_version": "comms-2026.1"}`,
   then again with `"status": "WITHDRAWN"`.
2. As **`ops@`**: `GET /api/v1/patients/MAGGIE_ID/consents/history` shows both records: nothing is overwritten.

## Scenario 8: private documents

1. As **`ops@`**: `GET /api/v1/patients/MAGGIE_ID/documents` lists "Your care plan". Copy its id.
2. `POST /api/v1/documents/{id}/download-link` → a `download_url` valid for 5 minutes.
   Open `http://127.0.0.1:8000` + that path in the browser to download it.
3. Open `http://127.0.0.1:8000/api/v1/storage/download/{document id}` (no signed link) → **403**.
4. As **`coordinator@`**: document endpoints → **403** (support staff have no document access).
5. As **`maggie@`**: `GET /api/v1/app/documents` shows the care plan shared with her.

Uploading a new file takes three calls and a raw file upload that Swagger cannot send, so use
`curl` for that step (see [DEMO.md](DEMO.md#steps), step 8).

## Scenario 9: the System Admin's job

As **`admin@`**:

- Create a staff member (they can log in straight away):
  `POST /api/v1/users`
  ```json
  {"email": "tester@northfield.example", "display_name": "Test Nurse", "role_keys": ["CARE_STAFF"],
   "password": "TestNurse-2026"}
  ```
- `POST /api/v1/users/{id}/deactivate` → the tester's token stops working immediately (**401**).
  `POST /api/v1/users/{id}/activate` brings them back.
- Removing your own SYSTEM_ADMIN role → **403**.
- `GET /api/v1/audit-events` with `action` = `auth.login`, `user.*` or `outcome` = `DENIED`.
  No passwords, tokens or patient details appear, and nobody can edit these entries.

## Accounts cannot be registered publicly

There is no sign-up, by design. Organisations are created by the operator
(`python manage.py create-organisation`), staff by the System Admin (`POST /api/v1/users`), and a
patient's app login by Ops (`POST /api/v1/patients/{id}/app-account`). Accounts created without a
password receive a one-time code by email; email is simulated locally, so give test users a
`password` when you create them.
