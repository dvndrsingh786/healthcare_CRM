import { Alert, Badge, Button, Card, Group, Menu, Modal, Pagination, Paper, Select, SimpleGrid, Stack, Switch, Text, Textarea, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconDots, IconHistory, IconLock, IconPencil, IconPlus, IconX } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { Note, NoteType, Patient, Visibility } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { ReasonModal } from "@/components/ReasonModal";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { NOTE_TYPES } from "@/utils/constants";
import { formatDateTime, humanize, options } from "@/utils/format";

const VISIBILITY_HELP: Record<string, string> = {
  INTERNAL: "Staff who may read notes",
  CLINICAL: "Restricted: care staff only. Never shown to support staff or the patient.",
  APP_VISIBLE: "Staff, and the patient in their app (they are notified)",
};

export function NotesTab({ patient }: { patient: Patient }) {
  const { me, can } = useAuth();
  const [visibility, setVisibility] = useState<string | null>(null);
  const [showRetracted, setShowRetracted] = useState(false);
  const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<{ open: boolean; note: Note | null }>({ open: false, note: null });
  const [retracting, setRetracting] = useState<Note | null>(null);
  const [historyOf, setHistoryOf] = useState<Note | null>(null);

  const notes = useQuery({
    queryKey: ["patient", patient.id, "notes", visibility, showRetracted, page],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/patients/{patient_id}/notes", {
          params: {
            path: { patient_id: patient.id },
            query: { visibility: (visibility as Visibility) ?? undefined, include_retracted: showRetracted, page, page_size: 20 },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const retract = useApiMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      unwrap(api.POST("/api/v1/notes/{note_id}/retract", { params: { path: { note_id: id } }, body: { reason } })),
    invalidate: [["patient", patient.id]],
    success: "Note marked as entered in error",
    onSuccess: () => setRetracting(null),
  });
  const visibilityOptions = ["INTERNAL", "APP_VISIBLE", ...(can("notes:read_clinical") ? ["CLINICAL"] : [])];

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={5}>Notes and interactions</Title>
        <Group>
          <Select
            size="xs"
            placeholder="All I may see"
            clearable
            data={visibilityOptions.map((v) => ({ value: v, label: humanize(v) }))}
            value={visibility}
            onChange={(v) => {
              setVisibility(v);
              setPage(1);
            }}
            w={170}
          />
          <Switch size="xs" label="Show retracted" checked={showRetracted} onChange={(e) => setShowRetracted(e.currentTarget.checked)} />
          {can("notes:write") && patient.status !== "ARCHIVED" && (
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setEditor({ open: true, note: null })}>
              Add note
            </Button>
          )}
        </Group>
      </Group>
      {!can("notes:read_clinical") && (
        <Text size="xs" c="dimmed" mb="sm">
          <IconLock size={12} /> Clinical notes are restricted to care staff and are not shown to you.
        </Text>
      )}
      <QueryState loading={notes.isPending} error={notes.error}>
        {notes.data?.data.length ? (
          <Stack>
            {notes.data.data.map((n) => {
              const mine = n.author_user_id === me?.id;
              const retracted = n.status !== "ACTIVE";
              return (
                <Paper key={n.id} withBorder p="md" opacity={retracted ? 0.6 : 1}>
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Group gap="xs">
                        <Text fw={600} td={retracted ? "line-through" : undefined}>
                          {n.subject}
                        </Text>
                        <StatusBadge value={n.visibility} size="xs" />
                        <Badge size="xs" variant="outline" color="gray">
                          {humanize(n.note_type)}
                        </Badge>
                        {n.edited && (
                          <Badge size="xs" variant="outline" color="gray">
                            edited
                          </Badge>
                        )}
                        {retracted && <StatusBadge value={n.status} size="xs" />}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {formatDateTime(n.occurred_at)} · {n.author_display_name ?? "Unknown"}
                      </Text>
                    </Stack>
                    <Menu position="bottom-end">
                      <Menu.Target>
                        <Button variant="subtle" size="compact-sm" px={4} aria-label="Note actions">
                          <IconDots size={16} />
                        </Button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        {n.edited && (
                          <Menu.Item leftSection={<IconHistory size={14} />} onClick={() => setHistoryOf(n)}>
                            Earlier versions
                          </Menu.Item>
                        )}
                        {mine && !retracted && can("notes:write") && (
                          <>
                            <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => setEditor({ open: true, note: n })}>
                              Edit
                            </Menu.Item>
                            <Menu.Item leftSection={<IconX size={14} />} color="red" onClick={() => setRetracting(n)}>
                              Mark as entered in error
                            </Menu.Item>
                          </>
                        )}
                        {!n.edited && !(mine && !retracted) && <Menu.Item disabled>No actions</Menu.Item>}
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                  <Text size="sm" mt="xs" style={{ whiteSpace: "pre-wrap" }}>
                    {n.body}
                  </Text>
                  {retracted && n.retracted_reason && (
                    <Text size="xs" c="dimmed" mt="xs">
                      Retracted: {n.retracted_reason}
                    </Text>
                  )}
                </Paper>
              );
            })}
            {notes.data.meta.total_pages > 1 && <Pagination total={notes.data.meta.total_pages} value={page} onChange={setPage} />}
          </Stack>
        ) : (
          <EmptyState>No notes you can see.</EmptyState>
        )}
      </QueryState>
      <NoteEditor
        patientId={patient.id}
        opened={editor.open}
        note={editor.note}
        visibilityOptions={visibilityOptions}
        onClose={() => setEditor({ open: false, note: null })}
      />
      <ReasonModal
        opened={!!retracting}
        title="Mark note as entered in error"
        label="Why? (the note is kept on record)"
        confirmLabel="Mark as entered in error"
        loading={retract.isPending}
        onClose={() => setRetracting(null)}
        onConfirm={(reason) => retracting && retract.mutate({ id: retracting.id, reason })}
      />
      <RevisionsModal note={historyOf} onClose={() => setHistoryOf(null)} />
    </Card>
  );
}

