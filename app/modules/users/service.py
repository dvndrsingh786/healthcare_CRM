"""Users, roles, staff profiles, teams and service accounts."""
from sqlalchemy import text

from app.audit import changed_fields, record_event
from app.errors import ApiError, conflict, forbidden, invalid, not_found
from app.pagination import like_pattern, order_by, paginate
from app.security import hash_password, hash_token, new_token

# Roles that only a SYSTEM_ADMIN may hand out.
PRIVILEGED_ROLES = {"SYSTEM_ADMIN"}

PROFILE_COLUMNS = ("display_name", "job_title", "phone")


# ---------- Reading ----------

def user_roles(db, user_id):
    return list(db.execute(
        text("""
            SELECT roles.key FROM user_roles JOIN roles ON roles.id = user_roles.role_id
            WHERE user_roles.user_id = :id ORDER BY roles.key
        """),
        {"id": user_id},
    ).scalars())


def user_teams(db, user_id):
    return [dict(row) for row in db.execute(
        text("""
            SELECT teams.id, teams.name FROM team_members JOIN teams ON teams.id = team_members.team_id
            WHERE team_members.user_id = :id ORDER BY teams.name
        """),
        {"id": user_id},
    ).mappings()]


USER_SELECT = """
    SELECT users.id, users.organisation_id, users.email, users.user_type, users.status,
           users.mfa_enabled, users.last_login_at, users.created_at, users.updated_at,
           staff_profiles.display_name, staff_profiles.job_title, staff_profiles.phone
    FROM users
    LEFT JOIN staff_profiles ON staff_profiles.user_id = users.id
"""


def serialize_user(db, row):
    user = dict(row)
    user["roles"] = user_roles(db, user["id"])
    user["teams"] = user_teams(db, user["id"])
    user["profile"] = {key: user.pop(key) for key in PROFILE_COLUMNS}
    return user


def find_user(db, principal, user_id, lock=False):
    """Load a staff/service user of the caller's organisation, or 404."""
    row = db.execute(
        text(USER_SELECT + """
            WHERE users.id = :id AND users.organisation_id = :org AND users.user_type <> 'PATIENT'
        """ + (" FOR UPDATE OF users" if lock else "")),
        {"id": user_id, "org": principal["organisation_id"]},
    ).mappings().first()
    if row is None:
        raise not_found("User")
    return row


def get_user(db, principal, user_id):
    return serialize_user(db, find_user(db, principal, user_id))


def list_users(db, principal, paging, user_type=None, status=None, role=None, search=None, sort=None):
    conditions = ["users.organisation_id = :org", "users.user_type <> 'PATIENT'"]
    params = {"org": principal["organisation_id"]}
    if user_type:
        conditions.append("users.user_type = :user_type")
        params["user_type"] = user_type
    if status:
        conditions.append("users.status = :status")
        params["status"] = status
    if role:
        conditions.append("""EXISTS (SELECT 1 FROM user_roles JOIN roles ON roles.id = user_roles.role_id
                                     WHERE user_roles.user_id = users.id AND roles.key = :role)""")
        params["role"] = role
    if search:
        conditions.append("(users.email ILIKE :search OR staff_profiles.display_name ILIKE :search)")
        params["search"] = like_pattern(search)

    where = " AND ".join(conditions)
    ordering = order_by(sort, {"email": "users.email", "created_at": "users.created_at",
                               "display_name": "staff_profiles.display_name"}, "email", "users.id")
    return paginate(
        db,
        f"{USER_SELECT} WHERE {where} {ordering}",
        f"SELECT count(*) FROM users LEFT JOIN staff_profiles ON staff_profiles.user_id = users.id WHERE {where}",
        params, paging, serialize=lambda row: serialize_user(db, row),
    )


def effective_permissions(db, principal, user_id):
    user = find_user(db, principal, user_id)
    from app.security import load_permissions
    return sorted(load_permissions(db, user["id"], user["user_type"]))


