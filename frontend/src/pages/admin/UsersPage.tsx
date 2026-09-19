import { Alert, Badge, Button, Card, Divider, Drawer, Group, Modal, MultiSelect, Pagination, PasswordInput, Select, SimpleGrid, Stack, Table, Text, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDebouncedValue } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { IconPlus, IconSearch, IconX } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { fieldErrors } from "@/api/errors";
import type { User } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { staffName } from "@/components/staff";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { PAGE_SIZE, STAFF_ROLES } from "@/utils/constants";
import { formatDateTime, fromNow } from "@/utils/format";

export function UsersPage() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [status, setStatus] = useState<string | null>("ACTIVE");
  const [role, setRole] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  // Search text goes in a POST body, never the URL.
  const users = useQuery({
    queryKey: ["users", "list", debounced, status, role, page],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/users/search", {
          body: {
            search: debounced || null,
            user_type: "STAFF",
            status: status as "ACTIVE" | "INACTIVE" | null,
            role,
            sort: "display_name",
            page,
            page_size: PAGE_SIZE,
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Users and roles"
        description="Staff accounts of your organisation. Patients' app accounts are managed from the patient record."
        actions={
          can("users:manage") &&
          can("roles:manage") && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              New staff user
            </Button>
          )
        }
      />
      <Card withBorder mb="md">
        <Group>
          <TextInput
            placeholder="Search name or email"
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(e) => {
              setSearch(e.currentTarget.value);
              setPage(1);
            }}
            style={{ flex: 1 }}
          />
          <Select
            placeholder="Any status"
            data={[
              { value: "ACTIVE", label: "Active" },
              { value: "INACTIVE", label: "Deactivated" },
            ]}
            value={status}
            onChange={(v) => {
              setStatus(v);
              setPage(1);
            }}
            clearable
            w={160}
          />
          <Select placeholder="Any role" data={[...STAFF_ROLES]} value={role} onChange={(v) => { setRole(v); setPage(1); }} clearable w={180} />
        </Group>
      </Card>
      <Card withBorder p={0}>
        <QueryState loading={users.isPending} error={users.error}>
          {users.data?.data.length ? (
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Name</Table.Th>
                  <Table.Th>Roles</Table.Th>
                  <Table.Th>Teams</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Last sign-in</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {users.data.data.map((u) => (
                  <Table.Tr key={u.id} style={{ cursor: "pointer" }} onClick={() => setSelected(u.id)}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {staffName(u)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {u.email}
                        {u.profile.job_title && ` · ${u.profile.job_title}`}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {u.roles.map((r) => (
                          <Badge key={r} size="sm" variant="light">
                            {r}
                          </Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td fz="sm">{u.teams.map((t) => t.name).join(", ") || "—"}</Table.Td>
                    <Table.Td>
                      <StatusBadge value={u.status} />
                    </Table.Td>
                    <Table.Td c="dimmed" fz="sm">
                      {u.last_login_at ? fromNow(u.last_login_at) : "Never"}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <EmptyState>No users match.</EmptyState>
          )}
        </QueryState>
      </Card>
      {users.data && users.data.meta.total_pages > 1 && (
        <Group justify="flex-end" mt="md">
          <Pagination total={users.data.meta.total_pages} value={page} onChange={setPage} />
        </Group>
      )}
      <CreateUserModal opened={creating} onClose={() => setCreating(false)} onCreated={setSelected} />
      <UserDrawer userId={selected} onClose={() => setSelected(null)} />
    </>
  );
}

interface CreateValues {
  email: string;
  display_name: string;
  job_title: string;
  phone: string;
  role_keys: string[];
  password: string;
}

function CreateUserModal({ opened, onClose, onCreated }: { opened: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { me } = useAuth();
  const form = useForm<CreateValues>({
    initialValues: { email: "", display_name: "", job_title: "", phone: "", role_keys: ["CARE_STAFF"], password: "" },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : "Not a valid email"),
      display_name: (v) => (v.trim() ? null : "Required"),
      role_keys: (v) => (v.length ? null : "Choose at least one role"),
      password: (v) => (!v || (v.length >= 10 && /[a-zA-Z]/.test(v) && /\d/.test(v)) ? null : "At least 10 characters with a letter and a number"),
    },
  });
  const create = useApiMutation({
    mutationFn: (v: CreateValues) =>
      unwrap(
        api.POST("/api/v1/users", {
          body: {
            email: v.email.trim(),
            display_name: v.display_name.trim(),
            job_title: v.job_title.trim() || null,
            phone: v.phone.trim() || null,
            role_keys: v.role_keys,
            password: v.password || null,
          },
        }),
      ),
    invalidate: [["users"]],
    success: (u) => (form.values.password ? `${u.email} can sign in now` : `Invitation emailed to ${u.email}`),
    onSuccess: (u) => {
      form.reset();
      onClose();
      onCreated(u.id);
    },
    onError: (error) => {
      const fields = fieldErrors(error);
      if (Object.keys(fields).length) {
        form.setErrors(fields);
        return true;
      }
      return false;
    },
  });
  const isAdmin = me?.roles.includes("SYSTEM_ADMIN");
  return (
    <Modal opened={opened} onClose={onClose} title="New staff user" size="lg">
      <form onSubmit={form.onSubmit((v) => create.mutate(v))}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Email" required {...form.getInputProps("email")} />
            <TextInput label="Display name" required {...form.getInputProps("display_name")} />
            <TextInput label="Job title" {...form.getInputProps("job_title")} />
            <TextInput label="Phone" {...form.getInputProps("phone")} />
          </SimpleGrid>
          <MultiSelect
            label="Roles"
            data={STAFF_ROLES.filter((r) => r !== "SYSTEM_ADMIN" || isAdmin).map((r) => ({ value: r, label: r }))}
            {...form.getInputProps("role_keys")}
          />
          <PasswordInput
            label="Initial password"
            description="Leave empty to email the user a one-time code to set their own password."
            autoComplete="new-password"
            {...form.getInputProps("password")}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create user
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function UserDrawer({ userId, onClose }: { userId: string | null; onClose: () => void }) {
  const { me, can } = useAuth();
  const [newRole, setNewRole] = useState<string | null>(null);
  const path = { params: { path: { user_id: userId ?? "" } } };
  const user = useQuery({
    queryKey: ["users", "detail", userId],
    queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}", path)),
    enabled: !!userId,
  });
  const permissions = useQuery({
    queryKey: ["users", "permissions", userId],
    queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}/permissions", path)),
    enabled: !!userId,
  });
  const profile = useForm({ initialValues: { display_name: "", job_title: "", phone: "" } });
  useEffect(() => {
    if (user.data) {
      profile.setValues({
        display_name: user.data.profile.display_name ?? "",
        job_title: user.data.profile.job_title ?? "",
        phone: user.data.profile.phone ?? "",
      });
      profile.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.data]);

  const invalidate = [["users"]];
  const saveProfile = useApiMutation({
    mutationFn: (v: { display_name: string; job_title: string; phone: string }) =>
      unwrap(
        api.PATCH("/api/v1/users/{user_id}", {
          ...path,
          body: { display_name: v.display_name.trim(), job_title: v.job_title.trim() || null, phone: v.phone.trim() || null },
        }),
      ),
    invalidate,
    success: "Profile saved",
  });
  const setActive = useApiMutation({
    mutationFn: (active: boolean) =>
      unwrap(active ? api.POST("/api/v1/users/{user_id}/activate", path) : api.POST("/api/v1/users/{user_id}/deactivate", path)),
    invalidate,
    success: (u: User) => (u.status === "ACTIVE" ? "User re-activated" : "User deactivated: signed out everywhere"),
  });
  const grant = useApiMutation({
    mutationFn: (role: string) => unwrap(api.POST("/api/v1/users/{user_id}/roles", { ...path, body: { role_key: role } })),
    invalidate,
    success: "Role granted",
    onSuccess: () => setNewRole(null),
  });
  const revoke = useApiMutation({
    mutationFn: (role: string) =>
      unwrap(api.DELETE("/api/v1/users/{user_id}/roles/{role_key}", { params: { path: { user_id: userId!, role_key: role } } })),
    invalidate,
    success: "Role removed",
  });

  const u = user.data;
  const self = u?.id === me?.id;
  return (
    <Drawer opened={!!userId} onClose={onClose} position="right" size="lg" title="Staff user">
      <QueryState loading={user.isPending} error={user.error}>
        {u && (
          <Stack>
            <Group justify="space-between">
              <Stack gap={0}>
                <Text fw={600} size="lg">
                  {staffName(u)}
                </Text>
                <Text size="sm" c="dimmed">
                  {u.email}
                </Text>
              </Stack>
              <StatusBadge value={u.status} size="md" />
            </Group>
            <Text size="xs" c="dimmed">
              Created {formatDateTime(u.created_at)} · last sign-in {u.last_login_at ? formatDateTime(u.last_login_at) : "never"}
            </Text>

            <Divider label="Profile" labelPosition="left" />
            <form onSubmit={profile.onSubmit((v) => saveProfile.mutate(v))}>
              <Stack gap="xs">
                <TextInput label="Display name" disabled={!can("users:manage")} {...profile.getInputProps("display_name")} />
                <SimpleGrid cols={2}>
                  <TextInput label="Job title" disabled={!can("users:manage")} {...profile.getInputProps("job_title")} />
                  <TextInput label="Phone" disabled={!can("users:manage")} {...profile.getInputProps("phone")} />
                </SimpleGrid>
                {can("users:manage") && (
                  <Group justify="flex-end">
                    <Button size="xs" type="submit" disabled={!profile.isDirty()} loading={saveProfile.isPending}>
                      Save profile
                    </Button>
                  </Group>
                )}
              </Stack>
            </form>

            <Divider label="Roles" labelPosition="left" />
            <Group gap="xs">
              {u.roles.map((r) => (
                <Badge
                  key={r}
                  size="lg"
                  variant="light"
                  rightSection={
                    can("roles:manage") && !self ? (
                      <IconX size={12} style={{ cursor: "pointer" }} onClick={() => revoke.mutate(r)} aria-label={`Remove ${r}`} />
                    ) : null
                  }
                >
                  {r}
                </Badge>
              ))}
            </Group>
            {self && (
              <Text size="xs" c="dimmed">
                You cannot change your own roles.
              </Text>
            )}
            {can("roles:manage") && !self && (
              <Group>
                <Select
                  placeholder="Add a role"
                  data={STAFF_ROLES.filter((r) => !u.roles.includes(r))}
                  value={newRole}
                  onChange={setNewRole}
                  w={220}
                />
                <Button size="xs" disabled={!newRole} loading={grant.isPending} onClick={() => newRole && grant.mutate(newRole)}>
                  Grant
                </Button>
              </Group>
            )}

            <Divider label="Effective permissions" labelPosition="left" />
            <Group gap={4}>
              {(permissions.data?.permissions ?? []).map((p) => (
                <Badge key={p} size="xs" variant="outline" color="gray">
                  {p}
                </Badge>
              ))}
            </Group>

            {can("users:manage") && !self && (
              <>
                <Divider label="Access" labelPosition="left" />
                {u.status === "ACTIVE" ? (
                  <Button
                    color="red"
                    variant="light"
                    onClick={() =>
                      modals.openConfirmModal({
                        title: "Deactivate this user?",
                        children: <Text size="sm">They are signed out everywhere immediately and cannot sign in until re-activated.</Text>,
                        labels: { confirm: "Deactivate", cancel: "Keep active" },
                        confirmProps: { color: "red" },
                        onConfirm: () => setActive.mutate(false),
                      })
                    }
                  >
                    Deactivate user
                  </Button>
                ) : (
                  <Button variant="light" onClick={() => setActive.mutate(true)}>
                    Re-activate user
                  </Button>
                )}
              </>
            )}
            {self && <Alert color="gray">This is your own account.</Alert>}
          </Stack>
        )}
      </QueryState>
    </Drawer>
  );
}
