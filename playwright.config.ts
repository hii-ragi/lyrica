import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/ui",
  testMatch: "**/*.pw.ts",
  fullyParallel: false,
  timeout: 90000,
  expect: { timeout: 10000 },
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:1420",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1400, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:1420",
    reuseExistingServer: !process.env.CI,
  },
});
