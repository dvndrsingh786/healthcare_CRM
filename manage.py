"""Operator commands.

    python manage.py create-organisation --name "Northfield Health" --slug northfield --admin-email a@b.org
    python manage.py process-notifications [--loop] [--interval 10]
    python manage.py export-openapi [docs/openapi.json]

Organisations are created here (or by seed.py), never through a public API.
"""
import argparse
import getpass
import json
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.database import get_engine


def create_organisation(args):
    from app.errors import ApiError
    from app.modules.organisations.service import create_organisation as create
    from app.modules.users.service import create_user
    from app.schemas import check_password_strength

    password = getpass.getpass("Password for the first System Admin: ")
    if len(password) < 10:
        sys.exit("The password must be at least 10 characters long.")
    try:
        check_password_strength(password)
    except ValueError as error:
        sys.exit(str(error))
    try:
        with get_engine().begin() as db:
            org_id = create(db, args.name, args.slug, args.timezone)
            create_user(db, org_id, args.admin_email, "STAFF", password=password, role_keys=["SYSTEM_ADMIN"],
                        profile={"display_name": args.admin_name, "job_title": "System administrator"})
    except ApiError as error:
        sys.exit(error.message)
    print(f"Organisation {args.slug} created ({org_id}). The System Admin can now log in as {args.admin_email}.")


def process_notifications(args):
    """Run the outbox for every active organisation. The audit identity is SYSTEM.
    In production, prefer the NOTIFICATION_WORKER service account calling the API."""
    from app.modules.notifications.service import process_due

    engine = get_engine()

    def run_once():
        with engine.connect() as db:
            organisations = db.execute(text("SELECT id FROM organisations WHERE status = 'ACTIVE'")).scalars().all()
        totals = {}
        for organisation_id in organisations:
            worker = {"user_id": None, "organisation_id": organisation_id, "user_type": "SYSTEM",
                      "permissions": frozenset({"notifications:process"})}
            for key, value in process_due(engine, worker, args.batch).items():
                totals[key] = totals.get(key, 0) + value
        print(json.dumps(totals), flush=True)

    if not args.loop:
        run_once()
        return
    while True:
        try:
            run_once()
        except Exception as error:  # a long-running worker must survive a database outage
            # Only the error type: messages can contain SQL or data. Leased rows are retried
            # automatically once their lease runs out, so nothing is lost.
            print(json.dumps({"error": type(error).__name__}), file=sys.stderr, flush=True)
        time.sleep(args.interval)


def export_openapi(args):
    from app.main import app

    path = Path(args.path)
    path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    org = commands.add_parser("create-organisation", help="Create a tenant and its first System Admin")
    org.add_argument("--name", required=True)
    org.add_argument("--slug", required=True)
    org.add_argument("--admin-email", required=True)
    org.add_argument("--admin-name", default="System Admin")
    org.add_argument("--timezone", default="Europe/London")
    org.set_defaults(run=create_organisation)

    worker = commands.add_parser("process-notifications", help="Send due notifications")
    worker.add_argument("--loop", action="store_true", help="Keep running")
    worker.add_argument("--interval", type=int, default=10, help="Seconds between runs with --loop")
    worker.add_argument("--batch", type=int, default=100)
    worker.set_defaults(run=process_notifications)

    openapi = commands.add_parser("export-openapi", help="Write the OpenAPI document to a file")
    openapi.add_argument("path", nargs="?", default="docs/openapi.json")
    openapi.set_defaults(run=export_openapi)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
