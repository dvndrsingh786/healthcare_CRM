import { Card, Chip, Group, Pagination, Stack, Text, ThemeIcon, Timeline, Title } from "@mantine/core";
import { IconCalendarEvent, IconChecklist, IconFileText, IconNotes, IconShieldCheck } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Patient } from "@/api/types";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/utils/format";

type EntryType = "appointment" | "note" | "task" | "document" | "consent";

const ICONS: Record<EntryType, { icon: React.ReactNode; color: string; label: string }> = {
  appointment: { icon: <IconCalendarEvent size={14} />, color: "blue", label: "Appointments" },
  note: { icon: <IconNotes size={14} />, color: "grape", label: "Notes" },
  task: { icon: <IconChecklist size={14} />, color: "indigo", label: "Tasks" },
  document: { icon: <IconFileText size={14} />, color: "teal", label: "Documents" },
  consent: { icon: <IconShieldCheck size={14} />, color: "orange", label: "Consent" },
};

/** Everything that happened to this patient, newest first. Entries the user may not read
 *  (e.g. clinical notes for a coordinator) are left out by the API. */
export function TimelineTab({ patient }: { patient: Patient }) {
  const [types, setTypes] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const timeline = useQuery({
    queryKey: ["patient", patient.id, "timeline", types, page],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/patients/{patient_id}/timeline", {
          params: { path: { patient_id: patient.id }, query: { types: types.length ? (types as EntryType[]) : undefined, page, page_size: 30 } },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="md">
        <Title order={5}>Timeline</Title>
        <Chip.Group
          multiple
          value={types}
          onChange={(v) => {
            setTypes(v);
            setPage(1);
          }}
        >
          <Group gap={6}>
            {(Object.keys(ICONS) as EntryType[]).map((t) => (
              <Chip key={t} value={t} size="xs" variant="light">
                {ICONS[t].label}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
      </Group>
      <QueryState loading={timeline.isPending} error={timeline.error}>
        {timeline.data?.data.length ? (
          <Stack>
            <Timeline bulletSize={26} lineWidth={2}>
              {timeline.data.data.map((e) => {
                const meta = ICONS[e.entry_type as EntryType];
                return (
                  <Timeline.Item
                    key={`${e.entry_type}-${e.id}`}
                    bullet={
                      <ThemeIcon size={26} radius="xl" color={meta.color} variant="light">
                        {meta.icon}
                      </ThemeIcon>
                    }
                    title={
                      <Group gap="xs">
                        <Text size="sm" fw={500}>
                          {e.title}
                        </Text>
                        {e.status && <StatusBadge value={e.status} size="xs" />}
                        {e.visibility && <StatusBadge value={e.visibility} size="xs" />}
                      </Group>
                    }
                  >
                    {e.summary && (
                      <Text size="sm" c="dimmed" lineClamp={2}>
                        {e.summary}
                      </Text>
                    )}
                    <Text size="xs" c="dimmed">
                      {formatDateTime(e.occurred_at)}
                      {e.actor_name && ` · ${e.actor_name}`}
                    </Text>
                  </Timeline.Item>
                );
              })}
            </Timeline>
            {timeline.data.meta.total_pages > 1 && (
              <Pagination total={timeline.data.meta.total_pages} value={page} onChange={setPage} />
            )}
          </Stack>
        ) : (
          <EmptyState>Nothing on the timeline yet.</EmptyState>
        )}
      </QueryState>
    </Card>
  );
}
