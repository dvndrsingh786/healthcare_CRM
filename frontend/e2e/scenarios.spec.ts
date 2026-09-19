/**
 * The realistic scenarios from docs/MANUAL_TESTING.md, done through the screens in a real browser.
 * Needs the demo data from seed.py. Each run uses fresh names, so it can be repeated.
 */
import { expect, test, type Page } from "@playwright/test";

import { login, openNav, settle, shot, watchForErrors } from "./helpers";

test.describe.configure({ mode: "serial" });

const suffix = Array.from({ length: 6 }, () => "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)]).join("");
const surname = `Tester${suffix}`;
const PDF = Buffer.from("%PDF-1.4\n% e2e test letter\n" + "Referral text.\n".repeat(20) + "%%EOF\n");

async function pickOption(page: Page, label: string, typed: string, option: RegExp) {
  // Mantine pickers are comboboxes.
  const input = page.getByRole("dialog").getByRole("combobox", { name: label, exact: true });
  await input.click();
  await input.fill(typed);
  await page.getByRole("option", { name: option }).first().click();
}

test.describe("operations admin: patient intake, appointment lifecycle, documents", () => {
  let page: Page;
  let problems: string[];
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    problems = watchForErrors(page);
    await login(page, "ops@northfield.example");
  });
  test.afterAll(async () => {
    expect(problems, problems.join("\n")).toEqual([]);
    await page.close();
  });

  test("new patient: validation, duplicate warning, consent, assign the nurse", async () => {
    await openNav(page, "Patients");
    await page.getByRole("button", { name: "New patient" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Create patient" }).click();
    // Required fields: the browser refuses to submit and marks the first empty field.
    const firstName = dialog.getByLabel("Legal first name");
    expect(await firstName.evaluate((el) => (el as HTMLInputElement).validity.valueMissing)).toBe(true);
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Legal first name").fill("Rosa");
    await dialog.getByLabel("Legal last name").fill(surname);
    await dialog.getByLabel("Date of birth").fill("5 May 1955"); // typed, as staff usually do
    await dialog.getByLabel("Date of birth").press("Tab");
    await dialog.getByLabel("Phone").fill("+44 7700 900555");
    await dialog.getByRole("button", { name: "Create patient" }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`Rosa ${surname}`) })).toBeVisible();
    await shot(page, "20-new-patient");

    // The same person again is flagged, and can be confirmed as someone else.
    await openNav(page, "Patients");
    await page.getByRole("button", { name: "New patient" }).click();
    await dialog.getByLabel("Legal first name").fill("Rosa");
    await dialog.getByLabel("Legal last name").fill(surname);
    await dialog.getByLabel("Date of birth").fill("5 May 1955"); // typed, as staff usually do
    await dialog.getByLabel("Date of birth").press("Tab");
    await dialog.getByRole("button", { name: "Create patient" }).click();
    await expect(dialog.getByText("Possible duplicate")).toBeVisible();
    await shot(page, "21-duplicate-warning");
    await dialog.getByRole("button", { name: "Cancel" }).click();

    // Open the first Rosa, record consent and assign the nurse.
    await page.getByPlaceholder(/Search name/).fill(surname);
    await page.getByRole("cell", { name: new RegExp(`Rosa ${surname}`) }).click();
    await page.getByRole("tab", { name: "Consent" }).click();
    await page.getByRole("button", { name: "Record consent" }).click();
    await dialog.getByLabel("Policy / wording version").fill("privacy-2026.1");
    await dialog.getByRole("button", { name: "Record" }).click();
    await expect(page.getByRole("cell", { name: "Data processing" }).first()).toBeVisible();
    await page.getByRole("tab", { name: "Care team" }).click();
    await page.getByRole("button", { name: "Assign" }).click();
    await pickOption(page, "Staff member", "Nadia", /Nadia Nurse/);
    await dialog.getByRole("button", { name: "Assign" }).click();
    await expect(page.getByRole("cell", { name: "Nadia Nurse" })).toBeVisible();
    await shot(page, "22-care-team");
  });

  test("appointment: book from the calendar, reschedule, cancel, history", async () => {
    await openNav(page, "Appointments");
    // A random future slot (2-9 weeks ahead, a weekday, 08:00-16:00), so repeated runs never
    // land on an appointment an earlier run booked.
    const weeksAhead = 2 + Math.floor(Math.random() * 8);
    for (let i = 0; i < weeksAhead; i++) {
      await page.getByRole("button", { name: "Next" }).first().click();
    }
    await settle(page);
    const day = page.locator("th.fc-col-header-cell").nth(Math.floor(Math.random() * 5));
    const hour = String(8 + Math.floor(Math.random() * 9)).padStart(2, "0");
    const slot = page.locator(`td.fc-timegrid-slot-lane[data-time="${hour}:00:00"]`);
    const x = (await day.boundingBox())!;
    const y = (await slot.boundingBox())!;
    await page.mouse.click(x.x + x.width / 2, y.y + y.height / 2);

    const dialog = page.getByRole("dialog", { name: "Book appointment", exact: true });
    await expect(dialog).toBeVisible();
    await pickOption(page, "Patient", surname.slice(0, 8), new RegExp(`Rosa ${surname}`));
    await pickOption(page, "Staff member", "Nadia", /Nadia Nurse/);
    await dialog.getByLabel("Location").fill("Patient's home");
    await dialog.getByLabel("Internal note").fill("Key safe code with the office");
    await shot(page, "23-booking-form");
    await dialog.getByRole("button", { name: "Book" }).click();

    // The drawer opens on the new appointment.
    const drawer = page.getByRole("dialog", { name: "Appointment", exact: true });
    await expect(drawer.getByText("Scheduled", { exact: true })).toBeVisible();
    await expect(drawer.getByText("Key safe code with the office")).toBeVisible();
    await shot(page, "24-appointment-drawer");

    await drawer.getByRole("button", { name: "Reschedule" }).click();
    const reschedule = page.getByRole("dialog", { name: "Reschedule", exact: true });
    await reschedule.getByLabel("Length").click();
    await page.getByRole("option", { name: "1 h", exact: true }).click();
    await reschedule.getByLabel("Reason").fill("Nurse on training");
    await reschedule.getByRole("button", { name: "Reschedule" }).click();
    await expect(page.getByText("Rescheduled. The patient is notified.")).toBeVisible();

    await drawer.getByRole("button", { name: "Cancel" }).click();
    const cancel = page.getByRole("dialog", { name: "Cancel appointment", exact: true });
    await cancel.getByLabel(/Reason/).fill("Patient admitted to hospital");
    await cancel.getByRole("button", { name: "Cancel appointment" }).click();
    await expect(drawer.getByText("Cancelled", { exact: true }).first()).toBeVisible();
    await expect(drawer.getByText("Rescheduled", { exact: true })).toBeVisible();
    await expect(drawer.getByText("Reason: Patient admitted to hospital")).toBeVisible();
    await shot(page, "25-appointment-history");
    await page.keyboard.press("Escape");
  });

  test("documents: upload a PDF, then download it", async () => {
    await openNav(page, "Patients");
    await page.getByPlaceholder(/Search name/).fill(surname);
    await page.getByRole("cell", { name: new RegExp(`Rosa ${surname}`) }).click();
    await page.getByRole("tab", { name: "Documents" }).click();
    await page.getByRole("button", { name: "Upload" }).click();
    const dialog = page.getByRole("dialog", { name: "Upload document", exact: true });
    await dialog.locator('input[type="file"]').setInputFiles({ name: "referral.pdf", mimeType: "application/pdf", buffer: PDF });
    await dialog.getByLabel("Title").fill("GP referral");
    await dialog.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByText("Document uploaded")).toBeVisible();
    await expect(page.getByText("GP referral")).toBeVisible();
    await shot(page, "26-documents");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download" }).click();
    expect((await download).suggestedFilename()).toBe("referral.pdf");
  });
});

