"""Appointments / visits and their lifecycle.

Status rules (anything else is 409 INVALID_TRANSITION):

    SCHEDULED -> CONFIRMED | CANCELLED | COMPLETED | NO_SHOW
    CONFIRMED -> CANCELLED | COMPLETED | NO_SHOW
    COMPLETED, NO_SHOW, CANCELLED -> (final)

- Only SCHEDULED / CONFIRMED appointments can be edited or rescheduled.
- COMPLETED / NO_SHOW can only be recorded once the appointment has started.
- Every step is written to appointment_events (append-only) and to the audit log.

Who sees an appointment: a caller with appointments:read who may see the patient
(see patients/access.py), or the staff member the appointment is booked with.
"""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.audit import changed_fields, record_event
from app.errors import ApiError, conflict, invalid, not_found
from app.modules.organisations.service import check_timezone
from app.modules.patients.access import check_patient_link, log_denied_access, visible_patient_condition
from app.modules.users.service import active_staff, find_team
from app.pagination import order_by, paginate

TRANSITIONS = {
    "SCHEDULED": {"CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"},
    "CONFIRMED": {"CANCELLED", "COMPLETED", "NO_SHOW"},
}
LIVE_STATUSES = ("SCHEDULED", "CONFIRMED")
# How far in the past a new start time may be (clock differences, a booking made during the visit).
PAST_TOLERANCE = timedelta(minutes=15)

APPOINTMENT_SELECT = """
    SELECT ap.*,
           coalesce(pt.preferred_name, pt.legal_first_name) || ' ' || pt.legal_last_name AS patient_name,
           sp.display_name AS staff_display_name, tm.name AS team_name
    FROM appointments ap
    JOIN patients pt ON pt.id = ap.patient_id
    LEFT JOIN staff_profiles sp ON sp.user_id = ap.staff_user_id
    LEFT JOIN teams tm ON tm.id = ap.team_id
"""

EDITABLE_COLUMNS = {"staff_user_id", "team_id", "appointment_type", "mode", "location", "patient_instructions",
                    "internal_note", "app_visible"}


def appointment_scope(principal, alias="ap"):
    patient_visible, params = visible_patient_condition(principal, f"{alias}.patient_id")
    return (f"{alias}.organisation_id = :org AND ({alias}.staff_user_id = :caller_id OR {patient_visible})",
            params)


def serialize(row):
    out = dict(row)
    local = row["starts_at"].astimezone(ZoneInfo(row["timezone"]))
    out["starts_at_local"] = local.isoformat()
    return out


def find_appointment(db, principal, appointment_id, lock=False):
    condition, params = appointment_scope(principal)
    row = db.execute(
        text(f"{APPOINTMENT_SELECT} WHERE ap.id = :id AND {condition}" + (" FOR UPDATE OF ap" if lock else "")),
        dict(params, id=appointment_id),
    ).mappings().first()
    if row is None:
        log_denied_access(db, principal, "appointment", appointment_id)
        raise not_found("Appointment")
    return row


def get_appointment(db, principal, appointment_id):
    return serialize(find_appointment(db, principal, appointment_id))


def organisation_timezone(db, organisation_id):
    return db.execute(text("SELECT timezone FROM organisations WHERE id = :id"), {"id": organisation_id}).scalar_one()


def check_times(starts_at, ends_at):
    if ends_at <= starts_at:
        raise invalid("ends_at must be after starts_at.", field="ends_at")
    if ends_at - starts_at > timedelta(hours=24):
        raise invalid("An appointment cannot be longer than 24 hours.", field="ends_at")
    if starts_at < datetime.now(UTC) - PAST_TOLERANCE:
        raise invalid("starts_at cannot be in the past.", field="starts_at")


def check_delivery(db, principal, staff_user_id, team_id):
    if staff_user_id is not None:
        try:
            active_staff(db, principal["organisation_id"], staff_user_id)
        except ApiError as error:
            raise invalid("The selected user is not an active staff member of your organisation.",
                          field="staff_user_id") from error
    if team_id is not None:
        try:
            team = find_team(db, principal, team_id)
        except ApiError as error:
            raise invalid("No such team in your organisation.", field="team_id") from error
        if not team["active"]:
            raise invalid("This team is not active.", field="team_id")


def raise_on_overlap(error):
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "ex_appointments_staff_overlap":
        raise conflict("The staff member already has an appointment at this time.",
                       code="APPOINTMENT_CONFLICT") from error
    raise error


