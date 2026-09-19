import { Center, Loader } from "@mantine/core";
import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import type { Me } from "@/api/types";
import { RequireAuth, RequirePage } from "@/auth/guards";
import { canSeePatients, canSeeTasks, hasPermission, type Permission } from "@/auth/permissions";
import { AppLayout } from "@/components/AppLayout";
import { canManageTeams, canManageUsers, canSeeMessages } from "@/components/navigation";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

// Pages load on first visit, so e.g. the calendar library is only downloaded when needed.
function lazyPage<M>(load: () => Promise<M>, name: keyof M) {
  return lazy(async () => ({ default: (await load())[name] as ComponentType }));
}
const DashboardPage = lazyPage(() => import("@/pages/DashboardPage"), "DashboardPage");
const AccountPage = lazyPage(() => import("@/pages/AccountPage"), "AccountPage");
const PatientsPage = lazyPage(() => import("@/pages/patients/PatientsPage"), "PatientsPage");
const PatientDetailPage = lazyPage(() => import("@/pages/patients/PatientDetailPage"), "PatientDetailPage");
const AppointmentsPage = lazyPage(() => import("@/pages/appointments/AppointmentsPage"), "AppointmentsPage");
const TasksPage = lazyPage(() => import("@/pages/tasks/TasksPage"), "TasksPage");
const NotificationsPage = lazyPage(() => import("@/pages/NotificationsPage"), "NotificationsPage");
const UsersPage = lazyPage(() => import("@/pages/admin/UsersPage"), "UsersPage");
const TeamsPage = lazyPage(() => import("@/pages/admin/TeamsPage"), "TeamsPage");
const ServiceAccountsPage = lazyPage(() => import("@/pages/admin/ServiceAccountsPage"), "ServiceAccountsPage");
const AuditPage = lazyPage(() => import("@/pages/admin/AuditPage"), "AuditPage");
const OrganisationPage = lazyPage(() => import("@/pages/admin/OrganisationPage"), "OrganisationPage");

const loading = (
  <Center py="xl">
    <Loader />
  </Center>
);

// Each page states which roles may open it. The API enforces the same rules on every request.
function page(allow: ((me: Me) => boolean) | null, element: ReactNode) {
  const content = <Suspense fallback={loading}>{element}</Suspense>;
  return allow ? <RequirePage allow={allow}>{content}</RequirePage> : content;
}
const perm = (permission: Permission) => (me: Me) => hasPermission(me, permission);

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: page(perm("summary:read"), <DashboardPage />) },
      { path: "patients", element: page(canSeePatients, <PatientsPage />) },
      { path: "patients/:patientId", element: page(canSeePatients, <PatientDetailPage />) },
      { path: "appointments", element: page(perm("appointments:read"), <AppointmentsPage />) },
      { path: "tasks", element: page(canSeeTasks, <TasksPage />) },
      { path: "notifications", element: page(canSeeMessages, <NotificationsPage />) },
      { path: "admin/users", element: page(canManageUsers, <UsersPage />) },
      { path: "admin/teams", element: page(canManageTeams, <TeamsPage />) },
      { path: "admin/service-accounts", element: page(perm("users:manage"), <ServiceAccountsPage />) },
      { path: "admin/audit", element: page(perm("audit:read"), <AuditPage />) },
      { path: "admin/organisation", element: page(perm("org:manage"), <OrganisationPage />) },
      { path: "account", element: page(null, <AccountPage />) },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
