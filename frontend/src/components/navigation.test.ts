import { describe, expect, it } from "vitest";

import type { Me } from "@/api/types";

import { homePath, NAV_ITEMS } from "./navigation";

// Permissions of the built-in roles (migrations/002_create_users_and_rbac.sql).
const ROLES: Record<string, string[]> = {
  SYSTEM_ADMIN: ["org:manage", "users:read", "users:manage", "roles:manage", "audit:read", "notifications:read"],
  OPS_ADMIN: [
    "users:read", "patients:read_all", "patients:read_sensitive", "patients:write", "patients:archive", "assignments:manage",
    "appointments:read", "appointments:write", "appointments:update_outcome", "tasks:read_all", "tasks:write", "notes:read",
    "notes:write", "consents:read", "consents:write", "documents:read", "documents:write", "notifications:send",
    "notifications:read", "summary:read",
  ],
  CARE_STAFF: [
    "users:read", "patients:read_assigned", "patients:read_sensitive", "appointments:read", "appointments:update_outcome",
    "tasks:write", "notes:read", "notes:read_clinical", "notes:write", "consents:read", "consents:write", "documents:read",
    "documents:write", "summary:read",
  ],
  COORDINATOR: [
    "users:read", "patients:read_all", "appointments:read", "appointments:write", "tasks:read_all", "tasks:write",
    "notes:read", "notes:write", "consents:read", "notifications:send", "notifications:read", "summary:read",
  ],
};

function me(role: string): Me {
  return {
    id: "u", email: "x@y.z", user_type: "STAFF", display_name: "X", mfa_enabled: false, last_login_at: null, scope: "crm",
    organisation: { id: "o", name: "Org", timezone: "Europe/London" }, roles: [role], permissions: ROLES[role],
  } as Me;
}

const menu = (role: string) => NAV_ITEMS.filter((item) => item.visible(me(role))).map((item) => item.label);

describe("role-based menu", () => {
  it("system admin: administration only, no patient data", () => {
    expect(menu("SYSTEM_ADMIN")).toEqual(["Users & roles", "Teams", "Service accounts", "Audit log", "Organisation"]);
    expect(homePath(me("SYSTEM_ADMIN"))).toBe("/admin/users");
  });

  it("operations admin: everything operational, teams but not user admin", () => {
    expect(menu("OPS_ADMIN")).toEqual(["Dashboard", "Patients", "Appointments", "Tasks", "Messages", "Teams"]);
    expect(homePath(me("OPS_ADMIN"))).toBe("/");
  });

  it("care staff and coordinators get no administration menu", () => {
    expect(menu("CARE_STAFF")).toEqual(["Dashboard", "Patients", "Appointments", "Tasks"]);
    expect(menu("COORDINATOR")).toEqual(["Dashboard", "Patients", "Appointments", "Tasks", "Messages"]);
  });
});
