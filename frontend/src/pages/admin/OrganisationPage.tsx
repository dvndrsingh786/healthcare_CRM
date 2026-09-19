import { Button, Card, Group, NumberInput, Select, SimpleGrid, Stack, Switch, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, unwrap } from "@/api/client";
import { fieldErrors } from "@/api/errors";
import type { Organisation } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { useApiMutation } from "@/components/useApiMutation";
import { timeZoneOptions } from "@/utils/appointments";

interface Values {
  name: string;
  timezone: string;
  patient_records_years: number;
  audit_events_years: number;
  notifications_days: number;
  transactional_ignores_opt_out: boolean;
}

function toValues(org: Organisation): Values {
  const settings = org.settings as {
    retention?: { patient_records_years?: number; audit_events_years?: number; notifications_days?: number };
    notifications?: { transactional_ignores_opt_out?: boolean };
  };
  return {
    name: org.name,
    timezone: org.timezone,
    patient_records_years: settings.retention?.patient_records_years ?? 8,
    audit_events_years: settings.retention?.audit_events_years ?? 8,
    notifications_days: settings.retention?.notifications_days ?? 365,
    transactional_ignores_opt_out: settings.notifications?.transactional_ignores_opt_out ?? true,
  };
}

export function OrganisationPage() {
  const org = useQuery({ queryKey: ["organisation"], queryFn: () => unwrap(api.GET("/api/v1/organisation")) });
  const form = useForm<Values>({
    initialValues: { name: "", timezone: "Europe/London", patient_records_years: 8, audit_events_years: 8, notifications_days: 365, transactional_ignores_opt_out: true },
  });
  useEffect(() => {
    if (org.data) {
      form.setValues(toValues(org.data));
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org.data]);

  const save = useApiMutation({
    mutationFn: (v: Values) =>
      unwrap(
        api.PATCH("/api/v1/organisation", {
          body: {
            name: v.name.trim(),
            timezone: v.timezone,
            settings: {
              retention: {
                patient_records_years: v.patient_records_years,
                audit_events_years: v.audit_events_years,
                notifications_days: v.notifications_days,
              },
              notifications: { transactional_ignores_opt_out: v.transactional_ignores_opt_out },
            },
          },
        }),
      ),
    invalidate: [["organisation"], ["me"]],
    success: "Organisation settings saved",
    onError: (error) => {
      const fields = fieldErrors(error);
      if (Object.keys(fields).length) {
        form.setErrors(fields);
        return true;
      }
      return false;
    },
  });

  return (
    <>
      <PageHeader title="Organisation" description="Settings for your whole organisation. Changes are audited." />
      <QueryState loading={org.isPending} error={org.error}>
        {org.data && (
          <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
            <Stack maw={760}>
              <Card withBorder>
                <Title order={5} mb="sm">
                  General
                </Title>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput label="Name" required {...form.getInputProps("name")} />
                  <Select label="Time zone" searchable data={timeZoneOptions(form.values.timezone)} {...form.getInputProps("timezone")} />
                </SimpleGrid>
                <Text size="xs" c="dimmed" mt="xs">
                  Identifier: {org.data.slug} · data region: {org.data.data_region}
                </Text>
              </Card>
              <Card withBorder>
                <Title order={5}>Retention (placeholders)</Title>
                <Text size="xs" c="dimmed" mb="sm">
                  Recorded for your data policy. The jobs that act on them are on the backlog; nothing is deleted automatically yet.
                </Text>
                <SimpleGrid cols={{ base: 1, sm: 3 }}>
                  <NumberInput label="Patient records (years)" min={1} max={100} {...form.getInputProps("patient_records_years")} />
                  <NumberInput label="Audit log (years)" min={1} max={100} {...form.getInputProps("audit_events_years")} />
                  <NumberInput label="Messages (days)" min={30} max={3650} {...form.getInputProps("notifications_days")} />
                </SimpleGrid>
              </Card>
              <Card withBorder>
                <Title order={5} mb="sm">
                  Messages
                </Title>
                <Switch
                  label="Send messages about a patient's own care even if they opted out of that channel"
                  description="E.g. an appointment change by SMS for a patient who turned SMS off. Marketing messages always respect opt-outs."
                  {...form.getInputProps("transactional_ignores_opt_out", { type: "checkbox" })}
                />
              </Card>
              <Group justify="flex-end">
                <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
                  Save settings
                </Button>
              </Group>
            </Stack>
          </form>
        )}
      </QueryState>
    </>
  );
}
