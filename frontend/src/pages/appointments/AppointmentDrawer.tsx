import { Alert, Anchor, Badge, Button, Divider, Drawer, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput, Timeline } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import { useDisclosure } from "@mantine/hooks";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { Appointment } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { QueryState } from "@/components/QueryState";
import { ReasonModal } from "@/components/ReasonModal";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { dayjs, formatDateTime, formatInZone, humanize, toApiDateTime, toPickerValue } from "@/utils/format";

import { DURATIONS } from "@/utils/appointments";

const LIVE = ["SCHEDULED", "CONFIRMED"];

/** Appointment details, lifecycle actions and history, in a side panel. */
export function AppointmentDrawer({ appointmentId, onClose }: { appointmentId: string | null; onClose: () => void }) {
  const { can } = useAuth();
  const [cancelling, { open: openCancel, close: closeCancel }] = useDisclosure(false);
  const [rescheduling, { open: openReschedule, close: closeReschedule }] = useDisclosure(false);
  const path = { params: { path: { appointment_id: appointmentId ?? "" } } };

  const appointment = useQuery({
    queryKey: ["appointments", "detail", appointmentId],
    queryFn: () => unwrap(api.GET("/api/v1/appointments/{appointment_id}", path)),
    enabled: !!appointmentId,
  });
  const history = useQuery({
    queryKey: ["appointments", "history", appointmentId],
    queryFn: () => unwrap(api.GET("/api/v1/appointments/{appointment_id}/history", path)),
    enabled: !!appointmentId,
  });
  const invalidate = [["appointments"], ["summary"], ["notifications"]];
  const confirm = useApiMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/appointments/{appointment_id}/confirm", path)),
    invalidate,
    success: "Appointment confirmed",
  });
  const complete = useApiMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/appointments/{appointment_id}/complete", path)),
    invalidate,
    success: "Marked as completed",
  });
  const noShow = useApiMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/appointments/{appointment_id}/no-show", path)),
    invalidate,
    success: "Marked as no-show",
  });
  const cancel = useApiMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/appointments/{appointment_id}/cancel", { ...path, body: { reason } })),
    invalidate,
    success: "Appointment cancelled. The patient is notified.",
    onSuccess: closeCancel,
  });

  const a = appointment.data;
  const live = !!a && LIVE.includes(a.status);
  const started = !!a && dayjs(a.starts_at).isBefore(dayjs());

  return (
    <Drawer opened={!!appointmentId} onClose={onClose} position="right" size="lg" title="Appointment">
      <QueryState loading={appointment.isPending} error={appointment.error}>
        {a && (
          <Stack>
            <Group justify="space-between">
              <Stack gap={0}>
                <Text fw={600} size="lg">
                  {humanize(a.appointment_type)} · {humanize(a.mode)}
                </Text>
                <Anchor component={Link} to={`/patients/${a.patient_id}?tab=appointments`} size="sm" onClick={onClose}>
                  {a.patient_name}
                </Anchor>
              </Stack>
              <StatusBadge value={a.status} size="md" />
            </Group>
            <SimpleGrid cols={2}>
              <div>
                <Text size="xs" c="dimmed">
                  When ({a.timezone})
                </Text>
                <Text size="sm">
                  {formatInZone(a.starts_at, a.timezone)} – {dayjs(a.ends_at).tz(a.timezone).format("HH:mm")}
                </Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  With
                </Text>
                <Text size="sm">{[a.staff_display_name, a.team_name].filter(Boolean).join(" · ") || "—"}</Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  Location
                </Text>
                <Text size="sm">{a.location ?? "—"}</Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  Patient app
                </Text>
                <Badge variant="light" color={a.app_visible ? "grape" : "gray"}>
                  {a.app_visible ? "Visible to patient" : "CRM only"}
                </Badge>
              </div>
            </SimpleGrid>
            {a.patient_instructions && (
              <Alert variant="light" color="blue" title="Instructions for the patient">
                {a.patient_instructions}
              </Alert>
            )}
            {a.internal_note && (
              <Alert variant="light" color="gray" title="Internal note (staff only)">
                {a.internal_note}
              </Alert>
            )}
            {a.status === "CANCELLED" && (
              <Alert variant="light" color="gray" title="Cancelled">
                {a.cancellation_reason} ({formatDateTime(a.cancelled_at)})
              </Alert>
            )}

            {live && (
              <Group>
                {can("appointments:write") && a.status === "SCHEDULED" && (
                  <Button size="xs" variant="light" loading={confirm.isPending} onClick={() => confirm.mutate()}>
                    Confirm
                  </Button>
                )}
                {can("appointments:write") && (
                  <Button size="xs" variant="light" onClick={openReschedule}>
                    Reschedule
                  </Button>
                )}
                {can("appointments:update_outcome") && (
                  <>
                    <Button size="xs" variant="light" color="green" disabled={!started} loading={complete.isPending} onClick={() => complete.mutate()}>
                      Completed
                    </Button>
                    <Button size="xs" variant="light" color="orange" disabled={!started} loading={noShow.isPending} onClick={() => noShow.mutate()}>
                      No-show
                    </Button>
                  </>
                )}
                {can("appointments:write") && (
                  <Button size="xs" variant="light" color="red" onClick={openCancel}>
                    Cancel
                  </Button>
                )}
              </Group>
            )}
            {live && !started && can("appointments:update_outcome") && (
              <Text size="xs" c="dimmed">
                The outcome (completed / no-show) can be recorded once the appointment has started.
              </Text>
            )}

            <Divider label="History" labelPosition="left" />
            <QueryState loading={history.isPending} error={history.error}>
              <Timeline bulletSize={14} lineWidth={2}>
                {(history.data ?? []).map((h, i) => (
                  <Timeline.Item key={i} title={humanize(h.event)}>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(h.occurred_at)}
                      {h.from_status && h.from_status !== h.to_status && ` · ${humanize(h.from_status)} → ${humanize(h.to_status)}`}
                    </Text>
                    {h.old_starts_at && h.new_starts_at && (
                      <Text size="xs">
                        {dayjs(h.old_starts_at).isSame(dayjs(h.new_starts_at))
                          ? "Same start time; length or time zone changed"
                          : `${formatInZone(h.old_starts_at, a.timezone)} → ${formatInZone(h.new_starts_at, a.timezone)}`}
                      </Text>
                    )}
                    {h.reason && <Text size="xs">Reason: {h.reason}</Text>}
                  </Timeline.Item>
                ))}
              </Timeline>
            </QueryState>
          </Stack>
        )}
      </QueryState>
      {a && <RescheduleModal appointment={a} opened={rescheduling} onClose={closeReschedule} />}
      <ReasonModal
        opened={cancelling}
        title="Cancel appointment"
        label="Reason (kept in the history)"
        confirmLabel="Cancel appointment"
        loading={cancel.isPending}
        onClose={closeCancel}
        onConfirm={(reason) => cancel.mutate(reason)}
      />
    </Drawer>
  );
}