def add_event(db, principal, appointment_id, event, from_status, to_status, old_starts_at=None,
              new_starts_at=None, reason=None):
    db.execute(
        text("""
            INSERT INTO appointment_events (organisation_id, appointment_id, event, from_status, to_status,
                                            old_starts_at, new_starts_at, reason, actor_user_id)
            VALUES (:org, :id, :event, :from_status, :to_status, :old_starts_at, :new_starts_at, :reason, :by)
        """),
        {"org": principal["organisation_id"], "id": appointment_id, "event": event, "from_status": from_status,
         "to_status": to_status, "old_starts_at": old_starts_at, "new_starts_at": new_starts_at,
         "reason": reason, "by": principal["user_id"]},
    )


def notify(db, principal, appointment, template_key):
    """Queue a message to the patient about this appointment (see the notifications module).
    Only for appointments the patient can see in the app."""
    from app.modules.notifications.service import queue_patient_notification

    if appointment["app_visible"]:
        queue_patient_notification(db, principal, appointment["patient_id"], template_key,
                                   reference_type="appointment", reference_id=appointment["id"],
                                   event_key=f"{template_key}:v{appointment['version']}")


# ---------- Create / read / update ----------

def create_appointment(db, principal, data):
    patient = check_patient_link(db, principal, data.patient_id)
    if patient["status"] == "ARCHIVED":
        raise ApiError(409, "INVALID_STATE", "Appointments cannot be booked for an archived patient.")
    check_times(data.starts_at, data.ends_at)
    check_delivery(db, principal, data.staff_user_id, data.team_id)
    timezone = check_timezone(data.timezone) if data.timezone else organisation_timezone(
        db, principal["organisation_id"])

    values = data.model_dump(exclude={"timezone"})
    try:
        appointment_id = db.execute(
            text("""
                INSERT INTO appointments (organisation_id, patient_id, staff_user_id, team_id, starts_at, ends_at,
                                          timezone, appointment_type, mode, location, patient_instructions,
                                          internal_note, app_visible, created_by, updated_by)
                VALUES (:org, :patient_id, :staff_user_id, :team_id, :starts_at, :ends_at, :timezone,
                        :appointment_type, :mode, :location, :patient_instructions, :internal_note,
                        :app_visible, :by, :by)
                RETURNING id
            """),
            dict(values, org=principal["organisation_id"], timezone=timezone, by=principal["user_id"]),
        ).scalar_one()
    except IntegrityError as error:
        raise_on_overlap(error)

    add_event(db, principal, appointment_id, "CREATED", None, "SCHEDULED", new_starts_at=data.starts_at)
    record_event(db, principal, "appointment.create", "appointment", appointment_id,
                 metadata={"patient_id": str(data.patient_id)})
    appointment = find_appointment(db, principal, appointment_id)
    notify(db, principal, appointment, "appointment_booked")
    return appointment_id


def list_appointments(db, principal, paging, patient_id=None, staff_user_id=None, team_id=None, status=None,
                      starts_from=None, starts_before=None, sort=None):
    condition, params = appointment_scope(principal)
    conditions = [condition]
    filters = {"patient_id": patient_id, "staff_user_id": staff_user_id, "team_id": team_id, "status": status}
    for column, value in filters.items():
        if value is not None:
            conditions.append(f"ap.{column} = :f_{column}")
            params[f"f_{column}"] = value
    if starts_from is not None:
        conditions.append("ap.starts_at >= :starts_from")
        params["starts_from"] = starts_from
    if starts_before is not None:
        conditions.append("ap.starts_at < :starts_before")
        params["starts_before"] = starts_before

    where = " AND ".join(conditions)
    sortable = {"starts_at": "ap.starts_at", "created_at": "ap.created_at", "updated_at": "ap.updated_at"}
    return paginate(
        db,
        f"{APPOINTMENT_SELECT} WHERE {where} {order_by(sort, sortable, 'starts_at', 'ap.id')}",
        f"SELECT count(*) FROM appointments ap WHERE {where}",
        params, paging, serialize=serialize,
    )


def require_live(appointment, action):
    if appointment["status"] not in LIVE_STATUSES:
        raise ApiError(409, "INVALID_STATE",
                       f"A {appointment['status'].lower()} appointment cannot be {action}.")


def check_version(appointment, version):
    if appointment["version"] != version:
        raise conflict("This appointment was changed by someone else. Reload it and try again.",
                       code="VERSION_CONFLICT")


