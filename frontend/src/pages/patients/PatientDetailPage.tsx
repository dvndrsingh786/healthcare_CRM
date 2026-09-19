import { Anchor, Badge, Breadcrumbs, Button, Group, Menu, Modal, Stack, Tabs, Text, TextInput, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconArchive,
  IconBell,
  IconCalendarEvent,
  IconChecklist,
  IconDeviceMobile,
  IconDots,
  IconFileText,
  IconHistory,
  IconId,
  IconNotes,
  IconPencil,
  IconRestore,
  IconShieldCheck,
  IconUsers,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { canSeeTasks } from "@/auth/permissions";
import { QueryState } from "@/components/QueryState";
import { ReasonModal } from "@/components/ReasonModal";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { formatDate, patientName } from "@/utils/format";

import { AppointmentsTab } from "./tabs/AppointmentsTab";
import { AssignmentsTab } from "./tabs/AssignmentsTab";
import { ConsentsTab } from "./tabs/ConsentsTab";
import { DocumentsTab } from "./tabs/DocumentsTab";
import { MessagesTab } from "./tabs/MessagesTab";
import { NotesTab } from "./tabs/NotesTab";
import { OverviewTab } from "./tabs/OverviewTab";
import { TasksTab } from "./tabs/TasksTab";
import { TimelineTab } from "./tabs/TimelineTab";
import { PatientFormModal } from "./PatientFormModal";

export function PatientDetailPage() {
  const { patientId = "" } = useParams();
  const { me, can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const [editing, { open: openEdit, close: closeEdit }] = useDisclosure(false);
  const [archiving, { open: openArchive, close: closeArchive }] = useDisclosure(false);
  const [inviting, { open: openInvite, close: closeInvite }] = useDisclosure(false);
  const [inviteEmail, setInviteEmail] = useState("");

  const patient = useQuery({
    queryKey: ["patient", patientId],
    queryFn: () => unwrap(api.GET("/api/v1/patients/{patient_id}", { params: { path: { patient_id: patientId } } })),
  });
  const path = { params: { path: { patient_id: patientId } } };
  const invalidate = [["patient", patientId], ["patients"]];

  const archive = useApiMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/patients/{patient_id}/archive", { ...path, body: { reason } })),
    invalidate,
    success: "Patient archived",
    onSuccess: closeArchive,
  });
  const restore = useApiMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/patients/{patient_id}/restore", path)),
    invalidate,
    success: "Patient restored",
  });
  const invite = useApiMutation({
    mutationFn: (email: string) => unwrap(api.POST("/api/v1/patients/{patient_id}/app-account", { ...path, body: { email } })),
    invalidate,
    success: "Invitation sent. The patient receives a one-time code to set a password.",
    onSuccess: closeInvite,
  });

  const p = patient.data;
  const archived = p?.status === "ARCHIVED";
  const setTab = (value: string | null) => setParams(value && value !== "overview" ? { tab: value } : {}, { replace: true });

  return (
    <QueryState loading={patient.isPending} error={patient.error}>
      {p && (
        <>
          <Breadcrumbs mb="xs">
            <Anchor component={Link} to="/patients" size="sm">
              Patients
            </Anchor>
            <Text size="sm">{patientName(p)}</Text>
          </Breadcrumbs>
          <Group justify="space-between" align="flex-start" mb="md">
            <Stack gap={4}>
              <Group gap="sm">
                <Title order={2}>{patientName(p)}</Title>
                <StatusBadge value={p.status} size="md" />
                {p.has_app_account && (
                  <Badge variant="outline" leftSection={<IconDeviceMobile size={12} />}>
                    App account
                  </Badge>
                )}
              </Group>
              <Text c="dimmed" size="sm">
                {p.sensitive_fields_hidden
                  ? "Date of birth, address and MRN are hidden for your role."
                  : `Born ${formatDate(p.date_of_birth)}${p.mrn ? ` · MRN ${p.mrn}` : ""}`}
              </Text>
            </Stack>
            {(can("patients:write") || can("patients:archive")) && (
              <Group>
                {can("patients:write") && !archived && (
                  <Button variant="light" leftSection={<IconPencil size={16} />} onClick={openEdit}>
                    Edit
                  </Button>
                )}
                <Menu position="bottom-end">
                  <Menu.Target>
                    <Button variant="default" px="xs" aria-label="More actions">
                      <IconDots size={18} />
                    </Button>
                  </Menu.Target>
                  <Menu.Dropdown>
                    {can("patients:write") && !archived && !p.has_app_account && (
                      <Menu.Item
                        leftSection={<IconDeviceMobile size={16} />}
                        onClick={() => {
                          setInviteEmail(p.email ?? "");
                          openInvite();
                        }}
                      >
                        Invite to the patient app
                      </Menu.Item>
                    )}
                    {can("patients:archive") && !archived && (
                      <Menu.Item color="red" leftSection={<IconArchive size={16} />} onClick={openArchive}>
                        Archive patient
                      </Menu.Item>
                    )}
                    {can("patients:archive") && archived && (
                      <Menu.Item leftSection={<IconRestore size={16} />} onClick={() => restore.mutate()}>
                        Restore patient
                      </Menu.Item>
                    )}
                  </Menu.Dropdown>
                </Menu>
              </Group>
            )}
          </Group>

          <Tabs value={tab} onChange={setTab} keepMounted={false}>
            <Tabs.List mb="md">
              <Tabs.Tab value="overview" leftSection={<IconId size={16} />}>
                Overview
              </Tabs.Tab>
              <Tabs.Tab value="care-team" leftSection={<IconUsers size={16} />}>
                Care team
              </Tabs.Tab>
              {can("appointments:read") && (
                <Tabs.Tab value="appointments" leftSection={<IconCalendarEvent size={16} />}>
                  Appointments
                </Tabs.Tab>
              )}
              {canSeeTasks(me) && (
                <Tabs.Tab value="tasks" leftSection={<IconChecklist size={16} />}>
                  Tasks
                </Tabs.Tab>
              )}
              {can("notes:read") && (
                <Tabs.Tab value="notes" leftSection={<IconNotes size={16} />}>
                  Notes
                </Tabs.Tab>
              )}
              {can("documents:read") && (
                <Tabs.Tab value="documents" leftSection={<IconFileText size={16} />}>
                  Documents
                </Tabs.Tab>
              )}
              {can("consents:read") && (
                <Tabs.Tab value="consents" leftSection={<IconShieldCheck size={16} />}>
                  Consent
                </Tabs.Tab>
              )}
              {can("notifications:read") && (
                <Tabs.Tab value="messages" leftSection={<IconBell size={16} />}>
                  Messages
                </Tabs.Tab>
              )}
              <Tabs.Tab value="timeline" leftSection={<IconHistory size={16} />}>
                Timeline
              </Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="overview">
              <OverviewTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="care-team">
              <AssignmentsTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="appointments">
              <AppointmentsTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="tasks">
              <TasksTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="notes">
              <NotesTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="documents">
              <DocumentsTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="consents">
              <ConsentsTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="messages">
              <MessagesTab patient={p} />
            </Tabs.Panel>
            <Tabs.Panel value="timeline">
              <TimelineTab patient={p} />
            </Tabs.Panel>
          </Tabs>

          <PatientFormModal opened={editing} onClose={closeEdit} patient={p} />
          <ReasonModal
            opened={archiving}
            title="Archive patient"
            label="Why is this patient being archived?"
            confirmLabel="Archive"
            loading={archive.isPending}
            onClose={closeArchive}
            onConfirm={(reason) => archive.mutate(reason)}
          />
          <Modal opened={inviting} onClose={closeInvite} title="Invite to the patient app">
            <Stack>
              <Text size="sm">
                We will create an app account and email a one-time code so the patient can set their own password.
              </Text>
              <TextInput label="Email for the app account" value={inviteEmail} onChange={(e) => setInviteEmail(e.currentTarget.value)} />
              <Group justify="flex-end">
                <Button variant="default" onClick={closeInvite}>
                  Cancel
                </Button>
                <Button loading={invite.isPending} disabled={!/^\S+@\S+\.\S+$/.test(inviteEmail)} onClick={() => invite.mutate(inviteEmail.trim())}>
                  Send invitation
                </Button>
              </Group>
            </Stack>
          </Modal>
        </>
      )}
    </QueryState>
  );
}
