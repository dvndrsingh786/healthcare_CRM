import { Button, Card, Group, Modal, SegmentedControl, Select, Stack, Switch, Table, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Patient } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { StaffSelect, TeamSelect } from "@/components/pickers";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { formatDate, humanize } from "@/utils/format";

export function AssignmentsTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [history, setHistory] = useState(false);
  const [opened, { open, close }] = useDisclosure(false);
  const [target, setTarget] = useState<"staff" | "team">("staff");
  const [staffId, setStaffId] = useState<string | null>(null);
  const [teamId, setTeamId] = useState<string | null>(null);
  const [type, setType] = useState<string | null>("PRIMARY");

  const assignments = useQuery({
    queryKey: ["patient", patient.id, "assignments", history],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/patients/{patient_id}/assignments", {
          params: { path: { patient_id: patient.id }, query: { include_ended: history } },
        }),
      ),
  });
  const invalidate = [["patient", patient.id, "assignments"], ["patients"]];
  const assign = useApiMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/patients/{patient_id}/assignments", {
          params: { path: { patient_id: patient.id } },
          body:
            target === "team"
              ? { team_id: teamId, assignment_type: "TEAM" }
              : { staff_user_id: staffId, assignment_type: type as "PRIMARY" | "SECONDARY" },
        }),
      ),
    invalidate,
    success: "Assigned",
    onSuccess: () => {
      close();
      setStaffId(null);
      setTeamId(null);
    },
  });
  const end = useApiMutation({
    mutationFn: (assignmentId: string) =>
      unwrap(
        api.POST("/api/v1/patients/{patient_id}/assignments/{assignment_id}/end", {
          params: { path: { patient_id: patient.id, assignment_id: assignmentId } },
        }),
      ),
    invalidate,
    success: "Assignment ended",
  });
  const manage = can("assignments:manage") && patient.status !== "ARCHIVED";

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={5}>Responsible staff and teams</Title>
        <Group>
          <Switch label="Show ended" checked={history} onChange={(e) => setHistory(e.currentTarget.checked)} />
          {manage && (
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={open}>
              Assign
            </Button>
          )}
        </Group>
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        Care staff can only see patients assigned to them or to one of their teams.
      </Text>
      <QueryState loading={assignments.isPending} error={assignments.error}>
        {assignments.data?.length ? (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Who</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>From</Table.Th>
                <Table.Th>Until</Table.Th>
                <Table.Th>Status</Table.Th>
                {manage && <Table.Th />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {assignments.data.map((a) => (
                <Table.Tr key={a.id}>
                  <Table.Td fw={500}>{a.staff_display_name ?? a.team_name}</Table.Td>
                  <Table.Td>{humanize(a.assignment_type)}</Table.Td>
                  <Table.Td>{formatDate(a.starts_on)}</Table.Td>
                  <Table.Td>{formatDate(a.ends_on)}</Table.Td>
                  <Table.Td>
                    <StatusBadge value={a.active ? "ACTIVE" : "INACTIVE"} />
                  </Table.Td>
                  {manage && (
                    <Table.Td>
                      {a.active && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          onClick={() =>
                            modals.openConfirmModal({
                              title: "End this assignment?",
                              children: <Text size="sm">It is kept in the history. Access through it stops now.</Text>,
                              labels: { confirm: "End assignment", cancel: "Keep" },
                              confirmProps: { color: "red" },
                              onConfirm: () => end.mutate(a.id),
                            })
                          }
                        >
                          End
                        </Button>
                      )}
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <EmptyState>Nobody is assigned to this patient yet.</EmptyState>
        )}
      </QueryState>
      <Modal opened={opened} onClose={close} title="Assign to this patient">
        <Stack>
          <SegmentedControl
            value={target}
            onChange={(v) => setTarget(v as "staff" | "team")}
            data={[
              { value: "staff", label: "A staff member" },
              { value: "team", label: "A team" },
            ]}
          />
          {target === "staff" ? (
            <>
              <StaffSelect label="Staff member" value={staffId} onChange={setStaffId} required />
              <Select
                label="Role"
                data={[
                  { value: "PRIMARY", label: "Primary (one per patient)" },
                  { value: "SECONDARY", label: "Secondary" },
                ]}
                value={type}
                onChange={setType}
              />
            </>
          ) : (
            <TeamSelect label="Team" value={teamId} onChange={setTeamId} required />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            <Button loading={assign.isPending} disabled={target === "staff" ? !staffId : !teamId} onClick={() => assign.mutate()}>
              Assign
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