def update_appointment(db, principal, appointment_id, changes):
    version = changes.pop("version")
    old = find_appointment(db, principal, appointment_id, lock=True)
    require_live(old, "edited")
    check_version(old, version)
    changes = {column: value for column, value in changes.items() if column in EDITABLE_COLUMNS}
    if "app_visible" in changes and changes["app_visible"] is None:
        raise invalid("app_visible cannot be empty.", field="app_visible")
    for required in ("appointment_type", "mode"):
        if required in changes and changes[required] is None:
            raise invalid(f"{required} cannot be empty.", field=required)
    check_delivery(db, principal, changes.get("staff_user_id"), changes.get("team_id"))

    changed = changed_fields(old, changes)
    if not changed:
        return
    sets = ", ".join(f"{column} = :{column}" for column in changed)
    try:
        db.execute(text(f"UPDATE appointments SET {sets}, version = version + 1, updated_by = :by WHERE id = :id"),
                   dict({c: changes[c] for c in changed}, by=principal["user_id"], id=appointment_id))
    except IntegrityError as error:
        raise_on_overlap(error)
    add_event(db, principal, appointment_id, "UPDATED", old["status"], old["status"])
    record_event(db, principal, "appointment.update", "appointment", appointment_id, changed_fields=changed)


def reschedule(db, principal, appointment_id, data):
    old = find_appointment(db, principal, appointment_id, lock=True)
    require_live(old, "rescheduled")
    check_version(old, data.version)
    check_times(data.starts_at, data.ends_at)
    timezone = check_timezone(data.timezone) if data.timezone else old["timezone"]
    try:
        db.execute(
            text("""
                UPDATE appointments SET starts_at = :starts_at, ends_at = :ends_at, timezone = :timezone,
                       status = 'SCHEDULED', version = version + 1, updated_by = :by
                WHERE id = :id
            """),
            {"starts_at": data.starts_at, "ends_at": data.ends_at, "timezone": timezone,
             "by": principal["user_id"], "id": appointment_id},
        )
    except IntegrityError as error:
        raise_on_overlap(error)
    # A confirmed appointment that moves needs confirming again.
    add_event(db, principal, appointment_id, "RESCHEDULED", old["status"], "SCHEDULED",
              old_starts_at=old["starts_at"], new_starts_at=data.starts_at, reason=data.reason)
    record_event(db, principal, "appointment.reschedule", "appointment", appointment_id,
                 changed_fields=["starts_at", "ends_at"] + (["timezone"] if timezone != old["timezone"] else []))
    notify(db, principal, find_appointment(db, principal, appointment_id), "appointment_rescheduled")


# ---------- Lifecycle ----------

def change_status(db, principal, appointment_id, new_status, reason=None):
    appointment = find_appointment(db, principal, appointment_id, lock=True)
    current = appointment["status"]
    if new_status not in TRANSITIONS.get(current, set()):
        raise ApiError(409, "INVALID_TRANSITION",
                       f"An appointment cannot go from {current} to {new_status}.")
    if new_status in ("COMPLETED", "NO_SHOW") and appointment["starts_at"] > datetime.now(UTC):
        raise ApiError(409, "INVALID_TRANSITION", "An outcome can only be recorded once the appointment has started.")

    extra = ""
    if new_status == "CANCELLED":
        extra = ", cancellation_reason = :reason, cancelled_at = now(), cancelled_by = :by"
    elif new_status in ("COMPLETED", "NO_SHOW"):
        extra = ", outcome_recorded_at = now(), outcome_recorded_by = :by"
    db.execute(
        text(f"UPDATE appointments SET status = :status{extra}, version = version + 1, updated_by = :by "
             "WHERE id = :id"),
        {"status": new_status, "reason": reason, "by": principal["user_id"], "id": appointment_id},
    )
    add_event(db, principal, appointment_id, new_status, current, new_status, reason=reason)
    record_event(db, principal, f"appointment.{new_status.lower()}", "appointment", appointment_id,
                 changed_fields=["status"], metadata={"from_status": current})
    if new_status == "CANCELLED":
        notify(db, principal, find_appointment(db, principal, appointment_id), "appointment_cancelled")


def list_events(db, principal, appointment_id):
    find_appointment(db, principal, appointment_id)
    rows = db.execute(
        text("SELECT * FROM appointment_events WHERE appointment_id = :id ORDER BY occurred_at, id"),
        {"id": appointment_id},
    ).mappings()
    return [dict(row) for row in rows]
