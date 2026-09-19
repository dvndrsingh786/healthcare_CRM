import { Button, Card, Code, Group, Pagination, Select, SimpleGrid, Table, Text, TextInput } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { api, unwrap } from "@/api/client";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { StaffSelect } from "@/components/pickers";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, toApiDateTime } from "@/utils/format";

interface Filters {
  actor: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string;
  outcome: string | null;
  from: string | null;
  to: string | null;
}

const EMPTY: Filters = { actor: null, action: "", resource_type: null, resource_id: "", outcome: null, from: null, to: null };
const RESOURCE_TYPES = ["patient", "appointment", "task", "note", "document", "notification", "user", "team", "organisation", "device"];

export function AuditPage() {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);

  const events = useQuery({
    queryKey: ["audit", filters, page],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/audit-events", {
          params: {
            query: {
              actor_user_id: filters.actor ?? undefined,
              action: filters.action.trim() || undefined,
              resource_type: filters.resource_type ?? undefined,
              resource_id: filters.resource_id.trim() || undefined,
              outcome: (filters.outcome as "SUCCESS" | "FAILURE" | "DENIED") ?? undefined,
              from: filters.from ? toApiDateTime(filters.from) : undefined,
              to: filters.to ? toApiDateTime(filters.to) : undefined,
              page,
              page_size: 50,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const apply = () => {
    setFilters(draft);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who did what, when. Append-only: nobody can edit or delete these entries. Your searches are recorded too."
      />
      <Card withBorder mb="md">
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
          <StaffSelect label="Who" placeholder="Anyone" value={draft.actor} onChange={(v) => set("actor", v)} />
          <TextInput
            label="Action"
            placeholder="e.g. patient.* or auth.login"
            value={draft.action}
            onChange={(e) => set("action", e.currentTarget.value)}
          />
          <Select label="Record type" placeholder="Any" clearable data={RESOURCE_TYPES} value={draft.resource_type} onChange={(v) => set("resource_type", v)} />
          <TextInput label="Record id" placeholder="Paste an id" value={draft.resource_id} onChange={(e) => set("resource_id", e.currentTarget.value)} />
          <Select
            label="Outcome"
            placeholder="Any"
            clearable
            data={[
              { value: "SUCCESS", label: "Success" },
              { value: "FAILURE", label: "Failure" },
              { value: "DENIED", label: "Denied (blocked access)" },
            ]}
            value={draft.outcome}
            onChange={(v) => set("outcome", v)}
          />
          <DateTimePicker label="From" clearable value={draft.from} onChange={(v) => set("from", v)} />
          <DateTimePicker label="To" clearable value={draft.to} onChange={(v) => set("to", v)} />
          <Group align="flex-end">
            <Button onClick={apply}>Search</Button>
            <Button
              variant="default"
              onClick={() => {
                setDraft(EMPTY);
                setFilters(EMPTY);
                setPage(1);
              }}
            >
              Clear
            </Button>
          </Group>
        </SimpleGrid>
      </Card>
      <Card withBorder p={0}>
        <QueryState loading={events.isPending} error={events.error}>
          {events.data?.data.length ? (
            <Table verticalSpacing="xs" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>Outcome</Table.Th>
                  <Table.Th>Who</Table.Th>
                  <Table.Th>Record</Table.Th>
                  <Table.Th>Changed fields</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {events.data.data.map((e) => (
                  <Fragment key={e.id}>
                    <Table.Tr style={{ cursor: "pointer" }} onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                      <Table.Td fz="sm">{formatDateTime(e.occurred_at)}</Table.Td>
                      <Table.Td>
                        <Code>{e.action}</Code>
                      </Table.Td>
                      <Table.Td>
                        <StatusBadge value={e.outcome} size="xs" />
                      </Table.Td>
                      <Table.Td fz="xs">
                        {e.actor_type}
                        <Text size="xs" c="dimmed" truncate maw={140}>
                          {e.actor_user_id}
                        </Text>
                      </Table.Td>
                      <Table.Td fz="xs">
                        {e.resource_type}
                        <Text size="xs" c="dimmed" truncate maw={140}>
                          {e.resource_id}
                        </Text>
                      </Table.Td>
                      <Table.Td fz="xs">{e.changed_fields?.join(", ")}</Table.Td>
                    </Table.Tr>
                    {expanded === e.id && (
                      <Table.Tr>
                        <Table.Td colSpan={6} bg="gray.0">
                          <Text size="xs" c="dimmed">
                            Request {e.request_id} · IP {e.ip_address ?? "—"}
                          </Text>
                          <Code block mt={4}>
                            {JSON.stringify(e.metadata, null, 2)}
                          </Code>
                        </Table.Td>
                      </Table.Tr>
                    )}
                  </Fragment>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <EmptyState>No audit events match.</EmptyState>
          )}
        </QueryState>
      </Card>
      {events.data && events.data.meta.total_pages > 1 && (
        <Group justify="space-between" mt="md">
          <Text size="sm" c="dimmed">
            {events.data.meta.total} events
          </Text>
          <Pagination total={events.data.meta.total_pages} value={page} onChange={setPage} />
        </Group>
      )}
    </>
  );
}