interface Values {
  note_type: string;
  subject: string;
  body: string;
  visibility: string;
  reason: string;
}

function NoteEditor({ patientId, opened, note, visibilityOptions, onClose }: {
  patientId: string;
  opened: boolean;
  note: Note | null;
  visibilityOptions: string[];
  onClose: () => void;
}) {
  const form = useForm<Values>({
    initialValues: { note_type: "NOTE", subject: "", body: "", visibility: "INTERNAL", reason: "" },
    validate: { subject: (v) => (v.trim() ? null : "Required"), body: (v) => (v.trim() ? null : "Required") },
  });
  useEffect(() => {
    if (opened) {
      form.setValues(
        note
          ? { note_type: note.note_type, subject: note.subject, body: note.body, visibility: note.visibility, reason: "" }
          : { note_type: "NOTE", subject: "", body: "", visibility: "INTERNAL", reason: "" },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, note]);

  const [conflict, setConflict] = useState(false);
  const save = useApiMutation({
    mutationFn: (v: Values) =>
      note
        ? unwrap(
            api.PATCH("/api/v1/notes/{note_id}", {
              params: { path: { note_id: note.id } },
              body: {
                version: note.version,
                note_type: v.note_type as NoteType,
                subject: v.subject.trim(),
                body: v.body.trim(),
                visibility: v.visibility as Visibility,
                reason: v.reason.trim() || null,
              },
            }),
          )
        : unwrap(
            api.POST("/api/v1/patients/{patient_id}/notes", {
              params: { path: { patient_id: patientId } },
              body: {
                note_type: v.note_type as NoteType,
                subject: v.subject.trim(),
                body: v.body.trim(),
                visibility: v.visibility as Visibility,
              },
            }),
          ),
    invalidate: [["patient", patientId]],
    success: note ? "Note updated (the previous text is kept)" : "Note added",
    onSuccess: () => {
      setConflict(false);
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        setConflict(true);
        return true;
      }
      return false;
    },
  });

  return (
    <Modal opened={opened} onClose={onClose} title={note ? "Edit note" : "Add note"} size="lg">
      <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
        <Stack>
          {conflict && <Alert color="orange">This note was changed since you opened it. Close and reopen it.</Alert>}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Type" data={options(NOTE_TYPES)} {...form.getInputProps("note_type")} />
            <Select
              label="Who can see it"
              data={visibilityOptions.map((v) => ({ value: v, label: humanize(v) }))}
              description={VISIBILITY_HELP[form.values.visibility]}
              {...form.getInputProps("visibility")}
            />
          </SimpleGrid>
          <TextInput label="Subject" required maxLength={200} {...form.getInputProps("subject")} />
          <Textarea label="Note" required autosize minRows={4} maxLength={20000} {...form.getInputProps("body")} />
          {note && <TextInput label="Reason for the change" placeholder="Optional, kept with the old version" {...form.getInputProps("reason")} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function RevisionsModal({ note, onClose }: { note: Note | null; onClose: () => void }) {
  const revisions = useQuery({
    queryKey: ["note", note?.id, "revisions"],
    queryFn: () => unwrap(api.GET("/api/v1/notes/{note_id}/revisions", { params: { path: { note_id: note!.id } } })),
    enabled: !!note,
  });
  return (
    <Modal opened={!!note} onClose={onClose} title="Earlier versions" size="lg">
      <QueryState loading={revisions.isPending} error={revisions.error}>
        {revisions.data?.length ? (
          <Stack>
            {revisions.data.map((r) => (
              <Paper key={r.version} withBorder p="sm">
                <Group gap="xs">
                  <Text fw={600} size="sm">
                    Version {r.version}: {r.subject}
                  </Text>
                  <StatusBadge value={r.visibility} size="xs" />
                </Group>
                <Text size="xs" c="dimmed">
                  Replaced {formatDateTime(r.edited_at)}
                  {r.edit_reason && ` · reason: ${r.edit_reason}`}
                </Text>
                <Text size="sm" mt={4} style={{ whiteSpace: "pre-wrap" }}>
                  {r.body}
                </Text>
              </Paper>
            ))}
          </Stack>
        ) : (
          <EmptyState>No earlier versions you may see.</EmptyState>
        )}
      </QueryState>
    </Modal>
  );
}
