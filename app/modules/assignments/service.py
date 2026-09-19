"""Assigning staff members and teams to patients, and each staff member's caseload."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.errors import ApiError, conflict, forbidden, not_found
from app.modules.patients.access import find_patient
from app.modules.users.service import active_staff, find_team
from app.pagination import paginate
from app.security import has

ASSIGNMENT_SELECT = """
    SELECT a.*, staff_profiles.display_name AS staff_display_name, teams.name AS team_name
    FROM patient_assignments a
    LEFT JOIN staff_profiles ON staff_profiles.user_id = a.staff_user_id
    LEFT JOIN teams ON teams.id = a.team_id
"""


def get_assignment(db, assignment_id):
    return db.execute(text(ASSIGNMENT_SELECT + " WHERE a.id = :id"), {"id": assignment_id}).mappings().one()


def assign(db, principal, patient_id, data):
    patient = find_patient(db, principal, patient_id, lock=True)
    if patient["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Archived patients cannot be assigned.")
    if data.staff_user_id is not None:
        active_staff(db, principal["organisation_id"], data.staff_user_id)
    else:
        team = find_team(db, principal, data.team_id)
        if not team["active"]:
            raise ApiError(409, "INVALID_STATE", "This team is not active.")

    try:
        # A savepoint, so a duplicate only undoes this INSERT and we can answer with a clear 409.
        with db.begin_nested():
            assignment_id = db.execute(
                text("""
                    INSERT INTO patient_assignments (organisation_id, patient_id, staff_user_id, team_id,
                                                     assignment_type, starts_on, created_by)
                    VALUES (:org, :patient_id, :staff, :team, :type, coalesce(:starts_on, CURRENT_DATE), :by)
                    RETURNING id
                """),
                {"org": principal["organisation_id"], "patient_id": patient_id, "staff": data.staff_user_id,
                 "team": data.team_id, "type": data.assignment_type, "starts_on": data.starts_on,
                 "by": principal["user_id"]},
            ).scalar_one()
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "")
        if constraint == "uq_assignment_active_primary":
            raise conflict("The patient already has an active PRIMARY assignment. End it first.",
                           code="ASSIGNMENT_CONFLICT") from error
        raise conflict("This staff member or team is already assigned to the patient.",
                       code="ASSIGNMENT_CONFLICT") from error

    record_event(db, principal, "assignment.create", "patient", patient_id,
                 metadata={"assignment_id": str(assignment_id), "type": data.assignment_type,
                           "staff_user_id": str(data.staff_user_id) if data.staff_user_id else None,
                           "team_id": str(data.team_id) if data.team_id else None})
    return get_assignment(db, assignment_id)


def end_assignment(db, principal, patient_id, assignment_id):
    find_patient(db, principal, patient_id)
    ended = db.execute(
        text("""
            UPDATE patient_assignments
            SET active = false, ends_on = greatest(CURRENT_DATE, starts_on), ended_at = now(), ended_by = :by
            WHERE id = :id AND patient_id = :patient_id AND active
            RETURNING id
        """),
        {"id": assignment_id, "patient_id": patient_id, "by": principal["user_id"]},
    ).first()
    if ended is None:
        raise not_found("Active assignment")
    record_event(db, principal, "assignment.end", "patient", patient_id,
                 metadata={"assignment_id": str(assignment_id)})
    return get_assignment(db, assignment_id)


def list_assignments(db, principal, patient_id, include_ended=False):
    find_patient(db, principal, patient_id)
    sql = ASSIGNMENT_SELECT + " WHERE a.patient_id = :patient_id"
    if not include_ended:
        sql += " AND a.active"
    rows = db.execute(text(sql + " ORDER BY a.active DESC, a.created_at DESC"), {"patient_id": patient_id})
    return [dict(row) for row in rows.mappings()]


def caseload(db, principal, staff_user_id, paging):
    """Patients assigned to a staff member, directly or through their teams.

    Staff may always see their own caseload; seeing someone else's needs assignments:manage.
    """
    if str(staff_user_id) != str(principal["user_id"]) and not has(principal, "assignments:manage"):
        raise forbidden("You can only view your own caseload.")
    active_staff(db, principal["organisation_id"], staff_user_id)

    params = {"org": principal["organisation_id"], "staff": staff_user_id}
    base = """
        FROM patients p
        JOIN patient_assignments a ON a.patient_id = p.id AND a.active
        LEFT JOIN teams t ON t.id = a.team_id
        WHERE p.organisation_id = :org AND p.status <> 'ARCHIVED'
          AND (a.staff_user_id = :staff
               OR a.team_id IN (SELECT team_id FROM team_members WHERE user_id = :staff))
    """
    return paginate(
        db,
        f"""SELECT p.id AS patient_id, p.legal_first_name, p.legal_last_name, p.preferred_name, p.status,
                   a.assignment_type, t.name AS via_team, p.updated_at
            {base} ORDER BY p.legal_last_name, p.id, a.id""",
        f"SELECT count(*) {base}",
        params, paging,
    )
