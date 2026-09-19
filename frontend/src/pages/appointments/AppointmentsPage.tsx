import type { DatesSetArg, EventClickArg } from "@fullcalendar/core";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin, { type DateClickArg } from "@fullcalendar/interaction";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import { Alert, Button, Card, Group, SegmentedControl, Select, Table, Text } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import type { Appointment } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { StaffSelect } from "@/components/pickers";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { APPOINTMENT_STATUSES } from "@/utils/constants";
import { dayjs, formatInZone, humanize, options } from "@/utils/format";

import { AppointmentDrawer } from "./AppointmentDrawer";
import { AppointmentFormModal } from "./AppointmentFormModal";

const EVENT_COLORS: Record<string, string> = {
  SCHEDULED: "#228be6",
  CONFIRMED: "#12b886",
  COMPLETED: "#40c057",
  NO_SHOW: "#fd7e14",
  CANCELLED: "#adb5bd",
};
const MAX_PER_VIEW = 100; // the API's maximum page size

export function AppointmentsPage() {
  const { can, me } = useAuth();
  const [view, setView] = useState("calendar");
  const [range, setRange] = useState(() => ({
    from: dayjs().startOf("week").toISOString(),
    to: dayjs().startOf("week").add(7, "day").toISOString(),
  }));
  const [staffId, setStaffId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [booking, setBooking] = useState<{ open: boolean; start: string | null }>({ open: false, start: null });

  // Whole days, so the query key stays the same between renders (no refetch loop).
  const today = dayjs().startOf("day");
  const listRange = { from: today.toISOString(), to: today.add(31, "day").toISOString() };
  const period = view === "calendar" ? range : listRange;
  const appointments = useQuery({
    queryKey: ["appointments", "range", period.from, period.to, staffId, status],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/appointments", {
          params: {
            query: {
              from: period.from,
              to: period.to,
              staff_user_id: staffId ?? undefined,
              status: (status as Appointment["status"]) ?? undefined,
              sort: "starts_at",
              page_size: MAX_PER_VIEW,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const rows = appointments.data?.data ?? [];

  const events = rows.map((a) => ({
    id: a.id,
    title: `${a.patient_name} · ${humanize(a.appointment_type)}${a.staff_display_name ? ` (${a.staff_display_name})` : ""}`,
    start: a.starts_at,
    end: a.ends_at,
    backgroundColor: EVENT_COLORS[a.status],
    borderColor: EVENT_COLORS[a.status],
    classNames: a.status === "CANCELLED" ? ["appointment-cancelled"] : [],
  }));

  return (
    <>
      <PageHeader
        title="Appointments"
        description={can("patients:read_all") ? "All appointments in your organisation." : "Appointments of your patients and those booked with you."}
        actions={
          can("appointments:write") && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setBooking({ open: true, start: null })}>
              Book appointment
            </Button>
          )
        }
      />
      <Card withBorder mb="md">
        <Group justify="space-between">
          <Group>
            <StaffSelect placeholder="All staff" value={staffId} onChange={setStaffId} w={240} />
            <Select placeholder="Any status" data={options(APPOINTMENT_STATUSES)} value={status} onChange={setStatus} clearable w={180} />
            {me && (
              <Button variant="subtle" size="xs" onClick={() => setStaffId(me.id)}>
                Only mine
              </Button>
            )}
          </Group>
          <SegmentedControl
            value={view}
            onChange={setView}
            data={[
              { value: "calendar", label: "Calendar" },
              { value: "list", label: "Next 30 days" },
            ]}
          />
        </Group>
      </Card>
      {appointments.data && appointments.data.meta.total > MAX_PER_VIEW && (
        <Alert color="yellow" mb="md">
          Showing the first {MAX_PER_VIEW} of {appointments.data.meta.total}. Filter by staff or status to see the rest.
        </Alert>
      )}
      {view === "calendar" ? (
        <Card withBorder>
          <FullCalendar
            plugins={[timeGridPlugin, dayGridPlugin, interactionPlugin]}
            initialView="timeGridWeek"
            headerToolbar={{ left: "prev,next today", center: "title", right: "timeGridDay,timeGridWeek,dayGridMonth" }}
            firstDay={1}
            slotMinTime="07:00:00"
            slotMaxTime="21:00:00"
            allDaySlot={false}
            nowIndicator
            height="auto"
            events={events}
            eventClick={(arg: EventClickArg) => setSelected(arg.event.id)}
            dateClick={(arg: DateClickArg) => {
              if (can("appointments:write") && dayjs(arg.date).isAfter(dayjs())) {
                // The booking form works in the organisation's time zone.
                const zone = me?.organisation.timezone ?? "Europe/London";
                setBooking({ open: true, start: dayjs(arg.date).tz(zone).format("YYYY-MM-DD HH:mm:ss") });
              }
            }}
            datesSet={(arg: DatesSetArg) => setRange({ from: arg.start.toISOString(), to: arg.end.toISOString() })}
          />
          <Text size="xs" c="dimmed" mt="xs">
            Times in your browser's time zone. Click an appointment for details; click an empty future slot to book.
          </Text>
        </Card>
      ) : (
        <Card withBorder p={0}>
          <QueryState loading={appointments.isPending} error={appointments.error}>
            {rows.length ? (
              <Table highlightOnHover verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>When</Table.Th>
                    <Table.Th>Patient</Table.Th>
                    <Table.Th>Type</Table.Th>
                    <Table.Th>With</Table.Th>
                    <Table.Th>Status</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((a) => (
                    <Table.Tr key={a.id} style={{ cursor: "pointer" }} onClick={() => setSelected(a.id)}>
                      <Table.Td>{formatInZone(a.starts_at, a.timezone)}</Table.Td>
                      <Table.Td fw={500}>{a.patient_name}</Table.Td>
                      <Table.Td>
                        {humanize(a.appointment_type)}
                        <Text size="xs" c="dimmed">
                          {humanize(a.mode)}
                        </Text>
                      </Table.Td>
                      <Table.Td>{[a.staff_display_name, a.team_name].filter(Boolean).join(" · ") || "—"}</Table.Td>
                      <Table.Td>
                        <StatusBadge value={a.status} />
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : (
              <EmptyState>No appointments in the next 30 days.</EmptyState>
            )}
          </QueryState>
        </Card>
      )}
      <AppointmentDrawer appointmentId={selected} onClose={() => setSelected(null)} />
      <AppointmentFormModal
        opened={booking.open}
        start={booking.start}
        onClose={() => setBooking({ open: false, start: null })}
        onSaved={(a) => setSelected(a.id)}
      />
    </>
  );
}
