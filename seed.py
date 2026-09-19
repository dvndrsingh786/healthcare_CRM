"""Demo data for local development and the sprint demo. NEVER run against production.

    python seed.py

Creates two organisations (so cross-tenant denial can be demonstrated), one user per role, patients,
assignments, appointments, tasks, notes of every visibility class, consents, a shared document and
a notification-worker service account. Everything goes through the normal service layer, so the
demo data is validated and audited exactly like API calls.

All demo users share the password in SEED_PASSWORD (default: DemoPass123!). Demo data only.
To start again: drop and recreate the database, then run `python migrate.py` and `python seed.py`.
"""
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine
from app.modules.appointments.schemas import AppointmentCreate
from app.modules.appointments.service import create_appointment
from app.modules.assignments.service import assign
from app.modules.consents.schemas import ConsentCreate
from app.modules.consents.service import insert_consent, record_staff_consent
from app.modules.documents.schemas import UploadIntent
from app.modules.documents.service import confirm_upload, create_upload_intent
from app.modules.notes.schemas import NoteCreate
from app.modules.notes.service import create_note
from app.modules.organisations.service import create_organisation
from app.modules.patients.schemas import AssignmentCreate, PatientCreate
from app.modules.patients.service import create_patient
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import create_task
from app.modules.users.schemas import ServiceAccountCreate
from app.modules.users.service import add_team_member, create_service_account, create_team, create_user
from app.security import principal_for_user
from app.storage import get_storage

PASSWORD = os.getenv("SEED_PASSWORD", "DemoPass123!")

STAFF = [
    ("admin", "SYSTEM_ADMIN", "Sam Admin", "System administrator"),
    ("ops", "OPS_ADMIN", "Olivia Ops", "Operations manager"),
    ("nurse", "CARE_STAFF", "Nadia Nurse", "Community nurse"),
    ("nurse2", "CARE_STAFF", "Noah Nurse", "Community nurse"),
    ("coordinator", "COORDINATOR", "Chris Coordinator", "Care coordinator"),
]

SAMPLE_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
              b"trailer<</Root 1 0 R>>\n%%EOF\n")


def at(days=0, hours=0):
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=days, hours=hours)


def seed_organisation(db, name, slug):
    org_id = create_organisation(db, name, slug)
    users = {}
    for key, role, display_name, job_title in STAFF:
        users[key] = create_user(db, org_id, f"{key}@{slug}.example", "STAFF", password=PASSWORD, role_keys=[role],
                                 profile={"display_name": display_name, "job_title": job_title})
    return org_id, users


def principal(db, user_id, scope="crm"):
    return principal_for_user(db, user_id, scope)


