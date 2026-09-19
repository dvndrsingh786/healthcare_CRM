import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.SEED_PASSWORD ?? "DemoPass123!";
export const SHOTS = process.env.E2E_SCREENSHOTS; // folder for review screenshots (optional)

/** Fails the test on any JavaScript error or server error while the page is used. */
export function watchForErrors(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("status of 4")) problems.push(`console: ${msg.text()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 500) problems.push(`HTTP ${response.status()} ${response.url()}`);
  });
  return problems;
}

export async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}

/** Waits until nothing is loading, so screenshots and checks see the finished page. */
export async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".mantine-Loader-root")).toHaveCount(0);
}

export async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

export async function openNav(page: Page, label: string) {
  await page.getByRole("navigation").getByRole("link", { name: label }).click();
}

/** A date well in the future, as the booking form's date text. */
export function futureDay(daysAhead: number) {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  return d;
}
