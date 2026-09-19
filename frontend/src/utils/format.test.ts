import { describe, expect, it } from "vitest";

import { ApiError, describeError, fieldErrors, toApiError } from "@/api/errors";

import { humanize, patientName, toApiDateTime, toPickerValue } from "./format";

describe("time zones", () => {
  it("interprets a picked wall-clock time in the appointment's zone", () => {
    // 10:00 in London in winter is 10:00 UTC; in summer (BST) it is 09:00 UTC.
    expect(toApiDateTime("2027-03-22 10:00:00", "Europe/London")).toBe("2027-03-22T10:00:00Z"); // Z = UTC, accepted by the API
    expect(toApiDateTime("2027-07-01 10:00:00", "Europe/London")).toBe("2027-07-01T10:00:00+01:00");
    expect(toApiDateTime("2027-07-01 10:00:00", "Asia/Kolkata")).toBe("2027-07-01T10:00:00+05:30");
  });

  it("shows an API instant as wall-clock time in a zone", () => {
    expect(toPickerValue("2027-07-01T09:00:00Z", "Europe/London")).toBe("2027-07-01 10:00:00");
    expect(toPickerValue(null)).toBeNull();
  });
});

describe("labels", () => {
  it("turns API codes into words", () => {
    expect(humanize("HOME_VISIT")).toBe("Home visit");
    expect(humanize(null)).toBe("—");
  });

  it("shows the preferred name", () => {
    expect(patientName({ legal_first_name: "Margaret", legal_last_name: "Okafor", preferred_name: "Maggie" })).toBe(
      'Margaret "Maggie" Okafor',
    );
    expect(patientName({ legal_first_name: "Arthur", legal_last_name: "Pembroke", preferred_name: null })).toBe("Arthur Pembroke");
  });
});

describe("API errors", () => {
  it("reads the API's error envelope, including field errors", () => {
    const error = toApiError(422, {
      error: { code: "VALIDATION_ERROR", message: "Validation failed.", request_id: "r1", fields: [{ field: "date_of_birth", message: "In the future" }] },
    });
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(fieldErrors(error)).toEqual({ date_of_birth: "In the future" });
    expect(describeError(error)).toBe("date_of_birth: In the future");
  });

  it("never shows raw technical details", () => {
    expect(toApiError(502, "<html>Bad gateway</html>").message).toBe("Something went wrong. Please try again.");
    expect(describeError(new TypeError("Failed to fetch"))).toBe("Cannot reach the server. Is the API running?");
  });
});
