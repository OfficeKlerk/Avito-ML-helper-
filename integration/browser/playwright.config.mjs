import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  outputDir: "../../reports/i2-playwright",
  reporter: "list",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.I2_BASE_URL ?? "http://127.0.0.1:13000",
    channel: process.env.I2_BROWSER_CHANNEL || undefined,
  },
});
