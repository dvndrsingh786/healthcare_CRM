import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests in a real browser against a running API with the demo data (seed.py).
 *   API:      uvicorn app.main:app            (port 8000, or set API_URL for the preview proxy)
 *   Frontend: npm run build && npm run preview (port 4173)
 *   Tests:    npm run e2e                     (E2E_BASE_URL to test another address)
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } }],
});