def list_roles(db, principal):
    rows = db.execute(
        text("""
            SELECT roles.id, roles.key, roles.name, roles.description, roles.for_user_type, roles.is_system,
                   coalesce(array_agg(role_permissions.permission_key ORDER BY role_permissions.permission_key)
                            FILTER (WHERE role_permissions.permission_key IS NOT NULL), '{}') AS permissions
            FROM roles
            LEFT JOIN role_permissions ON role_permissions.role_id = roles.id
            WHERE roles.organisation_id IS NULL OR roles.organisation_id = :org
            GROUP BY roles.id
            ORDER BY roles.key
        """),
        {"org": principal["organisation_id"]},
    ).mappings()
    return [dict(row) for row in rows]


# ---------- Creating users ----------

def find_role(db, organisation_id, role_key):
    return db.execute(
        text("""
            SELECT id, key, for_user_type FROM roles
            WHERE key = :key AND (organisation_id IS NULL OR organisation_id = :org)
        """),
        {"key": role_key, "org": organisation_id},
    ).mappings().first()


def add_role(db, organisation_id, user_id, user_type, role_key, assigned_by):
    role = find_role(db, organisation_id, role_key)
    if role is None:
        raise invalid(f"Unknown role: {role_key}.", field="role_key")
    if role["for_user_type"] != user_type:
        raise invalid(f"Role {role_key} cannot be given to a {user_type.lower()} user.", field="role_key")
    db.execute(
        text("""
            INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (:user_id, :role_id, :by)
            ON CONFLICT DO NOTHING
        """),
        {"user_id": user_id, "role_id": role["id"], "by": assigned_by},
    )


def create_user(db, organisation_id, email, user_type, password=None, role_keys=(), created_by=None,
                profile=None):
    """Low-level create used by the API, the seed script and tests. Returns the new user id."""
    exists = db.execute(text("SELECT 1 FROM users WHERE lower(email) = lower(:email)"), {"email": email}).first()
    if exists:
        raise conflict("A user with this email already exists.", code="DUPLICATE_EMAIL")

    user_id = db.execute(
        text("""
            INSERT INTO users (organisation_id, email, user_type, password_hash, created_by, updated_by)
            VALUES (:org, lower(:email), :user_type, :password_hash, :by, :by)
            RETURNING id
        """),
        {"org": organisation_id, "email": email, "user_type": user_type,
         "password_hash": hash_password(password) if password else None, "by": created_by},
    ).scalar_one()

    if profile is not None:
        db.execute(
            text("""
                INSERT INTO staff_profiles (user_id, organisation_id, display_name, job_title, phone)
                VALUES (:user_id, :org, :display_name, :job_title, :phone)
            """),
            {"user_id": user_id, "org": organisation_id, "display_name": profile["display_name"],
             "job_title": profile.get("job_title"), "phone": profile.get("phone")},
        )

    for role_key in role_keys:
        add_role(db, organisation_id, user_id, user_type, role_key, created_by)
    return user_id


def principal_roles(db, principal):
    return set(user_roles(db, principal["user_id"]))


def create_staff_user(db, principal, data):
    caller_roles = principal_roles(db, principal)
    if set(data.role_keys) & PRIVILEGED_ROLES and "SYSTEM_ADMIN" not in caller_roles:
        raise forbidden("Only a System Admin can grant the SYSTEM_ADMIN role.")

    user_id = create_user(
        db, principal["organisation_id"], data.email, "STAFF", password=data.password,
        role_keys=data.role_keys, created_by=principal["user_id"],
        profile={"display_name": data.display_name, "job_title": data.job_title, "phone": data.phone},
    )
    record_event(db, principal, "user.create", "user", user_id,
                 changed_fields=["email", "roles", "profile"], metadata={"roles": list(data.role_keys)})
    return user_id


