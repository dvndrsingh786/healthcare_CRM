import { ActionIcon, Anchor, Button, Group, Menu, Modal, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { useForm } from "@mantine/form";
import { IconCheck, IconDots, IconPencil, IconPlayerPlay, IconRotate, IconX } from "@tabler/icons-react";
import { useEffect } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { Task, TaskPriority } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PatientPicker, StaffSelect } from "@/components/pickers";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { TASK_PRIORITIES } from "@/utils/constants";
import { formatDateTime, options, toApiDateTime, toPickerValue } from "@/utils/format";

const OPEN = ["OPEN", "IN_PROGRESS"];
const INVALIDATE = [["tasks"], ["summary"]];

interface Values {
  title: string;
  description: string;
  owner_user_id: string | null;
  patient_id: string | null;
  priority: string;
  due: string | null;
}

/** Create a task (optionally for a given patient), or edit one. */
export function TaskFormModal({ opened, onClose, task, patient }: {
  opened: boolean;
  onClose: () => void;
  task?: Task | null;
  patient?: { id: string; name: string };
}) {
  const { me } = useAuth();
  const blank = (): Values => ({
    title: task?.title ?? "",
    description: task?.description ?? "",
    owner_user_id: task?.owner_user_id ?? me?.id ?? null,
    patient_id: task?.patient_id ?? patient?.id ?? null,
    priority: task?.priority ?? "NORMAL",
    due: toPickerValue(task?.due_at),
  });
  const form = useForm<Values>({
    initialValues: blank(),
    validate: { title: (v) => (v.trim() ? null : "Required"), owner_user_id: (v) => (v ? null : "Choose who does it") },
  });
  useEffect(() => {
    if (opened) form.setValues(blank());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, task]);

  const save = useApiMutation({
    mutationFn: (v: Values) => {
      const due = v.due ? toApiDateTime(v.due) : null;
      if (task) {
        return unwrap(
          api.PATCH("/api/v1/tasks/{task_id}", {
            params: { path: { task_id: task.id } },
            body: {
              version: task.version,
              title: v.title.trim(),
              description: v.description.trim() || null,
              owner_user_id: v.owner_user_id!,
              priority: v.priority as TaskPriority,
              due_at: due,
            },
          }),
        );
      }
      return unwrap(
        api.POST("/api/v1/tasks", {
          body: {
            title: v.title.trim(),
            description: v.description.trim() || null,
            owner_user_id: v.owner_user_id,
            patient_id: v.patient_id,
            priority: v.priority as TaskPriority,
            due_at: due,
          },
        }),
      );
    },
    invalidate: INVALIDATE,
    success: task ? "Task updated" : "Task created",
    onSuccess: onClose,
    onError: (error) => {
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        form.setErrors({ title: "Someone changed this task after you opened it. Close and reopen it." });
        return true;
      }
      return false;
    },
  });

  return (
    <Modal opened={opened} onClose={onClose} title={task ? "Edit task" : "New task"} size="lg">
      <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
        <Stack>
          <TextInput label="What needs doing" required maxLength={200} {...form.getInputProps("title")} />
          <Textarea label="Details" maxLength={4000} autosize minRows={2} {...form.getInputProps("description")} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <StaffSelect label="Owner" required {...form.getInputProps("owner_user_id")} />
            <Select label="Priority" data={options(TASK_PRIORITIES)} {...form.getInputProps("priority")} />
            <DateTimePicker label="Due" clearable valueFormat="ddd D MMM YYYY, HH:mm" {...form.getInputProps("due")} />
            {!task &&
              (patient ? (
                <TextInput label="Patient" value={patient.name} readOnly />
              ) : (
                <PatientPicker label="Patient" placeholder="Optional" {...form.getInputProps("patient_id")} />
              ))}
          </SimpleGrid>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {task ? "Save" : "Create task"}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function useTaskAction(name: "complete" | "reopen" | "cancel", message: string) {
  return useApiMutation({
    mutationFn: (taskId: string) => {
      const path = { params: { path: { task_id: taskId } } };
      if (name === "complete") return unwrap(api.POST("/api/v1/tasks/{task_id}/complete", path));
      if (name === "reopen") return unwrap(api.POST("/api/v1/tasks/{task_id}/reopen", path));
      return unwrap(api.POST("/api/v1/tasks/{task_id}/cancel", path));
    },
    invalidate: INVALIDATE,
    success: message,
  });
}

/** A table of tasks with the lifecycle actions the caller may take. */
export function TaskTable({ tasks, showPatient = true, onEdit }: { tasks: Task[]; showPatient?: boolean; onEdit: (task: Task) => void }) {
  const { me, can } = useAuth();
  const complete = useTaskAction("complete", "Task completed");
  const reopen = useTaskAction("reopen", "Task reopened");
  const cancel = useTaskAction("cancel", "Task cancelled");
  const start = useApiMutation({
    mutationFn: (task: Task) =>
      unwrap(api.PATCH("/api/v1/tasks/{task_id}", { params: { path: { task_id: task.id } }, body: { version: task.version, status: "IN_PROGRESS" } })),
    invalidate: INVALIDATE,
    success: "Task started",
  });
  // Mirrors the API rule: owner, creator or someone with tasks:read_all may change a task.
  const mayChange = (t: Task) => can("tasks:write") && (can("tasks:read_all") || t.owner_user_id === me?.id || t.created_by === me?.id);

  return (
    <Table highlightOnHover verticalSpacing="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Task</Table.Th>
          <Table.Th>Owner</Table.Th>
          <Table.Th>Due</Table.Th>
          <Table.Th>Priority</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {tasks.map((t) => (
          <Table.Tr key={t.id}>
            <Table.Td>
              <Text size="sm" fw={500}>
                {t.title}
              </Text>
              {t.description && (
                <Text size="xs" c="dimmed" lineClamp={1}>
                  {t.description}
                </Text>
              )}
              {showPatient && t.patient_id && (
                <Anchor component={Link} to={`/patients/${t.patient_id}?tab=tasks`} size="xs">
                  Open patient
                </Anchor>
              )}
            </Table.Td>
            <Table.Td>{t.owner_display_name ?? "—"}</Table.Td>
            <Table.Td>
              <Text size="sm" c={t.is_overdue ? "red" : undefined} fw={t.is_overdue ? 600 : undefined}>
                {t.due_at ? formatDateTime(t.due_at) : "—"}
              </Text>
              {t.is_overdue && (
                <Text size="xs" c="red">
                  Overdue
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              <StatusBadge value={t.priority} />
            </Table.Td>
            <Table.Td>
              <StatusBadge value={t.status} />
              {t.status === "DONE" && (
                <Text size="xs" c="dimmed">
                  {formatDateTime(t.completed_at)}
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              {mayChange(t) && (
                <Group gap={4} justify="flex-end" wrap="nowrap">
                  {OPEN.includes(t.status) && (
                    <ActionIcon variant="light" color="green" aria-label="Complete" onClick={() => complete.mutate(t.id)}>
                      <IconCheck size={16} />
                    </ActionIcon>
                  )}
                  <Menu position="bottom-end">
                    <Menu.Target>
                      <ActionIcon variant="subtle" aria-label="More">
                        <IconDots size={16} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      {t.status === "OPEN" && (
                        <Menu.Item leftSection={<IconPlayerPlay size={14} />} onClick={() => start.mutate(t)}>
                          Start working on it
                        </Menu.Item>
                      )}
                      {OPEN.includes(t.status) && (
                        <>
                          <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => onEdit(t)}>
                            Edit
                          </Menu.Item>
                          <Menu.Item leftSection={<IconX size={14} />} color="red" onClick={() => cancel.mutate(t.id)}>
                            Cancel task
                          </Menu.Item>
                        </>
                      )}
                      {!OPEN.includes(t.status) && (
                        <Menu.Item leftSection={<IconRotate size={14} />} onClick={() => reopen.mutate(t.id)}>
                          Reopen
                        </Menu.Item>
                      )}
                    </Menu.Dropdown>
                  </Menu>
                </Group>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
