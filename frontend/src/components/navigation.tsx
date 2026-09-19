import {
  IconBell,
  IconBuildingHospital,
  IconCalendarEvent,
  IconChecklist,
  IconFileSearch,
  IconLayoutDashboard,
  IconRobot,
  IconSettings,
  IconUsers,
  IconUsersGroup,
} from "@tabler/icons-react";
import type { ReactNode } from "react";

import type { Me } from "@/api/types";
import { canSeePatients, canSeeTasks, hasAny, hasPermission } from "@/auth/permissions";

// Admin screens are for the roles that manage things. Care staff and coordinators may read the
// staff list (to pick a colleague), but they get no "Administration" menu.
export const canManageUsers = (me: Me) => hasAny(me, "users:manage", "roles:manage");
export const canManageTeams = (me: Me) => hasAny(me, "assignments:manage", "users:manage");
// Message status is listed per patient you may see, so it is only useful with patient access.
export const canSeeMessages = (me: Me) => hasPermission(me, "notifications:read") && canSeePatients(me);

export interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
  visible: (me: Me) => boolean;
  section?: "admin";
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", to: "/", icon: <IconLayoutDashboard size={18} />, visible: (me) => hasPermission(me, "summary:read") },
  { label: "Patients", to: "/patients", icon: <IconBuildingHospital size={18} />, visible: canSeePatients },
  { label: "Appointments", to: "/appointments", icon: <IconCalendarEvent size={18} />, visible: (me) => hasPermission(me, "appointments:read") },
  { label: "Tasks", to: "/tasks", icon: <IconChecklist size={18} />, visible: canSeeTasks },
  { label: "Messages", to: "/notifications", icon: <IconBell size={18} />, visible: canSeeMessages },
  { label: "Users & roles", to: "/admin/users", icon: <IconUsers size={18} />, visible: canManageUsers, section: "admin" },
  { label: "Teams", to: "/admin/teams", icon: <IconUsersGroup size={18} />, visible: canManageTeams, section: "admin" },
  { label: "Service accounts", to: "/admin/service-accounts", icon: <IconRobot size={18} />, visible: (me) => hasPermission(me, "users:manage"), section: "admin" },
  { label: "Audit log", to: "/admin/audit", icon: <IconFileSearch size={18} />, visible: (me) => hasPermission(me, "audit:read"), section: "admin" },
  { label: "Organisation", to: "/admin/organisation", icon: <IconSettings size={18} />, visible: (me) => hasPermission(me, "org:manage"), section: "admin" },
];

/** The first page this user may open (e.g. the System Admin has no dashboard). */
export function homePath(me: Me) {
  return NAV_ITEMS.find((item) => item.visible(me))?.to ?? "/account";
}

