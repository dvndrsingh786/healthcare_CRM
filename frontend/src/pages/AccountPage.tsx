import { Badge, Button, Card, Group, PasswordInput, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";

import { api, unwrap } from "@/api/client";
import { fieldErrors } from "@/api/errors";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { useApiMutation } from "@/components/useApiMutation";
import { formatDateTime } from "@/utils/format";

export function AccountPage() {
  const { me, logout } = useAuth();
  const form = useForm({
    initialValues: { current_password: "", new_password: "", confirm: "" },
    validate: {
      new_password: (v) =>
        v.length < 10 || !/[a-zA-Z]/.test(v) || !/\d/.test(v) ? "At least 10 characters, with a letter and a number" : null,
      confirm: (v, values) => (v === values.new_password ? null : "The passwords do not match"),
    },
  });
  const change = useApiMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      unwrap(api.POST("/api/v1/auth/change-password", { body })),
    onSuccess: () => {
      form.reset();
      notifications.show({ color: "green", message: "Password changed. Your other sessions were signed out." });
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
  if (!me) return null;

  return (
    <>
      <PageHeader title="My account" />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Title order={4} mb="sm">
            Profile
          </Title>
          <Stack gap="xs">
            <Text>
              <b>{me.display_name}</b> ({me.email})
            </Text>
            <Text size="sm">Organisation: {me.organisation.name}</Text>
            <Group gap="xs">
              {me.roles.map((r) => (
                <Badge key={r} variant="light">
                  {r}
                </Badge>
              ))}
            </Group>
            <Text size="sm" c="dimmed">
              Last sign-in: {formatDateTime(me.last_login_at)}
            </Text>
            <Text size="sm" fw={500} mt="sm">
              Your permissions
            </Text>
            <Group gap={4}>
              {me.permissions.map((p) => (
                <Badge key={p} size="xs" variant="outline" color="gray">
                  {p}
                </Badge>
              ))}
            </Group>
          </Stack>
        </Card>
        <Stack>
          <Card withBorder>
            <Title order={4} mb="sm">
              Change password
            </Title>
            <form onSubmit={form.onSubmit(({ current_password, new_password }) => change.mutate({ current_password, new_password }))}>
              <Stack>
                <PasswordInput label="Current password" autoComplete="current-password" {...form.getInputProps("current_password")} />
                <PasswordInput label="New password" autoComplete="new-password" {...form.getInputProps("new_password")} />
                <PasswordInput label="Repeat new password" autoComplete="new-password" {...form.getInputProps("confirm")} />
                <Button type="submit" loading={change.isPending}>
                  Change password
                </Button>
              </Stack>
            </form>
          </Card>
          <Card withBorder>
            <Title order={4} mb="xs">
              Sessions
            </Title>
            <Text size="sm" c="dimmed" mb="sm">
              Lost a device? Sign out of every browser and device at once.
            </Text>
            <Button variant="light" color="red" onClick={() => logout(true)}>
              Sign out everywhere
            </Button>
          </Card>
        </Stack>
      </SimpleGrid>
    </>
  );
}
