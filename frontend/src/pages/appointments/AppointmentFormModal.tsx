import { Button, Checkbox, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { useForm } from "@mantine/form";
import { useEffect } from "react";

import { api, unwrap } from "@/api/client";
import { fieldErrors } from "@/api/errors";
import type { Appointment, AppointmentMode, AppointmentType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { PatientPicker, StaffSelect, TeamSelect } from "@/components/pickers";
import { useApiMutation } from "@/components/useApiMutation";
import { DURATIONS, timeZoneOptions } from "@/utils/appointments";
import { APPOINTMENT_MODES, APPOINTMENT_TYPES } from "@/utils/constants";
import { dayjs, options, toApiDateTime } from "@/utils/format";

interface Values {
  patient_id: string | null;
  staff_user_id: string | null;
  team_id: string | null;
  start: string | null;
  duration: string;
  timezone: string;
  appointment_type: string;
  mode: string;
  location: string;
  patient_instructions: string;
  internal_note: string;
  app_visible: boolean;
}

/** Book an appointment. `patient` pre-selects the patient (from the patient's page). */
export function AppointmentFormModal({ opened, onClose, patient, start, onSaved }: {
  opened: boolean;
  onClose: () => void;
  patient?: { id: string; name: string };
  start?: string | null;
  onSaved?: (appointment: Appointment) => void;
}) {
  const { me } = useAuth();
  const zone = me?.organisation.timezone ?? "Europe/London";
  const blank = (): Values => ({
    patient_id: patient?.id ?? null,
    staff_user_id: null,
    team_id: null,
    start: start ?? null,
    duration: "45",
    timezone: zone,
    appointment_type: "HOME_VISIT",
    mode: "IN_PERSON",
    location: "",
    patient_instructions: "",
    internal_note: "",
    app_visible: true,
  });
  const form = useForm<Values>({
    initialValues: blank(),
    validate: {
      patient_id: (v) => (v ? null : "Choose a patient"),
      start: (v, values) =>
        !v ? "Choose a start time" : dayjs.tz(v, values.timezone).isBefore(dayjs()) ? "Choose a time in the future" : null,
    },
  });
  useEffect(() => {
    if (opened) form.setValues(blank());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const save = useApiMutation({
    mutationFn: (v: Values) => {
      const startsAt = toApiDateTime(v.start!, v.timezone);
      const endsAt = dayjs(startsAt).add(Number(v.duration), "minute").tz(v.timezone).format();
      return unwrap(
        api.POST("/api/v1/appointments", {
          body: {
            patient_id: v.patient_id!,
            staff_user_id: v.staff_user_id,
            team_id: v.team_id,
            starts_at: startsAt,
            ends_at: endsAt,
            timezone: v.timezone,
            appointment_type: v.appointment_type as AppointmentType,
            mode: v.mode as AppointmentMode,
            location: v.location.trim() || null,
            patient_instructions: v.patient_instructions.trim() || null,
            internal_note: v.internal_note.trim() || null,
            app_visible: v.app_visible,
          },
        }),
      );
    },
    invalidate: [["appointments"], ["summary"], ["patient"]],
    success: "Appointment booked",
    onSuccess: (a) => {
      onClose();
      onSaved?.(a);
    },
    onError: (error) => {
      const fields = fieldErrors(error);
      if (fields.starts_at) form.setFieldError("start", fields.starts_at);
      return false;
    },
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Book appointment" size="lg">
      <form onSubmit={form.onSubmit((v) => save.mutate(v))}>
        <Stack>
          {patient ? (
            <Text size="sm">
              Patient: <b>{patient.name}</b>
            </Text>
          ) : (
            <PatientPicker label="Patient" placeholder="Type a name" required {...form.getInputProps("patient_id")} />
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <StaffSelect label="Staff member" placeholder="Optional" {...form.getInputProps("staff_user_id")} />
            <TeamSelect label="Team / service" placeholder="Optional" {...form.getInputProps("team_id")} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <DateTimePicker
              label="Starts"
              required
              valueFormat="ddd D MMM YYYY, HH:mm"
              minDate={new Date()}
              {...form.getInputProps("start")}
            />
            <Select label="Length" data={DURATIONS} {...form.getInputProps("duration")} />
            <Select label="Time zone" searchable data={timeZoneOptions(zone)} {...form.getInputProps("timezone")} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Type" data={options(APPOINTMENT_TYPES)} {...form.getInputProps("appointment_type")} />
            <Select label="Mode" data={options(APPOINTMENT_MODES)} {...form.getInputProps("mode")} />
          </SimpleGrid>
          <TextInput label="Location" placeholder="Patient's home, clinic room 3..." {...form.getInputProps("location")} />
          <Textarea label="Instructions for the patient" description="Shown in the patient app" maxLength={1000} {...form.getInputProps("patient_instructions")} />
          <Textarea label="Internal note" description="Staff only. Never shown to the patient." maxLength={2000} {...form.getInputProps("internal_note")} />
          <Checkbox label="Show this appointment in the patient app (and notify the patient)" {...form.getInputProps("app_visible", { type: "checkbox" })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Book
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