def update_user(db, principal, user_id, changes):
    user = find_user(db, principal, user_id, lock=True)
    if user["user_type"] != "STAFF":
        raise invalid("Only staff profiles can be edited here.")
    old = {key: user[key] for key in PROFILE_COLUMNS}
    if changes:
        sets = ", ".join(f"{column} = :{column}" for column in changes)
        db.execute(text(f"UPDATE staff_profiles SET {sets} WHERE user_id = :user_id"),
                   dict(changes, user_id=user_id))
        db.execute(text("UPDATE users SET updated_by = :by WHERE id = :id"),
                   {"by": principal["user_id"], "id": user_id})
    record_event(db, principal, "user.update", "user", user_id, changed_fields=changed_fields(old, changes))


def set_status(db, principal, user_id, status):
    user = find_user(db, principal, user_id, lock=True)
    if str(user["id"]) == str(principal["user_id"]):
        raise forbidden("You cannot change the status of your own account.")
    if user["status"] == status:
        return
    db.execute(text("UPDATE users SET status = :status, updated_by = :by WHERE id = :id"),
               {"status": status, "by": principal["user_id"], "id": user_id})
    if status == "INACTIVE":
        # Deactivation takes effect immediately: every session and API key stops working.
        revoke_all_sessions(db, user_id, "user_deactivated")
        db.execute(text("UPDATE api_keys SET revoked_at = now() WHERE user_id = :id AND revoked_at IS NULL"),
                   {"id": user_id})
    record_event(db, principal, "user.activate" if status == "ACTIVE" else "user.deactivate", "user", user_id,
                 changed_fields=["status"])


def revoke_all_sessions(db, user_id, reason):
    db.execute(
        text("UPDATE sessions SET revoked_at = now(), revoked_reason = :reason "
             "WHERE user_id = :id AND revoked_at IS NULL"),
        {"id": user_id, "reason": reason},
    )


def grant_role(db, principal, user_id, role_key):
    user = find_user(db, principal, user_id, lock=True)
    if str(user["id"]) == str(principal["user_id"]):
        raise forbidden("You cannot change your own roles.")
    if role_key in PRIVILEGED_ROLES and "SYSTEM_ADMIN" not in principal_roles(db, principal):
        raise forbidden("Only a System Admin can grant this role.")
    add_role(db, principal["organisation_id"], user_id, user["user_type"], role_key, principal["user_id"])
    record_event(db, principal, "user.role_grant", "user", user_id, changed_fields=["roles"],
                 metadata={"role": role_key})


def revoke_role(db, principal, user_id, role_key):
    user = find_user(db, principal, user_id, lock=True)
    if str(user["id"]) == str(principal["user_id"]):
        raise forbidden("You cannot change your own roles.")
    role = find_role(db, principal["organisation_id"], role_key)
    removed = role is not None and db.execute(
        text("DELETE FROM user_roles WHERE user_id = :user_id AND role_id = :role_id"),
        {"user_id": user_id, "role_id": role["id"]},
    ).rowcount
    if not removed:
        raise not_found("Role assignment")
    record_event(db, principal, "user.role_revoke", "user", user_id, changed_fields=["roles"],
                 metadata={"role": role_key})


# ---------- Teams ----------

def list_teams(db, principal):
    rows = db.execute(
        text("""
            SELECT teams.id, teams.name, teams.service, teams.active,
                   (SELECT count(*) FROM team_members WHERE team_members.team_id = teams.id) AS member_count
            FROM teams WHERE teams.organisation_id = :org ORDER BY teams.name
        """),
        {"org": principal["organisation_id"]},
    ).mappings()
    return [dict(row) for row in rows]


def find_team(db, principal, team_id):
    team = db.execute(
        text("SELECT id, name, service, active FROM teams WHERE id = :id AND organisation_id = :org"),
        {"id": team_id, "org": principal["organisation_id"]},
    ).mappings().first()
    if team is None:
        raise not_found("Team")
    return team


def create_team(db, principal, name, service):
    team_id = db.execute(
        text("INSERT INTO teams (organisation_id, name, service) VALUES (:org, :name, :service) RETURNING id"),
        {"org": principal["organisation_id"], "name": name, "service": service},
    ).scalar_one()
    record_event(db, principal, "team.create", "team", team_id)
    return team_id


