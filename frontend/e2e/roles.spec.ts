/**
 * Each role sees what it should, in a real browser. One login per role (login is rate limited).
 * Needs the demo data from seed.py.
 */
import { expect, test, type Page } from "@playwright/test";

import { login, openNav, shot, watchForErrors } from "./helpers";

test.describe.configure({ mode: "serial" });

test("login page: wrong password shows a clear error", async ({ page }) => {
  await page.goto("/login");
  await shot(page, "01-login");
  await page.getByLabel("Email", { exact: true }).fill("nobody@northfield.example");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
});

test.describe("operations admin", () => {
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

  test("dashboard", async () => {
    await expect(page.getByRole("heading", { name: /Hello, Olivia/ })).toBeVisible();
    await expect(page.getByText("Appointments today", { exact: true })).toBeVisible();
    await expect(page.getByText("Open tasks", { exact: true })).toBeVisible();
    await shot(page, "02-ops-dashboard");
  });

  test("patients list and search", async () => {
    await openNav(page, "Patients");
    await expect(page.getByRole("cell", { name: /Margaret "Maggie" Okafor/ })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Date of birth" })).toBeVisible();
    await shot(page, "03-ops-patients");
    await page.getByPlaceholder(/Search name/).fill("pembroke");
    await expect(page.getByRole("cell", { name: /Arthur Pembroke/ })).toBeVisible();
    await expect(page.getByRole("cell", { name: /Okafor/ })).toHaveCount(0);
    // The search text never goes in the page address.
    expect(page.url()).not.toContain("pembroke");
    await page.getByPlaceholder(/Search name/).fill("");
  });

  test("patient record with every tab", async () => {
    await page.getByRole("cell", { name: /Margaret "Maggie" Okafor/ }).click();
    await expect(page.getByRole("heading", { name: /Margaret "Maggie" Okafor/ })).toBeVisible();
    await expect(page.getByText("David Okafor")).toBeVisible();
    await shot(page, "04-ops-patient-overview");
    for (const tab of ["Care team", "Appointments", "Tasks", "Notes", "Documents", "Consent", "Messages", "Timeline"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tabpanel")).toBeVisible();
      await page.waitForLoadState("networkidle");
      await shot(page, `05-ops-patient-${tab.toLowerCase().replace(" ", "-")}`);
    }
    // Ops admins have no clinical access: the seeded clinical note is not listed.
    await page.getByRole("tab", { name: "Notes" }).click();
    await expect(page.getByText("Welfare call")).toBeVisible();
    await expect(page.getByText("Wound review")).toHaveCount(0);
  });

  test("appointments calendar, tasks and messages pages", async () => {
    await openNav(page, "Appointments");
    await expect(page.locator(".fc-timegrid")).toBeVisible();
    await shot(page, "06-ops-calendar");
    await openNav(page, "Tasks");
    await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
    await shot(page, "07-ops-tasks");
    await openNav(page, "Messages");
    await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
    await shot(page, "08-ops-messages");
  });
});

test.describe("care staff (nurse)", () => {
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

  test("sees only assigned patients and clinical notes", async () => {
    await openNav(page, "Patients");
    await expect(page.getByRole("cell", { name: /Okafor/ })).toBeVisible();
    await expect(page.getByRole("cell", { name: /Pembroke/ })).toHaveCount(0); // not assigned to her
    await page.getByRole("cell", { name: /Okafor/ }).click();
    await page.getByRole("tab", { name: "Notes" }).click();
    await expect(page.getByText("Wound review")).toBeVisible();
    await shot(page, "09-nurse-notes");
    // No admin menu for care staff.
    await expect(page.getByText("Administration")).toHaveCount(0);
  });
});

test.describe("coordinator", () => {
  let page: Page;
  let problems: string[];
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    problems = watchForErrors(page);
    await login(page, "coordinator@northfield.example");
  });
  test.afterAll(async () => {
    expect(problems, problems.join("\n")).toEqual([]);
    await page.close();
  });

  test("no sensitive fields, no clinical notes, no documents", async () => {
    await openNav(page, "Patients");
    await expect(page.getByRole("columnheader", { name: "Date of birth" })).toHaveCount(0);
    await page.getByRole("cell", { name: /Okafor/ }).click();
    await expect(page.getByText("Date of birth, address and MRN are hidden for your role.")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Documents" })).toHaveCount(0);
    await page.getByRole("tab", { name: "Notes" }).click();
    await expect(page.getByText("Clinical notes are restricted")).toBeVisible();
    await expect(page.getByText("Wound review")).toHaveCount(0);
    await shot(page, "10-coordinator-patient");
  });
});

test.describe("system admin", () => {
  let page: Page;
  let problems: string[];
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    problems = watchForErrors(page);
    await login(page, "admin@northfield.example");
  });
  test.afterAll(async () => {
    expect(problems, problems.join("\n")).toEqual([]);
    await page.close();
  });

  test("no patient access, admin screens instead", async () => {
    await expect(page).toHaveURL(/\/admin\/users/);
    await expect(page.getByRole("navigation").getByRole("link", { name: "Patients" })).toHaveCount(0);
    await shot(page, "11-admin-users");
    // Typing a patient address directly just sends them back to their start page.
    await page.goto("/patients");
    await expect(page).toHaveURL(/\/admin\/users/);
    for (const [label, name] of [["Teams", "12-admin-teams"], ["Service accounts", "13-admin-service-accounts"], ["Audit log", "14-admin-audit"], ["Organisation", "15-admin-organisation"]]) {
      await openNav(page, label);
      await page.waitForLoadState("networkidle");
      await shot(page, name);
    }
    await expect(page.getByLabel("Name")).toHaveValue("Northfield Community Health");
  });
});
