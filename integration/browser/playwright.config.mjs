import { defineConfig } from "@playwright/test";

const outputDir = process.env.Q3_PERFORMANCE ? `q3-${process.env.Q3_PERFORMANCE}` :
  process.env.I5_LIVE_MODEL ? "i5-playwright" :
  process.env.I6_RECOVERY ? "i6-playwright" :
  process.env.I34_PROJECT ? "i34-playwright" : "i2-playwright";

export default defineConfig({
  testDir: ".",
  outputDir: `../../reports/${outputDir}`,
  reporter: process.env.Q3_PERFORMANCE || process.env.I6_RECOVERY || process.env.I5_LIVE_MODEL
    ? [["list"], ["json", { outputFile: `../../reports/${outputDir}-result.json` }]]
    : "list",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.I2_BASE_URL ?? "http://127.0.0.1:13000",
    channel: process.env.I2_BROWSER_CHANNEL || undefined,
  },
});
