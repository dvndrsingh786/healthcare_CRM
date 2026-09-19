import { Alert, Button, Checkbox, Divider, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { useForm } from "@mantine/form";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError, fieldErrors } from "@/api/errors";
import type { Patient, PatientCreate } from "@/api/types";
import { useApiMutation } from "@/components/useApiMutation";

const LANGUAGES = [
  { value: "en", label: "English" }, { value: "cy", label: "Welsh" }, { value: "pl", label: "Polish" },
  { value: "ur", label: "Urdu" }, { value: "pa", label: "Punjabi" }, { value: "ar", label: "Arabic" },
  { value: "ro", label: "Romanian" }, { value: "es", label: "Spanish" }, { value: "fr", label: "French" },
];

interface Values {
  legal_first_name: string; legal_last_name: string; preferred_name: string; date_of_birth: string | null;
  mrn: string; email: string; phone: string; address_line1: string; address_line2: string; city: string;
  postcode: string; country: string; preferred_language: string;
  contact_by_email: boolean; contact_by_sms: boolean; contact_by_push: boolean; status: string;
}

const TEXT_FIELDS = [
  "legal_first_name", "legal_last_name", "preferred_name", "mrn", "email", "phone",
  "address_line1", "address_line2", "city", "postcode",
] as const;

function initialValues(patient?: Patient): Values {
  return {
    legal_first_name: patient?.legal_first_name ?? "",
    legal_last_name: patient?.legal_last_name ?? "",
    preferred_name: patient?.preferred_name ?? "",
    date_of_birth: patient?.date_of_birth ?? null,
    mrn: patient?.mrn ?? "",
    email: patient?.email ?? "",
    phone: patient?.phone ?? "",
    address_line1: patient?.address_line1 ?? "",
    address_line2: patient?.address_line2 ?? "",
    city: patient?.city ?? "",
    postcode: patient?.postcode ?? "",
    country: patient?.country ?? "GB",
    preferred_language: patient?.preferred_language ?? "en",
    contact_by_email: patient?.contact_by_email ?? true,
    contact_by_sms: patient?.contact_by_sms ?? false,
    contact_by_push: patient?.contact_by_push ?? true,
    status: patient?.status ?? "ACTIVE",
  };
}