test.describe("the nurse sees the new patient and the cancelled visit", () => {
  let page: Page;
  let problems: string[];
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    problems = watchForErrors(page);
    await login(page, "nurse@northfield.example");
  });
  test.afterAll(async () => {
    expect(problems, problems.join("\n")).toEqual([]);
    await page.close();
  });

  test("caseload and appointment history", async () => {
    await openNav(page, "Patients");
    await page.getByPlaceholder(/Search name/).fill(surname);
    await page.getByRole("cell", { name: new RegExp(`Rosa ${surname}`) }).click();
    await page.getByRole("tab", { name: "Appointments" }).click();
    await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
    // Nurses record outcomes but cannot cancel or book.
    await expect(page.getByRole("button", { name: "Book appointment" })).toHaveCount(0);
    await shot(page, "27-nurse-appointments");
  });
});

test.describe("the admin sees it in the audit log", () => {
  test("audit search", async ({ browser }) => {
    const page = await browser.newPage();
    const problems = watchForErrors(page);
    await login(page, "admin@northfield.example");
    await openNav(page, "Audit log");
    await page.getByLabel("Action").fill("appointment.*");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("appointment.cancelled").first()).toBeVisible();
    await expect(page.getByText("appointment.reschedule").first()).toBeVisible();
    await shot(page, "28-audit");
    expect(problems, problems.join("\n")).toEqual([]);
    await page.close();
  });
});
