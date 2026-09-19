import { Badge, type MantineColor } from "@mantine/core";

import { humanize } from "@/utils/format";

const COLORS: Record<string, MantineColor> = {
  ACTIVE: "green", INACTIVE: "gray", ARCHIVED: "gray",
  SCHEDULED: "blue", CONFIRMED: "teal", COMPLETED: "green", NO_SHOW: "orange", CANCELLED: "gray",
  OPEN: "blue", IN_PROGRESS: "indigo", DONE: "green",
  LOW: "gray", NORMAL: "blue", HIGH: "orange", URGENT: "red",
  INTERNAL: "blue", CLINICAL: "red", APP_VISIBLE: "grape",
  GRANTED: "green", WITHDRAWN: "orange", REFUSED: "red", EXPIRED: "gray",
  AVAILABLE: "green", PENDING_UPLOAD: "yellow", REJECTED: "red",
  QUEUED: "blue", SENDING: "indigo", SENT: "green", FAILED: "red", SKIPPED: "gray",
  SUCCESS: "green", FAILURE: "orange", DENIED: "red",
  ENTERED_IN_ERROR: "gray",
};

export function StatusBadge({ value, size = "sm" }: { value?: string | null; size?: "xs" | "sm" | "md" }) {
  if (!value) return null;
  return (
    <Badge color={COLORS[value] ?? "gray"} variant="light" size={size} radius="sm">
      {humanize(value)}
    </Badge>
  );
}
