/** The API's single error shape: {"error": {"code", "message", "request_id", "fields"}}. */
export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  fields: FieldError[];

  constructor(status: number, code: string, message: string, requestId?: string, fields: FieldError[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; request_id?: string; fields?: FieldError[] };
}

export function toApiError(status: number, body: unknown): ApiError {
  const error = (body as ErrorBody | undefined)?.error;
  if (error?.code) {
    return new ApiError(status, error.code, error.message ?? "Request failed.", error.request_id, error.fields ?? []);
  }
  return new ApiError(status, status >= 500 ? "TEMPORARY_FAILURE" : "ERROR", "Something went wrong. Please try again.");
}

/** Readable text for a notification, including field errors. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fields.length) {
      return error.fields.map((f) => `${f.field}: ${f.message}`).join("\n");
    }
    return error.message;
  }
  if (error instanceof TypeError) {
    return "Cannot reach the server. Is the API running?";
  }
  return "Something went wrong. Please try again.";
}

/** Field errors keyed by field name, for showing next to form inputs. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  return Object.fromEntries(error.fields.map((f) => [f.field, f.message]));
}
