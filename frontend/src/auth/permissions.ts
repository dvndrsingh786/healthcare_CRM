import type { Me } from "@/api/types";

/** Permission keys checked by the UI. The API enforces them again on every request:
 *  hiding a button is only a convenience, never the security control. */
export type Permission =
  | "org:manage" | "users:read" | "users:manage" | "roles:manage" | "audit:read"
  | "patients:read_all" | "patients:read_assigned" | "patients:read_sensitive" | "patients:write"
  | "patients:archive" | "assignments:manage"
  | "appointments:read" | "appointments:write" | "appointments:update_outcome"
  | "tasks:read_all" | "tasks:write"
  | "notes:read" | "notes:read_clinical" | "notes:write"
  | "consents:read" | "consents:write" | "documents:read" | "documents:write"
  | "notifications:send" | "notifications:read" | "summary:read";

export function hasPermission(me: Me | null | undefined, permission: Permission) {
  return !!me && me.permissions.includes(permission);
}

export function hasAny(me: Me | null | undefined, ...permissions: Permission[]) {
  return permissions.some((p) => hasPermission(me, p));
}

export function canSeePatients(me: Me | null | undefined) {
  return hasAny(me, "patients:read_all", "patients:read_assigned");
}

export function canSeeTasks(me: Me | null | undefined) {
  return hasAny(me, "tasks:read_all", "tasks:write");
}
