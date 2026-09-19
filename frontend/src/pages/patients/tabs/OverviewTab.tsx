import { ActionIcon, Badge, Button, Card, Checkbox, Group, Modal, NumberInput, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDisclosure } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { fieldErrors } from "@/api/errors";
import type { EmergencyContact, Patient } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { useApiMutation } from "@/components/useApiMutation";
import { formatDate, formatDateTime } from "@/utils/format";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{children || "—"}</Text>
    </div>
  );
}

export function OverviewTab({ patient }: { patient: Patient }) {
  const hidden = patient.sensitive_fields_hidden;
  const address = [patient.address_line1, patient.address_line2, patient.city, patient.postcode, patient.country]
    .filter(Boolean)
    .join(", ");
  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <Stack>
        <Card withBorder>
          <Title order={5} mb="sm">
            Details
          </Title>
          <SimpleGrid cols={2}>
            <Field label="Legal name">{`${patient.legal_first_name} ${patient.legal_last_name}`}</Field>
            <Field label="Preferred name">{patient.preferred_name}</Field>
            <Field label="Date of birth">{hidden ? "Hidden for your role" : formatDate(patient.date_of_birth)}</Field>
            <Field label="MRN">{hidden ? "Hidden for your role" : patient.mrn}</Field>
            <Field label="Phone">{patient.phone}</Field>
            <Field label="Email">{patient.email}</Field>
            <Field label="Address">{hidden ? "Hidden for your role" : address}</Field>
            <Field label="Language">{patient.preferred_language}</Field>
          </SimpleGrid>
        </Card>
        <Card withBorder>
          <Title order={5} mb="sm">
            Contact preferences
          </Title>
          <Group>
            {(["email", "sms", "push"] as const).map((channel) => (
              <Badge key={channel} variant="light" color={patient[`contact_by_${channel}`] ? "green" : "gray"}>
                {channel === "push" ? "App" : channel.toUpperCase()}: {patient[`contact_by_${channel}`] ? "yes" : "no"}
              </Badge>
            ))}
          </Group>
          <Text size="xs" c="dimmed" mt="sm">
            Record created {formatDateTime(patient.created_at)}, last changed {formatDateTime(patient.updated_at)} (version {patient.version}).
          </Text>
        </Card>
      </Stack>
      <EmergencyContacts patient={patient} />
    </SimpleGrid>
  );
}

interface ContactValues {
  name: string;
  relationship: string;
  phone: string;
  email: string;
  priority: number;
  is_next_of_kin: boolean;
}

function EmergencyContacts({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState<EmergencyContact | null>(null);
  const [opened, { open, close }] = useDisclosure(false);
  const path = { params: { path: { patient_id: patient.id } } };
  const contacts = useQuery({
    queryKey: ["patient", patient.id, "contacts"],
    queryFn: () => unwrap(api.GET("/api/v1/patients/{patient_id}/emergency-contacts", path)),
  });
  const form = useForm<ContactValues>({
    initialValues: { name: "", relationship: "", phone: "", email: "", priority: 1, is_next_of_kin: false },
    validate: {
      name: (v) => (v.trim() ? null : "Required"),
      relationship: (v) => (v.trim() ? null : "Required"),
      phone: (v, values) => (v.trim() || values.email.trim() ? null : "Give a phone number or an email"),
    },
  });
  const onError = (error: unknown) => {
    const fields = fieldErrors(error);
    if (Object.keys(fields).length) {
      form.setErrors(fields);
      return true;
    }
    return false;
  };
  const toBody = (v: ContactValues) => ({
    name: v.name.trim(),
    relationship: v.relationship.trim(),
    phone: v.phone.trim() || null,
    email: v.email.trim() || null,
    priority: v.priority,
    is_next_of_kin: v.is_next_of_kin,
  });
  const invalidate = [["patient", patient.id, "contacts"]];
  const save = useApiMutation({
    mutationFn: (v: ContactValues) =>
      editing
        ? unwrap(
            api.PATCH("/api/v1/patients/{patient_id}/emergency-contacts/{contact_id}", {
              params: { path: { patient_id: patient.id, contact_id: editing.id } },
              body: toBody(v),
            }),
          )
        : unwrap(api.POST("/api/v1/patients/{patient_id}/emergency-contacts", { ...path, body: toBody(v) })),
    invalidate,
    success: "Emergency contact saved",
    onSuccess: close,
    onError,
  });
  const remove = useApiMutation({
    mutationFn: (contactId: string) =>
      unwrap(
        api.DELETE("/api/v1/patients/{patient_id}/emergency-contacts/{contact_id}", {
          params: { path: { patient_id: patient.id, contact_id: contactId } },
        }),
      ),
    invalidate,
    success: "Emergency contact removed",
  });

  const startEdit = (contact: EmergencyContact | null) => {
    setEditing(contact);
    form.setValues(
      contact
        ? { name: contact.name, relationship: contact.relationship, phone: contact.phone ?? "", email: contact.email ?? "", priority: contact.priority, is_next_of_kin: contact.is_next_of_kin }
        : { name: "", relationship: "", phone: "", email: "", priority: (contacts.data?.length ?? 0) + 1, is_next_of_kin: false },
    );
    form.clearErrors();
    open();
  };
  const writable = can("patients:write") && patient.status !== "ARCHIVED";

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={5}>Emergency contacts</Title>
        {writable && (
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => startEdit(null)}>
            Add
          </Button>
        )}
      </Group>
      <QueryState loading={contacts.isPending} error={contacts.error}>
        {contacts.data?.length ? (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>#</Table.Th>
                <Table.Th>Name</Table.Th>
                <Table.Th>Contact</Table.Th>
                {writable && <Table.Th />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {contacts.data.map((c) => (
                <Table.Tr key={c.id}>
                  <Table.Td>{c.priority}</Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {c.name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {c.relationship}
                      {c.is_next_of_kin && " · next of kin"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{c.phone}</Text>
                    <Text size="xs" c="dimmed">
                      {c.email}
                    </Text>
                  </Table.Td>
                  {writable && (
                    <Table.Td>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <ActionIcon variant="subtle" aria-label="Edit" onClick={() => startEdit(c)}>
                          <IconPencil size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label="Remove"
                          onClick={() =>
                            modals.openConfirmModal({
                              title: "Remove emergency contact?",
                              children: <Text size="sm">{c.name} will be removed from this patient.</Text>,
                              labels: { confirm: "Remove", cancel: "Keep" },
                              confirmProps: { color: "red" },
                              onConfirm: () => remove.mutate(c.id),
                            })
                          }
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <EmptyState>No emergency contacts recorded.</EmptyState>
        )}
      </QueryState>
      <Modal opened={opened} onClose={close} title={editing ? "Edit emergency contact" : "Add emergency contact"}>
        <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
          <Stack>
            <TextInput label="Name" required {...form.getInputProps("name")} />
            <TextInput label="Relationship" placeholder="Son, neighbour..." required {...form.getInputProps("relationship")} />
            <TextInput label="Phone" {...form.getInputProps("phone")} />
            <TextInput label="Email" {...form.getInputProps("email")} />
            <NumberInput label="Call order (1 = first)" min={1} max={9} {...form.getInputProps("priority")} />
            <Checkbox label="Next of kin" {...form.getInputProps("is_next_of_kin", { type: "checkbox" })} />
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" loading={save.isPending}>
                Save
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </Card>
  );
}
