// Allowed values, mirroring the API's enums (the API validates them again).
export const APPOINTMENT_TYPES = ["HOME_VISIT", "CLINIC", "ASSESSMENT", "REVIEW", "FOLLOW_UP", "OTHER"] as const;
export const APPOINTMENT_MODES = ["IN_PERSON", "PHONE", "VIDEO"] as const;
export const APPOINTMENT_STATUSES = ["SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"] as const;
export const TASK_PRIORITIES = ["LOW", "NORMAL", "HIGH", "URGENT"] as const;
export const NOTE_TYPES = ["NOTE", "PHONE_CALL", "VISIT", "EMAIL", "SMS", "MEETING", "MESSAGE"] as const;
export const VISIBILITIES = ["INTERNAL", "CLINICAL", "APP_VISIBLE"] as const;
export const DOCUMENT_CATEGORIES = ["REFERRAL", "CARE_PLAN", "LETTER", "CONSENT_FORM", "ASSESSMENT", "IDENTITY", "OTHER"] as const;
export const CONSENT_TYPES = [
  "DATA_PROCESSING", "CARE_INFORMATION_SHARING", "APP_TERMS", "MARKETING_EMAIL", "MARKETING_SMS", "RESEARCH_CONTACT",
] as const;
export const CONSENT_STATUSES = ["GRANTED", "WITHDRAWN", "REFUSED"] as const;
export const CONSENT_SOURCES = ["STAFF_VERBAL", "PAPER_FORM", "ELECTRONIC_FORM", "IMPORT"] as const;
export const NOTIFICATION_STATUSES = ["QUEUED", "SENDING", "SENT", "FAILED", "SKIPPED", "CANCELLED"] as const;
export const CHANNELS = ["EMAIL", "SMS", "PUSH"] as const;
export const TEMPLATES = [
  "appointment_booked", "appointment_rescheduled", "appointment_cancelled", "appointment_reminder",
  "new_message", "document_available", "service_update",
] as const;
export const STAFF_ROLES = ["SYSTEM_ADMIN", "OPS_ADMIN", "CARE_STAFF", "COORDINATOR"] as const;
export const UPLOAD_TYPES: Record<string, string> = {
  "application/pdf": ".pdf",
  "image/png": ".png",
  "image/jpeg": ".jpg,.jpeg",
};
export const PAGE_SIZE = 25;
