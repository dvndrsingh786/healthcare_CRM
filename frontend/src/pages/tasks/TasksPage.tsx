import { Button, Card, Group, Pagination, SegmentedControl, Select, Switch, Text } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { api, unwrap } from "@/api/client";
import type { Task, TaskPriority } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { StaffSelect } from "@/components/pickers";
import { QueryState } from "@/components/QueryState";
import { PAGE_SIZE, TASK_PRIORITIES } from "@/utils/constants";
import { options } from "@/utils/format";

import { TaskFormModal, TaskTable } from "./TaskComponents";

type StatusFilter = "open" | "in_progress" | "done" | "cancelled";

export function TasksPage() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [whose, setWhose] = useState(can("tasks:read_all") ? "all" : "mine");
  const [owner, setOwner] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("open");
  const [priority, setPriority] = useState<string | null>(null);
  const [overdue, setOverdue] = useState(params.get("overdue") === "1");
  const [sort, setSort] = useState("due_at");
  const [page, setPage] = useState(1);
  const [form, setForm] = useState<{ open: boolean; task: Task | null }>({ open: false, task: null });

  const ownerFilter = whose === "mine" ? "me" : (owner ?? undefined);
  const tasks = useQuery({
    queryKey: ["tasks", "list", ownerFilter, status, priority, overdue, sort, page],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/tasks", {
          params: {
            query: {
              owner: ownerFilter,
              status: status === "all" ? undefined : (status as StatusFilter),
              priority: (priority as TaskPriority) ?? undefined,
              overdue,
              sort,
              page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const reset = () => setPage(1);

  return (
    <>
      <PageHeader
        title="Tasks"
        description="Follow-ups for patients, appointments and the team."
        actions={
          can("tasks:write") && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setForm({ open: true, task: null })}>
              New task
            </Button>
          )
        }
      />
      <Card withBorder mb="md">
        <Group>
          <SegmentedControl
            value={whose}
            onChange={(v) => {
              setWhose(v);
              reset();
            }}
            data={[
              { value: "mine", label: "My tasks" },
              { value: "all", label: can("tasks:read_all") ? "Everyone's" : "All I can see" },
            ]}
          />
          {whose === "all" && <StaffSelect placeholder="Any owner" value={owner} onChange={(v) => { setOwner(v); reset(); }} w={220} />}
          <Select
            value={status}
            onChange={(v) => {
              setStatus(v ?? "open");
              reset();
            }}
            data={[
              { value: "open", label: "Open (to do)" },
              { value: "in_progress", label: "In progress" },
              { value: "done", label: "Done" },
              { value: "cancelled", label: "Cancelled" },
              { value: "all", label: "Any status" },
            ]}
            w={160}
          />
          <Select placeholder="Any priority" data={options(TASK_PRIORITIES)} value={priority} onChange={(v) => { setPriority(v); reset(); }} clearable w={150} />
          <Select
            value={sort}
            onChange={(v) => setSort(v ?? "due_at")}
            data={[
              { value: "due_at", label: "Due soonest" },
              { value: "-priority", label: "Most urgent" },
              { value: "-created_at", label: "Newest" },
            ]}
            w={150}
          />
          <Switch label="Overdue only" checked={overdue} onChange={(e) => { setOverdue(e.currentTarget.checked); reset(); }} />
        </Group>
      </Card>
      <Card withBorder p={0}>
        <QueryState loading={tasks.isPending} error={tasks.error}>
          {tasks.data?.data.length ? (
            <TaskTable tasks={tasks.data.data} onEdit={(task) => setForm({ open: true, task })} />
          ) : (
            <EmptyState>{overdue ? "Nothing overdue." : "No tasks match these filters."}</EmptyState>
          )}
        </QueryState>
      </Card>
      {tasks.data && tasks.data.meta.total_pages > 1 && (
        <Group justify="space-between" mt="md">
          <Text size="sm" c="dimmed">
            {tasks.data.meta.total} tasks
          </Text>
          <Pagination total={tasks.data.meta.total_pages} value={page} onChange={setPage} />
        </Group>
      )}
      <TaskFormModal opened={form.open} task={form.task} onClose={() => setForm({ open: false, task: null })} />
    </>
  );
}
