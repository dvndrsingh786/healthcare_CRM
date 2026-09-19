export const DURATIONS = [15, 30, 45, 60, 90, 120, 180, 240].map((m) => ({
  value: String(m),
  label: m < 60 ? `${m} min` : `${m / 60} h`,
}));

/** IANA time zones for a picker, making sure the current one is included. */
export function timeZoneOptions(current: string) {
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [current];
  return zones.includes(current) ? zones : [current, ...zones];
}
