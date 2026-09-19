import { Button, Card, Group, Modal, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { useForm } from "@mantine/form";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Consent, ConsentType, Patient } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { CONSENT_SOURCES, CONSENT_STATUSES, CONSENT_TYPES } from "@/utils/constants";
import { formatDate, formatDateTime, humanize, options, toApiDateTime } from "@/utils/format";

function ConsentRows({ rows }: { rows: Consent[] }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Consent</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>How</Table.Th>
          <Table.Th>Policy</Table.Th>
          <Table.Th>Given</Table.Th>
          <Table.Th>Recorded</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((c) => (
          <Table.Tr key={c.id}>
            <Table.Td>{humanize(c.consent_type)}</Table.Td>
            <Table.Td>
              <StatusBadge value={c.effective_status} />
              {c.expires_at && (
                <Text size="xs" c="dimmed">
                  until {formatDate(c.expires_at)}
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              {humanize(c.source)}
              <Text size="xs" c="dimmed">
                by {c.captured_by_type === "PATIENT" ? "the patient" : "staff"}
              </Text>
            </Table.Td>
            <Table.Td>{c.policy_version}</Table.Td>
            <Table.Td>{formatDate(c.captured_at)}</Table.Td>
            <Table.Td c="dimmed" fz="xs">
              {formatDateTime(c.recorded_at)}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function ConsentsTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [recording, setRecording] = useState(false);
  const [historyType, setHistoryType] = useState<string | null>(null);
  const path = { params: { path: { patient_id: patient.id } } };
  const current = useQuery({
    queryKey: ["patient", patient.id, "consents"],
    queryFn: () => unwrap(api.GET("/api/v1/patients/{patient_id}/consents", path)),
  });
  const history = useQuery({
    queryKey: ["patient", patient.id, "consents", "history", historyType],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/patients/{patient_id}/consents/history", {
          params: { path: { patient_id: patient.id }, query: { consent_type: (historyType as ConsentType) ?? undefined } },
        }),
      ),
  });

  return (
    <Stack>
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Title order={5}>Current consent</Title>
          {can("consents:write") && (
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setRecording(true)}>
              Record consent
            </Button>
          )}
        </Group>
        <QueryState loading={current.isPending} error={current.error}>
          {current.data?.length ? <ConsentRows rows={current.data} /> : <EmptyState>No consent recorded yet.</EmptyState>}
        </QueryState>
      </Card>
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Stack gap={0}>
            <Title order={5}>Full history</Title>
            <Text size="xs" c="dimmed">
              Every change is kept as evidence. Nothing is overwritten.
            </Text>
          </Stack>
          <Select size="xs" placeholder="All types" clearable data={options(CONSENT_TYPES)} value={historyType} onChange={setHistoryType} w={220} />
        </Group>
        <QueryState loading={history.isPending} error={history.error}>
          {history.data?.length ? <ConsentRows rows={history.data} /> : <EmptyState>No history.</EmptyState>}
        </QueryState>
      </Card>
      <RecordConsentModal patientId={patient.id} opened={recording} onClose={() => setRecording(false)} />
    </Stack>
  );
}

interface Values {
  consent_type: string;
  status: string;
  source: string;
  policy_version: string;
  captured: string | null;
  expires: string | null;
  note: string;
}

function RecordConsentModal({ patientId, opened, onClose }: { patientId: string; opened: boolean; onClose: () => void }) {
  const form = useForm<Values>({
    initialValues: { consent_type: "DATA_PROCESSING", status: "GRANTED", source: "STAFF_VERBAL", policy_version: "", captured: null, expires: null, note: "" },
    validate: { policy_version: (v) => (/^[A-Za-z0-9._-]{1,40}$/.test(v) ? null : "e.g. privacy-2026.1 (letters, numbers, . _ -)") },
  });
  const save = useApiMutation({
    mutationFn: (v: Values) =>
      unwrap(
        api.POST("/api/v1/patients/{patient_id}/consents", {
          params: { path: { patient_id: patientId } },
          body: {
            consent_type: v.consent_type as ConsentType,
            status: v.status as Consent["status"],
            source: v.source as "STAFF_VERBAL" | "PAPER_FORM" | "ELECTRONIC_FORM" | "IMPORT",
            policy_version: v.policy_version,
            captured_at: v.captured ? toApiDateTime(v.captured) : null,
            expires_at: v.expires ? toApiDateTime(v.expires) : null,
            note: v.note.trim() || null,
          },
        }),
      ),
    invalidate: [["patient", patientId]],
    success: "Consent recorded",
    onSuccess: () => {
      form.reset();
      onClose();
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Record consent" size="lg">
      <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Consent" data={options(CONSENT_TYPES)} {...form.getInputProps("consent_type")} />
            <Select label="Decision" data={options(CONSENT_STATUSES)} {...form.getInputProps("status")} />
            <Select label="How it was given" data={options(CONSENT_SOURCES)} {...form.getInputProps("source")} />
            <TextInput label="Policy / wording version" placeholder="privacy-2026.1" required {...form.getInputProps("policy_version")} />
            <DateTimePicker label="When the patient gave it" placeholder="Now" clearable maxDate={new Date()} {...form.getInputProps("captured")} />
            <DateTimePicker label="Expires" placeholder="Never" clearable {...form.getInputProps("expires")} />
          </SimpleGrid>
          <Textarea label="Note" maxLength={500} {...form.getInputProps("note")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Record
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
