import { Anchor, Card, Group, Pagination, Select, Table, Text } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { Notification } from "@/api/types";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { NOTIFICATION_STATUSES, PAGE_SIZE } from "@/utils/constants";
import { formatDateTime, humanize, options } from "@/utils/format";

/** Delivery status of messages to patients (the outbox), for the patients you may see. */
export function NotificationsPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["notifications", "list", status, page],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/notifications", {
          params: { query: { status: (status as Notification["status"]) ?? undefined, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  return (
    <>
      <PageHeader
        title="Messages"
        description="Emails, texts and app notifications to patients. The notification worker sends queued messages and retries failures."
      />
      <Card withBorder mb="md">
        <Select
          placeholder="Any status"
          data={options(NOTIFICATION_STATUSES)}
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          clearable
          w={200}
        />
      </Card>
      <Card withBorder p={0}>
        <QueryState loading={list.isPending} error={list.error}>
          {list.data?.data.length ? (
            <Table verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Message</Table.Th>
                  <Table.Th>Channel</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Attempts</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th>Patient</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data.data.map((n) => (
                  <Table.Tr key={n.id}>
                    <Table.Td>
                      {humanize(n.template_key)}
                      <Text size="xs" c="dimmed">
                        {n.transactional ? "About the patient's care" : "General"}
                      </Text>
                    </Table.Td>
                    <Table.Td>{n.channel}</Table.Td>
                    <Table.Td>
                      <StatusBadge value={n.status} />
                      {(n.skip_reason || n.last_error_code) && (
                        <Text size="xs" c="dimmed">
                          {humanize(n.skip_reason ?? n.last_error_code)}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {n.attempts} / {n.max_attempts}
                    </Table.Td>
                    <Table.Td fz="sm">{formatDateTime(n.created_at)}</Table.Td>
                    <Table.Td>
                      {n.patient_id && (
                        <Anchor component={Link} to={`/patients/${n.patient_id}?tab=messages`} size="sm">
                          Open
                        </Anchor>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <EmptyState>No messages.</EmptyState>
          )}
        </QueryState>
      </Card>
      {list.data && list.data.meta.total_pages > 1 && (
        <Group justify="flex-end" mt="md">
          <Pagination total={list.data.meta.total_pages} value={page} onChange={setPage} />
        </Group>
      )}
    </>
  );
}
