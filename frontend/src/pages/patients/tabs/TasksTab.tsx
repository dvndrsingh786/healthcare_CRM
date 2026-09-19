import { Button, Card, Group, Switch, Title } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Patient, Task } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { TaskFormModal, TaskTable } from "@/pages/tasks/TaskComponents";
import { patientName } from "@/utils/format";

export function TasksTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [openOnly, setOpenOnly] = useState(true);
  const [form, setForm] = useState<{ open: boolean; task: Task | null }>({ open: false, task: null });
  const tasks = useQuery({
    queryKey: ["tasks", "patient", patient.id, openOnly],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/tasks", {
          params: { query: { patient_id: patient.id, status: openOnly ? "open" : undefined, sort: "due_at", page_size: 100 } },
        }),
      ),
  });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={5}>Follow-up tasks</Title>
        <Group>
          <Switch label="Open only" checked={openOnly} onChange={(e) => setOpenOnly(e.currentTarget.checked)} />
          {can("tasks:write") && (
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setForm({ open: true, task: null })}>
              New task
            </Button>
          )}
        </Group>
      </Group>
      <QueryState loading={tasks.isPending} error={tasks.error}>
        {tasks.data?.data.length ? (
          <TaskTable tasks={tasks.data.data} showPatient={false} onEdit={(task) => setForm({ open: true, task })} />
        ) : (
          <EmptyState>{openOnly ? "No open tasks for this patient." : "No tasks for this patient."}</EmptyState>
        )}
      </QueryState>
      <TaskFormModal
        opened={form.open}
        task={form.task}
        onClose={() => setForm({ open: false, task: null })}
        patient={{ id: patient.id, name: patientName(patient) }}
      />
    </Card>
  );
}