def main():
    if get_settings().is_production:
        sys.exit("Refusing to seed demo data in production.")
    engine = get_engine()
    with engine.connect() as db:
        if db.execute(text("SELECT 1 FROM organisations WHERE slug = 'northfield'")).first():
            sys.exit("Demo data already exists. Recreate the database to seed again.")

    with engine.begin() as db:
        org_id, users = seed_organisation(db, "Northfield Community Health", "northfield")
        seed_organisation(db, "Southbank Care", "southbank")
        admin, ops = principal(db, users["admin"]), principal(db, users["ops"])
        nurse, coordinator = principal(db, users["nurse"]), principal(db, users["coordinator"])

        team_id = create_team(db, ops, "District Nursing North", "Community nursing")
        add_team_member(db, ops, team_id, users["nurse2"])

        maggie = create_patient(db, ops, PatientCreate(
            legal_first_name="Margaret", legal_last_name="Okafor", preferred_name="Maggie", date_of_birth="1948-03-14",
            mrn="NF-100245", email="maggie.okafor@example.com", phone="+44 7700 900456", address_line1="12 Elm Road",
            city="Leeds", postcode="LS1 4AB", contact_by_sms=True,
            emergency_contacts=[{"name": "David Okafor", "relationship": "Son", "phone": "+44 7700 900789",
                                 "is_next_of_kin": True}]))
        arthur = create_patient(db, ops, PatientCreate(
            legal_first_name="Arthur", legal_last_name="Pembroke", date_of_birth="1939-11-02", mrn="NF-100310",
            phone="+44 7700 900321", address_line1="4 Mill Lane", city="Leeds", postcode="LS6 2QT"))
        priya = create_patient(db, ops, PatientCreate(
            legal_first_name="Priya", legal_last_name="Shah", date_of_birth="1985-07-21", email="priya@example.com"))

        assign(db, ops, maggie, AssignmentCreate(staff_user_id=users["nurse"], assignment_type="PRIMARY"))
        assign(db, ops, arthur, AssignmentCreate(team_id=team_id, assignment_type="TEAM"))
        assign(db, ops, priya, AssignmentCreate(staff_user_id=users["nurse"], assignment_type="SECONDARY"))

        # Maggie uses the patient app.
        maggie_user = create_user(db, org_id, "maggie@northfield.example", "PATIENT", password=PASSWORD,
                                  role_keys=["APP_USER"], created_by=users["ops"])
        db.execute(text("UPDATE patients SET app_user_id = :u WHERE id = :p"), {"u": maggie_user, "p": maggie})

        visit = create_appointment(db, ops, AppointmentCreate(
            patient_id=maggie, staff_user_id=users["nurse"], starts_at=at(days=1, hours=2),
            ends_at=at(days=1, hours=3), timezone="Europe/London", appointment_type="HOME_VISIT",
            location="Patient's home", patient_instructions="Please have your medication list ready.",
            internal_note="Key safe code held by the office."))
        create_appointment(db, coordinator, AppointmentCreate(
            patient_id=maggie, team_id=team_id, starts_at=at(days=8), ends_at=at(days=8, hours=1),
            appointment_type="REVIEW", mode="PHONE", app_visible=True))
        create_appointment(db, ops, AppointmentCreate(
            patient_id=arthur, staff_user_id=users["nurse2"], starts_at=at(hours=3), ends_at=at(hours=4),
            appointment_type="HOME_VISIT", location="Patient's home"))
        past = create_appointment(db, ops, AppointmentCreate(
            patient_id=maggie, staff_user_id=users["nurse"], starts_at=at(days=2), ends_at=at(days=2, hours=1),
            appointment_type="ASSESSMENT"))
        # A visit that already happened (the API only books future times).
        db.execute(text("UPDATE appointments SET starts_at = now() - interval '7 days', "
                        "ends_at = now() - interval '7 days' + interval '1 hour', status = 'COMPLETED', "
                        "outcome_recorded_at = now() - interval '7 days', outcome_recorded_by = :nurse WHERE id = :id"),
                   {"nurse": users["nurse"], "id": past})

        create_task(db, ops, TaskCreate(title="Confirm pharmacy delivery", owner_user_id=users["nurse"],
                                        patient_id=maggie, appointment_id=visit, priority="HIGH", due_at=at(days=1)))
        create_task(db, coordinator, TaskCreate(title="Call son about care review", owner_user_id=users["coordinator"],
                                                patient_id=maggie, due_at=at(days=-1)))
        create_task(db, ops, TaskCreate(title="Update key safe details", priority="LOW"))

        create_note(db, nurse, maggie, NoteCreate(
            note_type="VISIT", subject="Wound review", visibility="CLINICAL",
            body="Left heel pressure area improving; dressing changed. Review in one week."))
        create_note(db, coordinator, maggie, NoteCreate(
            note_type="PHONE_CALL", subject="Welfare call", visibility="INTERNAL",
            body="Maggie is managing well at home. Son visits on Sundays."))
        create_note(db, nurse, maggie, NoteCreate(
            note_type="MESSAGE", subject="Before your next visit", visibility="APP_VISIBLE",
            body="Please keep your leg raised when resting. See you tomorrow."))

        record_staff_consent(db, ops, maggie, ConsentCreate(
            consent_type="DATA_PROCESSING", status="GRANTED", source="PAPER_FORM", policy_version="privacy-2026.1",
            captured_at=at(days=-30)))
        record_staff_consent(db, nurse, maggie, ConsentCreate(
            consent_type="CARE_INFORMATION_SHARING", status="GRANTED", source="STAFF_VERBAL",
            policy_version="sharing-2026.1", captured_at=at(days=-30)))
        maggie_app = principal(db, maggie_user, "app")
        insert_consent(db, maggie_app, maggie, {"consent_type": "MARKETING_SMS", "status": "GRANTED", "source": "APP",
                                                "policy_version": "comms-2026.1"})
        insert_consent(db, maggie_app, maggie, {"consent_type": "MARKETING_SMS", "status": "WITHDRAWN",
                                                "source": "APP", "policy_version": "comms-2026.1"})

        document_id, _, _ = create_upload_intent(db, ops, maggie, UploadIntent(
            original_filename="care-plan.pdf", mime_type="application/pdf", size_bytes=len(SAMPLE_PDF),
            category="CARE_PLAN", visibility="APP_VISIBLE", title="Your care plan"))
        key = db.execute(text("SELECT storage_key FROM documents WHERE id = :id"), {"id": document_id}).scalar_one()
        get_storage().save(key, [SAMPLE_PDF], max_bytes=len(SAMPLE_PDF))
        confirm_upload(db, ops, document_id)

        _, api_key, _ = create_service_account(db, admin, ServiceAccountCreate(
            name="outbox-worker", role_keys=["NOTIFICATION_WORKER"], expires_in_days=30))

    print("Demo data created.\n")
    print(f"Password for every demo user: {PASSWORD}\n")
    print("Northfield Community Health (organisation A)")
    for key, role, _, _ in STAFF:
        print(f"  {role:<14} {key}@northfield.example")
    print("  APP_USER       maggie@northfield.example   (patient Margaret 'Maggie' Okafor)")
    print("\nSouthbank Care (organisation B, for cross-tenant checks): same user names @southbank.example")
    print("\nNotification worker API key (shown once, send as X-API-Key):")
    print(f"  {api_key}")


if __name__ == "__main__":
    main()