def active_staff(db, organisation_id, user_id):
    """The user must be an ACTIVE staff member of the SAME organisation. Same error either way,
    so this cannot be used to discover users of other organisations."""
    found = db.execute(
        text("""
            SELECT 1 FROM users WHERE id = :id AND organisation_id = :org
              AND user_type = 'STAFF' AND status = 'ACTIVE'
        """),
        {"id": user_id, "org": organisation_id},
    ).first()
    if found is None:
        raise invalid("The selected user is not an active staff member of your organisation.", field="user_id")


def add_team_member(db, principal, team_id, user_id):
    find_team(db, principal, team_id)
    active_staff(db, principal["organisation_id"], user_id)
    db.execute(text("INSERT INTO team_members (team_id, user_id) VALUES (:t, :u) ON CONFLICT DO NOTHING"),
               {"t": team_id, "u": user_id})
    record_event(db, principal, "team.member_add", "team", team_id, metadata={"user_id": str(user_id)})


def remove_team_member(db, principal, team_id, user_id):
    find_team(db, principal, team_id)
    removed = db.execute(text("DELETE FROM team_members WHERE team_id = :t AND user_id = :u"),
                         {"t": team_id, "u": user_id}).rowcount
    if not removed:
        raise not_found("Team member")
    record_event(db, principal, "team.member_remove", "team", team_id, metadata={"user_id": str(user_id)})


# ---------- Service accounts ----------

def create_api_key(db, user_id, expires_in_days, created_by):
    raw_key = new_token("hcrm_")
    key_id = db.execute(
        text("""
            INSERT INTO api_keys (user_id, prefix, key_hash, expires_at, created_by)
            VALUES (:user_id, :prefix, :key_hash, now() + make_interval(days => :days), :by)
            RETURNING id
        """),
        {"user_id": user_id, "prefix": raw_key[:12], "key_hash": hash_token(raw_key),
         "days": expires_in_days, "by": created_by},
    ).scalar_one()
    key = db.execute(text("SELECT id, prefix, expires_at FROM api_keys WHERE id = :id"),
                     {"id": key_id}).mappings().one()
    return raw_key, dict(key)


def create_service_account(db, principal, data):
    # Service accounts get an address that can never receive mail or be used to log in.
    email = f"{data.name}.{new_token()[:8].lower()}@service.invalid"
    user_id = create_user(db, principal["organisation_id"], email, "SERVICE", role_keys=data.role_keys,
                          created_by=principal["user_id"],
                          profile={"display_name": data.name, "job_title": "Service account"})
    raw_key, key = create_api_key(db, user_id, data.expires_in_days, principal["user_id"])
    record_event(db, principal, "service_account.create", "user", user_id, metadata={"roles": list(data.role_keys)})
    return user_id, raw_key, key


def rotate_api_key(db, principal, user_id, expires_in_days):
    user = find_user(db, principal, user_id, lock=True)
    if user["user_type"] != "SERVICE":
        raise not_found("Service account")
    if user["status"] != "ACTIVE":
        raise ApiError(409, "INVALID_STATE", "Activate the service account before rotating its key.")
    db.execute(text("UPDATE api_keys SET revoked_at = now() WHERE user_id = :id AND revoked_at IS NULL"),
               {"id": user_id})
    raw_key, key = create_api_key(db, user_id, expires_in_days, principal["user_id"])
    record_event(db, principal, "service_account.rotate_key", "user", user_id)
    return raw_key, key


def revoke_api_keys(db, principal, user_id):
    user = find_user(db, principal, user_id, lock=True)
    if user["user_type"] != "SERVICE":
        raise not_found("Service account")
    db.execute(text("UPDATE api_keys SET revoked_at = now() WHERE user_id = :id AND revoked_at IS NULL"),
               {"id": user_id})
    record_event(db, principal, "service_account.revoke_keys", "user", user_id)
