import { Alert, Badge, Button, Card, Code, CopyButton, Group, Menu, Modal, NumberInput, Stack, Table, Text, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { IconAlertTriangle, IconDots, IconKey, IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { formatDateTime, fromNow } from "@/utils/format";

/** Machine accounts (e.g. the notification worker) with scoped, expiring API keys. */
export function ServiceAccountsPage() {
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<{ name: string; key: string; expires: string } | null>(null);
  const accounts = useQuery({
    queryKey: ["users", "service-accounts"],
    queryFn: () => unwrap(api.GET("/api/v1/users", { params: { query: { user_type: "SERVICE", page_size: 100 } } })),
  });
  const rotate = useApiMutation({
    mutationFn: ({ id }: { id: string; name: string }) =>
      unwrap(api.POST("/api/v1/service-accounts/{user_id}/rotate-key", { params: { path: { user_id: id } }, body: { expires_in_days: 90 } })),
    invalidate: [["users"]],
    onSuccess: (key, v) => setNewKey({ name: v.name, key: key.api_key, expires: key.expires_at }),
  });
  const revoke = useApiMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/service-accounts/{user_id}/keys", { params: { path: { user_id: id } } })),
    invalidate: [["users"]],
    success: "All keys revoked. The account can no longer call the API.",
  });

  return (
    <>
      <PageHeader
        title="Service accounts"
        description="Machine-to-machine access with narrow roles, expiring keys and their own audit identity."
        actions={
          can("roles:manage") && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              New service account
            </Button>
          )
        }
      />
      <Card withBorder p={0}>
        <QueryState loading={accounts.isPending} error={accounts.error}>
          {accounts.data?.data.length ? (
            <Table verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Name</Table.Th>
                  <Table.Th>Roles</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {accounts.data.data.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {a.profile.display_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {a.email}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {a.roles.map((r) => (
                        <Badge key={r} size="sm" variant="light">
                          {r}
                        </Badge>
                      ))}
                    </Table.Td>
                    <Table.Td>
                      <StatusBadge value={a.status} />
                    </Table.Td>
                    <Table.Td fz="sm" c="dimmed">
                      {fromNow(a.created_at)}
                    </Table.Td>
                    <Table.Td>
                      <Menu position="bottom-end">
                        <Menu.Target>
                          <Button variant="subtle" size="compact-sm" px={4} aria-label="Actions">
                            <IconDots size={16} />
                          </Button>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item leftSection={<IconKey size={14} />} onClick={() => rotate.mutate({ id: a.id, name: a.profile.display_name ?? a.email })}>
                            Issue a new key (old one stops)
                          </Menu.Item>
                          <Menu.Item
                            color="red"
                            onClick={() =>
                              modals.openConfirmModal({
                                title: "Revoke all keys?",
                                children: <Text size="sm">Anything using this account stops working immediately.</Text>,
                                labels: { confirm: "Revoke", cancel: "Keep" },
                                confirmProps: { color: "red" },
                                onConfirm: () => revoke.mutate(a.id),
                              })
                            }
                          >
                            Revoke all keys
                          </Menu.Item>
                        </Menu.Dropdown>
                      </Menu>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <EmptyState>No service accounts.</EmptyState>
          )}
        </QueryState>
      </Card>
      <CreateModal opened={creating} onClose={() => setCreating(false)} onCreated={setNewKey} />
      <Modal opened={!!newKey} onClose={() => setNewKey(null)} title="API key" size="lg">
        {newKey && (
          <Stack>
            <Alert color="orange" icon={<IconAlertTriangle size={18} />}>
              Copy this key now. It is shown only once and cannot be retrieved later.
            </Alert>
            <Text size="sm">
              Key for <b>{newKey.name}</b>, valid until {formatDateTime(newKey.expires)}. Send it as the <Code>X-API-Key</Code> header.
            </Text>
            <Code block>{newKey.key}</Code>
            <Group justify="flex-end">
              <CopyButton value={newKey.key}>
                {({ copied, copy }) => (
                  <Button color={copied ? "green" : "teal"} onClick={copy}>
                    {copied ? "Copied" : "Copy key"}
                  </Button>
                )}
              </CopyButton>
              <Button variant="default" onClick={() => setNewKey(null)}>
                Done
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}

function CreateModal({ opened, onClose, onCreated }: {
  opened: boolean;
  onClose: () => void;
  onCreated: (key: { name: string; key: string; expires: string }) => void;
}) {
  const form = useForm({
    initialValues: { name: "", expires_in_days: 90 },
    validate: { name: (v) => (/^[a-z0-9-]{3,40}$/.test(v) ? null : "3–40 lowercase letters, digits or dashes") },
  });
  const create = useApiMutation({
    mutationFn: (v: { name: string; expires_in_days: number }) =>
      unwrap(api.POST("/api/v1/service-accounts", { body: { name: v.name, role_keys: ["NOTIFICATION_WORKER"], expires_in_days: v.expires_in_days } })),
    invalidate: [["users"]],
    onSuccess: (result) => {
      form.reset();
      onClose();
      onCreated({ name: result.user.profile.display_name ?? result.user.email, key: result.key.api_key, expires: result.key.expires_at });
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New service account">
      <form onSubmit={form.onSubmit((v) => create.mutate(v))}>
        <Stack>
          <TextInput label="Name" placeholder="outbox-worker" required {...form.getInputProps("name")} />
          <Text size="sm">
            Role: <Badge variant="light">NOTIFICATION_WORKER</Badge> (can only send queued notifications)
          </Text>
          <NumberInput label="Key valid for (days)" min={1} max={365} {...form.getInputProps("expires_in_days")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
