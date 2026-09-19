import { Button, Card, Group, Modal, Select, Stack, Table, Text, Title } from "@mantine/core";
import { IconSend } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Patient } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { CHANNELS, TEMPLATES } from "@/utils/constants";
import { formatDateTime, humanize, options } from "@/utils/format";

export function NotificationRows({ rows }: { rows: { id: string; channel: string; template_key: string; status: string; skip_reason?: string | null; last_error_code?: string | null; attempts: number; created_at: string; sent_at?: string | null }[] }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Message</Table.Th>
          <Table.Th>Channel</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Created</Table.Th>
          <Table.Th>Sent</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((n) => (
          <Table.Tr key={n.id}>
            <Table.Td>{humanize(n.template_key)}</Table.Td>
            <Table.Td>{n.channel}</Table.Td>
            <Table.Td>
              <StatusBadge value={n.status} />
              {(n.skip_reason || n.last_error_code) && (
                <Text size="xs" c="dimmed">
                  {humanize(n.skip_reason ?? n.last_error_code)}
                  {n.attempts > 1 && ` · ${n.attempts} attempts`}
                </Text>
              )}
            </Table.Td>
            <Table.Td fz="sm">{formatDateTime(n.created_at)}</Table.Td>
            <Table.Td fz="sm">{formatDateTime(n.sent_at)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function MessagesTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [sending, setSending] = useState(false);
  const [channel, setChannel] = useState<string | null>("EMAIL");
  const [template, setTemplate] = useState<string | null>("appointment_reminder");
  // One key per message being composed: if the request is retried (network blip, double
  // submit), the API recognises the key and returns the first message instead of sending twice.
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const openSend = () => {
    setIdempotencyKey(`crm-${crypto.randomUUID()}`);
    setSending(true);
  };
  const notificationsQuery = useQuery({
    queryKey: ["notifications", "patient", patient.id],
    queryFn: () => unwrap(api.GET("/api/v1/notifications", { params: { query: { patient_id: patient.id, page_size: 50 } } })),
    refetchInterval: 15_000,
  });
  const send = useApiMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/notifications", {
          params: { header: { "Idempotency-Key": idempotencyKey } },
          body: {
            patient_id: patient.id,
            channel: channel as "EMAIL" | "SMS" | "PUSH",
            template_key: template!,
          },
        }),
      ),
    invalidate: [["notifications"]],
    success: "Message queued. It is sent within seconds by the worker.",
    onSuccess: () => setSending(false),
  });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Stack gap={0}>
          <Title order={5}>Messages to the patient</Title>
          <Text size="xs" c="dimmed">
            Texts never contain health details, only a prompt to open the app.
          </Text>
        </Stack>
        {can("notifications:send") && patient.status === "ACTIVE" && (
          <Button size="xs" variant="light" leftSection={<IconSend size={14} />} onClick={openSend}>
            Send message
          </Button>
        )}
      </Group>
      <QueryState loading={notificationsQuery.isPending} error={notificationsQuery.error}>
        {notificationsQuery.data?.data.length ? (
          <NotificationRows rows={notificationsQuery.data.data} />
        ) : (
          <EmptyState>No messages yet.</EmptyState>
        )}
      </QueryState>
      <Modal opened={sending} onClose={() => setSending(false)} title="Send a message">
        <Stack>
          <Select label="Message" data={options(TEMPLATES)} value={template} onChange={setTemplate} />
          <Select label="Channel" data={options(CHANNELS)} value={channel} onChange={setChannel} />
          <Text size="xs" c="dimmed">
            The patient's channel preferences and marketing consent are checked when it is sent.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSending(false)}>
              Cancel
            </Button>
            <Button loading={send.isPending} disabled={!template || !channel} onClick={() => send.mutate()}>
              Queue message
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
