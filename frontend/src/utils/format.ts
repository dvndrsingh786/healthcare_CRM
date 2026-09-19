import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(relativeTime);

export { dayjs };

/** "19 Sep 2026, 14:05" in the browser's time zone. */
export function formatDateTime(value?: string | null) {
  return value ? dayjs(value).format("D MMM YYYY, HH:mm") : "—";
}

export function formatDate(value?: string | null) {
  return value ? dayjs(value).format("D MMM YYYY") : "—";
}

/** A time in a given IANA zone, e.g. an appointment shown in its own zone. */
export function formatInZone(value: string, zone: string) {
  return dayjs(value).tz(zone).format("ddd D MMM YYYY, HH:mm");
}

export function fromNow(value?: string | null) {
  return value ? dayjs(value).fromNow() : "—";
}

/**
 * Mantine date pickers give wall-clock strings ("2027-03-22 10:00:00") without a zone.
 * The API needs an explicit offset: interpret the wall-clock time in `zone`
 * (the appointment's zone) or, without one, in the browser's zone.
 */
export function toApiDateTime(value: string, zone?: string) {
  return (zone ? dayjs.tz(value, zone) : dayjs(value)).format();
}

/** The reverse: an API instant as a wall-clock string for a picker, in `zone` if given. */
export function toPickerValue(value?: string | null, zone?: string) {
  if (!value) return null;
  return (zone ? dayjs(value).tz(zone) : dayjs(value)).format("YYYY-MM-DD HH:mm:ss");
}

/** "HOME_VISIT" -> "Home visit" */
export function humanize(value?: string | null) {
  if (!value) return "—";
  const text = value.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function patientName(p: { preferred_name?: string | null; legal_first_name: string; legal_last_name: string }) {
  const first = p.preferred_name ? `${p.legal_first_name} "${p.preferred_name}"` : p.legal_first_name;
  return `${first} ${p.legal_last_name}`;
}

export function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function options(values: readonly string[]) {
  return values.map((value) => ({ value, label: humanize(value) }));
}
