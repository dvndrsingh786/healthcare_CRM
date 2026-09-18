"""Organisations (tenants).

There is no public sign-up: a healthcare organisation is created by the platform operator
(seed script or `python manage.py create-organisation`), together with its first System Admin.
"""
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from app.audit import changed_fields, record_event
from app.errors import invalid

# Data lifecycle placeholders. Real values come from the organisation's approved policy;
# the retention/archival jobs that use them are next-sprint work (see docs/BACKLOG.md).
DEFAULT_SETTINGS = {
    "retention": {
        "patient_records_years": 8,
        "audit_events_years": 8,
        "notifications_days": 365,
        # Closing an app account never hard-deletes the health record.
        "delete_on_app_account_closure": False,
    },
    "notifications": {
        # Transactional messages (appointment changes, security) are sent even if a patient
        # opted out of that channel, unless the organisation turns this off.
        "transactional_ignores_opt_out": True,
    },
}


def check_timezone(name):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise invalid("Unknown time zone. Use an IANA name such as Europe/London.", field="timezone") from error
    return name


def create_organisation(db, name, slug, timezone="Europe/London", data_region="uk"):
    check_timezone(timezone)
    return db.execute(
        text("""
            INSERT INTO organisations (name, slug, timezone, data_region, settings)
            VALUES (:name, :slug, :timezone, :region, CAST(:settings AS JSONB))
            RETURNING id
        """),
        {"name": name, "slug": slug, "timezone": timezone, "region": data_region,
         "settings": json.dumps(DEFAULT_SETTINGS)},
    ).scalar_one()


def get_organisation(db, principal):
    return db.execute(
        text("""SELECT id, name, slug, status, timezone, data_region, settings, created_at, updated_at
                FROM organisations WHERE id = :id"""),
        {"id": principal["organisation_id"]},
    ).mappings().one()


def update_organisation(db, principal, changes):
    old = dict(get_organisation(db, principal))
    if "timezone" in changes:
        check_timezone(changes["timezone"])
    if "settings" in changes:
        # Merge one level deep, so a PATCH of one retention value keeps the others.
        merged = dict(old["settings"])
        for section, values in changes["settings"].items():
            merged[section] = {**merged.get(section, {}), **values}
        changes["settings"] = json.dumps(merged)
    if changes:
        sets = ", ".join(
            f"{column} = CAST(:{column} AS JSONB)" if column == "settings" else f"{column} = :{column}"
            for column in changes
        )
        db.execute(text(f"UPDATE organisations SET {sets} WHERE id = :id"),
                   dict(changes, id=principal["organisation_id"]))
    record_event(db, principal, "organisation.update", "organisation", principal["organisation_id"],
                 changed_fields=changed_fields(old, {k: v for k, v in changes.items() if k != "settings"})
                 + (["settings"] if "settings" in changes else []))