function RescheduleModal({ appointment, opened, onClose }: { appointment: Appointment; opened: boolean; onClose: () => void }) {
  // Mantine unmounts modal content when closed, so the form starts fresh on every open.
  return (
    <Modal opened={opened} onClose={onClose} title="Reschedule">
      <RescheduleForm appointment={appointment} onClose={onClose} />
    </Modal>
  );
}

function RescheduleForm({ appointment, onClose }: { appointment: Appointment; onClose: () => void }) {
  const zone = appointment.timezone;
  const minutes = dayjs(appointment.ends_at).diff(dayjs(appointment.starts_at), "minute");
  const [start, setStart] = useState<string | null>(() => toPickerValue(appointment.starts_at, zone));
  const [duration, setDuration] = useState(() => (DURATIONS.some((d) => d.value === String(minutes)) ? String(minutes) : "45"));
  const [reason, setReason] = useState("");
  const [conflict, setConflict] = useState(false);

  const save = useApiMutation({
    mutationFn: () => {
      const startsAt = toApiDateTime(start!, zone);
      return unwrap(
        api.POST("/api/v1/appointments/{appointment_id}/reschedule", {
          params: { path: { appointment_id: appointment.id } },
          body: {
            version: appointment.version,
            starts_at: startsAt,
            ends_at: dayjs(startsAt).add(Number(duration), "minute").tz(zone).format(),
            reason: reason.trim() || null,
          },
        }),
      );
    },
    invalidate: [["appointments"], ["summary"], ["notifications"]],
    success: "Rescheduled. The patient is notified.",
    onSuccess: onClose,
    onError: (error) => {
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        setConflict(true);
        return true;
      }
      return false;
    },
  });

  return (
    <Stack>
      {conflict && (
          <Alert color="orange" icon={<IconAlertTriangle size={18} />}>
            Someone changed this appointment after you opened it. Close and reopen it to see the latest version.
          </Alert>
        )}
        <DateTimePicker label={`New start (${zone})`} valueFormat="ddd D MMM YYYY, HH:mm" minDate={new Date()} value={start} onChange={setStart} />
        <Select label="Length" data={DURATIONS} value={duration} onChange={(v) => setDuration(v ?? "45")} />
        <TextInput label="Reason" placeholder="Optional, kept in the history" value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Back
          </Button>
          <Button loading={save.isPending} disabled={!start || conflict} onClick={() => save.mutate()}>
            Reschedule
          </Button>
        </Group>
    </Stack>
  );
}
