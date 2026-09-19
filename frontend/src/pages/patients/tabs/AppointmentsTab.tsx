import { Button, Card, Group, SegmentedControl, Table, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Patient } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { AppointmentDrawer } from "@/pages/appointments/AppointmentDrawer";
import { AppointmentFormModal } from "@/pages/appointments/AppointmentFormModal";
import { dayjs, formatInZone, humanize, patientName } from "@/utils/format";

export function AppointmentsTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [when, setWhen] = useState("upcoming");
  const [booking, { open, close }] = useDisclosure(false);
  const [selected, setSelected] = useState<string | null>(null);
  const now = dayjs().toISOString();
  const appointments = useQuery({
    queryKey: ["appointments", "patient", patient.id, when],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/appointments", {
          params: {
            query: {
              patient_id: patient.id,
              ...(when === "upcoming" ? { from: now, sort: "starts_at" } : { to: now, sort: "-starts_at" }),
              page_size: 50,
            },
          },
        }),
      ),
  });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Group>
          <Title order={5}>Appointments</Title>
          <SegmentedControl
            size="xs"
            value={when}
            onChange={setWhen}
            data={[
              { value: "upcoming", label: "Upcoming" },
              { value: "past", label: "Past" },
            ]}
          />
        </Group>
        {can("appointments:write") && patient.status !== "ARCHIVED" && (
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={open}>
            Book appointment
          </Button>
        )}
      </Group>
      <QueryState loading={appointments.isPending} error={appointments.error}>
        {appointments.data?.data.length ? (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>With</Table.Th>
                <Table.Th>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {appointments.data.data.map((a) => (
                <Table.Tr key={a.id} style={{ cursor: "pointer" }} onClick={() => setSelected(a.id)}>
                  <Table.Td>{formatInZone(a.starts_at, a.timezone)}</Table.Td>
                  <Table.Td>
                    {humanize(a.appointment_type)}
                    <Text size="xs" c="dimmed">
                      {humanize(a.mode)}
                      {a.app_visible ? "" : " · CRM only"}
                    </Text>
                  </Table.Td>
                  <Table.Td>{[a.staff_display_name, a.team_name].filter(Boolean).join(" · ") || "—"}</Table.Td>
                  <Table.Td>
                    <StatusBadge value={a.status} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <EmptyState>{when === "upcoming" ? "No upcoming appointments." : "No past appointments."}</EmptyState>
        )}
      </QueryState>
      <AppointmentFormModal
        opened={booking}
        onClose={close}
        patient={{ id: patient.id, name: patientName(patient) }}
        onSaved={(a) => setSelected(a.id)}
      />
      <AppointmentDrawer appointmentId={selected} onClose={() => setSelected(null)} />
    </Card>
  );
}
