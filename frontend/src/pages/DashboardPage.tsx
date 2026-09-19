import { Anchor, Card, Group, SimpleGrid, Stack, Table, Text, ThemeIcon, Title } from "@mantine/core";
import { IconAlertTriangle, IconCalendarEvent, IconCalendarTime, IconChecklist, IconClockHour4 } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { canSeeTasks } from "@/auth/permissions";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, fromNow } from "@/utils/format";

function StatCard({ label, value, icon, color, to }: { label: string; value: number; icon: ReactNode; color: string; to?: string }) {
  const body = (
    <Card withBorder padding="lg">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            {label}
          </Text>
          <Text fz={32} fw={700}>
            {value}
          </Text>
        </Stack>
        <ThemeIcon size={44} radius="md" variant="light" color={color}>
          {icon}
        </ThemeIcon>
      </Group>
    </Card>
  );
  return to ? (
    <Anchor component={Link} to={to} underline="never" c="inherit">
      {body}
    </Anchor>
  ) : (
    body
  );
}

export function DashboardPage() {
  const { me } = useAuth();
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => unwrap(api.GET("/api/v1/summary")), refetchInterval: 60_000 });
  const myTasks = useQuery({
    queryKey: ["tasks", "dashboard-mine"],
    queryFn: () =>
      unwrap(api.GET("/api/v1/tasks", { params: { query: { owner: "me", status: "open", sort: "due_at", page_size: 8 } } })),
    enabled: canSeeTasks(me),
  });
  const s = summary.data;

  return (
    <>
      <PageHeader title={`Hello, ${me?.display_name?.split(" ")[0] ?? ""}`} description={`${me?.organisation.name} · times in ${s?.timezone ?? "your time zone"}`} />
      <QueryState loading={summary.isPending} error={summary.error}>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} mb="lg">
          {s?.appointments && (
            <>
              <StatCard label="Appointments today" value={s.appointments.today} icon={<IconCalendarEvent />} color="blue" to="/appointments" />
              <StatCard label="Next 7 days" value={s.appointments.upcoming_7_days} icon={<IconCalendarTime />} color="teal" to="/appointments" />
            </>
          )}
          {s?.tasks && (
            <>
              <StatCard label="Open tasks" value={s.tasks.open} icon={<IconChecklist />} color="indigo" to="/tasks" />
              <StatCard label="Overdue tasks" value={s.tasks.overdue} icon={<IconAlertTriangle />} color="red" to="/tasks?overdue=1" />
            </>
          )}
        </SimpleGrid>

        <SimpleGrid cols={{ base: 1, lg: 2 }}>
          {canSeeTasks(me) && (
            <Card withBorder>
              <Group justify="space-between" mb="sm">
                <Title order={4}>My open tasks</Title>
                <Anchor component={Link} to="/tasks" size="sm">
                  All tasks
                </Anchor>
              </Group>
              {myTasks.data?.data.length ? (
                <Table>
                  <Table.Tbody>
                    {myTasks.data.data.map((t) => (
                      <Table.Tr key={t.id}>
                        <Table.Td>
                          <Anchor component={Link} to="/tasks" size="sm">
                            {t.title}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>
                          <StatusBadge value={t.priority} size="xs" />
                        </Table.Td>
                        <Table.Td>
                          <Group gap={4} c={t.is_overdue ? "red" : "dimmed"}>
                            <IconClockHour4 size={14} />
                            <Text size="xs">{t.due_at ? formatDateTime(t.due_at) : "No due date"}</Text>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              ) : (
                <EmptyState>No open tasks. Nice work.</EmptyState>
              )}
            </Card>
          )}
          {s?.recently_updated_assigned_patients && (
            <Card withBorder>
              <Title order={4} mb="sm">
                My patients recently updated
              </Title>
              {s.recently_updated_assigned_patients.length ? (
                <Table>
                  <Table.Tbody>
                    {s.recently_updated_assigned_patients.map((p) => (
                      <Table.Tr key={p.id}>
                        <Table.Td>
                          <Anchor component={Link} to={`/patients/${p.id}`} size="sm">
                            {p.display_name}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>
                          <StatusBadge value={p.status} size="xs" />
                        </Table.Td>
                        <Table.Td c="dimmed" fz="xs">
                          {fromNow(p.updated_at)}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              ) : (
                <EmptyState>None of your assigned patients changed in the last 7 days.</EmptyState>
              )}
            </Card>
          )}
        </SimpleGrid>
      </QueryState>
    </>
  );
}
