import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "local-smoke.spec.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: "list",
  timeout: 150_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.LOCAL_SMOKE_BASE_URL ?? "http://127.0.0.1:5173",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1440, height: 1000 },
  },
});
