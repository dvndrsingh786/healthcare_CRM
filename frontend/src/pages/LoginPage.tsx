import { Alert, Anchor, Button, Center, Collapse, Paper, PasswordInput, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDisclosure } from "@mantine/hooks";
import { IconAlertTriangle, IconBuildingHospital } from "@tabler/icons-react";
import { useState } from "react";
import { Navigate, useLocation } from "react-router";

import { ApiError, describeError } from "@/api/errors";
import { useAuth } from "@/auth/AuthContext";
import { homePath } from "@/components/navigation";

// Demo accounts created by seed.py. Only shown in development builds.
const DEMO_USERS = [
  ["ops@northfield.example", "Operations Admin"],
  ["nurse@northfield.example", "Care Staff"],
  ["coordinator@northfield.example", "Coordinator"],
  ["admin@northfield.example", "System Admin"],
  ["ops@southbank.example", "Other organisation"],
];

export function LoginPage() {
  const { me, login } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoOpen, { toggle: toggleDemo }] = useDisclosure(false);
  const form = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: (v) => (/^\S+@\S+$/.test(v) ? null : "Enter your email address"),
      password: (v) => (v ? null : "Enter your password"),
    },
  });

  if (me) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from !== "/login" ? from : homePath(me)} replace />;
  }

  const submit = form.onSubmit(async ({ email, password }) => {
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
    } catch (e) {
      if (e instanceof ApiError && e.code === "RATE_LIMITED") {
        setError("Too many attempts. Please wait a minute and try again.");
      } else if (e instanceof ApiError || e instanceof TypeError) {
        setError(describeError(e));
      } else {
        setError(e instanceof Error ? e.message : "Login failed.");
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center mih="100vh" bg="gray.0" p="md">
      <Paper withBorder shadow="sm" radius="md" p="xl" w={400}>
        <form onSubmit={submit}>
          <Stack>
            <Stack gap={4} align="center">
              <IconBuildingHospital size={40} color="var(--mantine-color-teal-6)" />
              <Title order={3}>Healthcare CRM</Title>
              <Text c="dimmed" size="sm">
                Staff sign in
              </Text>
            </Stack>
            {error && (
              <Alert color="red" icon={<IconAlertTriangle size={18} />}>
                {error}
              </Alert>
            )}
            <TextInput label="Email" autoComplete="username" data-autofocus {...form.getInputProps("email")} />
            <PasswordInput label="Password" autoComplete="current-password" {...form.getInputProps("password")} />
            <Button type="submit" loading={submitting} fullWidth>
              Sign in
            </Button>
            {import.meta.env.DEV && (
              <>
                <Anchor component="button" type="button" size="xs" c="dimmed" onClick={toggleDemo}>
                  Demo accounts (development only)
                </Anchor>
                <Collapse expanded={demoOpen}>
                  <Table fz="xs" withRowBorders={false}>
                    <Table.Tbody>
                      {DEMO_USERS.map(([email, role]) => (
                        <Table.Tr
                          key={email}
                          style={{ cursor: "pointer" }}
                          onClick={() => form.setValues({ email, password: "DemoPass123!" })}
                        >
                          <Table.Td>{email}</Table.Td>
                          <Table.Td c="dimmed">{role}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                  <Text size="xs" c="dimmed">
                    Click one to fill in the form. Password: DemoPass123!
                  </Text>
                </Collapse>
              </>
            )}
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