/** Create a patient, or edit one (then only the changed fields are sent, with the version read). */
export function PatientFormModal({ opened, onClose, patient, onSaved }: {
  opened: boolean;
  onClose: () => void;
  patient?: Patient;
  onSaved?: (patient: Patient) => void;
}) {
  const editing = !!patient;
  const [duplicate, setDuplicate] = useState(false);
  const [conflict, setConflict] = useState(false);
  const form = useForm<Values>({
    initialValues: initialValues(patient),
    validate: {
      legal_first_name: (v) => (v.trim() ? null : "Required"),
      legal_last_name: (v) => (v.trim() ? null : "Required"),
      date_of_birth: (v) => (v ? null : "Required"),
      email: (v) => (!v || /^\S+@\S+\.\S+$/.test(v) ? null : "Not a valid email address"),
    },
  });

  // Start from the latest data each time the form opens.
  useEffect(() => {
    if (opened) {
      form.setValues(initialValues(patient));
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, patient]);

  const close = () => {
    form.setValues(initialValues(patient));
    form.resetDirty();
    form.clearErrors();
    setDuplicate(false);
    setConflict(false);
    onClose();
  };

  const handleError = (error: unknown) => {
    if (error instanceof ApiError && error.code === "POSSIBLE_DUPLICATE") {
      setDuplicate(true);
      return true;
    }
    if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
      setConflict(true);
      return true;
    }
    if (error instanceof ApiError && error.code === "DUPLICATE_IDENTIFIER") {
      form.setFieldError("mrn", "Another patient already has this MRN.");
      return true;
    }
    const fields = fieldErrors(error);
    if (Object.keys(fields).length) {
      form.setErrors(fields);
    }
    return false;
  };

  const create = useApiMutation({
    mutationFn: (body: PatientCreate) => unwrap(api.POST("/api/v1/patients", { body })),
    invalidate: [["patients"]],
    success: "Patient created",
    onSuccess: (saved) => {
      close();
      onSaved?.(saved);
    },
    onError: handleError,
  });

  const update = useApiMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.PATCH("/api/v1/patients/{patient_id}", { params: { path: { patient_id: patient!.id } }, body: body as never })),
    invalidate: [["patients"], ["patient", patient?.id]],
    success: "Patient updated",
    onSuccess: (saved) => {
      close();
      onSaved?.(saved);
    },
    onError: handleError,
  });

  const toBody = (values: Values) => {
    const body: Record<string, unknown> = { ...values };
    for (const field of TEXT_FIELDS) {
      const value = (values[field] ?? "").trim();
      body[field] = value === "" ? null : value;
    }
    return body;
  };

  const submit = (confirmNotDuplicate = false) =>
    form.onSubmit((values) => {
      const body = toBody(values);
      if (!editing) {
        delete body.status;
        create.mutate({ ...(body as PatientCreate), confirm_not_duplicate: confirmNotDuplicate });
        return;
      }
      // Only what changed, plus the version we read (409 VERSION_CONFLICT if someone else saved first).
      const original = toBody(initialValues(patient));
      const changes = Object.fromEntries(Object.entries(body).filter(([k, v]) => original[k] !== v));
      if (Object.keys(changes).length === 0) {
        close();
        return;
      }
      update.mutate({ ...changes, version: patient!.version });
    });

  const sensitiveHidden = patient?.sensitive_fields_hidden;

  return (
    <Modal opened={opened} onClose={close} title={editing ? "Edit patient" : "New patient"} size="lg">
      <form onSubmit={submit(false)}>
        <Stack>
          {conflict && (
            <Alert color="orange" icon={<IconAlertTriangle size={18} />} title="Changed by someone else">
              Someone updated this patient after you opened it. Close this form and open it again to see their changes.
            </Alert>
          )}
          {duplicate && (
            <Alert color="orange" icon={<IconAlertTriangle size={18} />} title="Possible duplicate">
              <Text size="sm">A patient with the same name and date of birth already exists. Search for them first.</Text>
              <Group mt="sm">
                <Button size="xs" color="orange" onClick={() => submit(true)()} loading={create.isPending}>
                  It is a different person, create anyway
                </Button>
              </Group>
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Legal first name" required {...form.getInputProps("legal_first_name")} />
            <TextInput label="Legal last name" required {...form.getInputProps("legal_last_name")} />
            <TextInput label="Preferred name" {...form.getInputProps("preferred_name")} />
            {!sensitiveHidden && (
              <DateInput
                label="Date of birth"
                required
                placeholder="Type e.g. 5 May 1955, or pick"
                valueFormat="D MMM YYYY"
                maxDate={new Date()}
                defaultLevel="decade"
                {...form.getInputProps("date_of_birth")}
              />
            )}
          </SimpleGrid>
          <Divider label="Contact" labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Email" type="email" {...form.getInputProps("email")} />
            <TextInput label="Phone" placeholder="+44 7700 900123" {...form.getInputProps("phone")} />
          </SimpleGrid>
          {!sensitiveHidden && (
            <>
              <Divider label="Address and identifier (sensitive)" labelPosition="left" />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextInput label="Address line 1" {...form.getInputProps("address_line1")} />
                <TextInput label="Address line 2" {...form.getInputProps("address_line2")} />
                <TextInput label="City" {...form.getInputProps("city")} />
                <TextInput label="Postcode" {...form.getInputProps("postcode")} />
                <TextInput label="Country (2 letters)" maxLength={2} {...form.getInputProps("country")} />
                <TextInput label="MRN / internal reference" description="Optional, unique in your organisation" {...form.getInputProps("mrn")} />
              </SimpleGrid>
            </>
          )}
          <Divider label="Preferences" labelPosition="left" />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Preferred language" data={LANGUAGES} {...form.getInputProps("preferred_language")} />
            {editing && (
              <Select
                label="Status"
                data={[{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }]}
                {...form.getInputProps("status")}
              />
            )}
          </SimpleGrid>
          <Group>
            <Checkbox label="Email" {...form.getInputProps("contact_by_email", { type: "checkbox" })} />
            <Checkbox label="SMS" {...form.getInputProps("contact_by_sms", { type: "checkbox" })} />
            <Checkbox label="App notifications" {...form.getInputProps("contact_by_push", { type: "checkbox" })} />
          </Group>
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending || update.isPending} disabled={conflict}>
              {editing ? "Save changes" : "Create patient"}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
