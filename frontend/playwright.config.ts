import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["product.spec.ts", "brand-performance.spec.ts"],
  outputDir: "./test-results/responsive",
  snapshotPathTemplate: "{testDir}/{testFilePath}-snapshots/{arg}-{projectName}-darwin{ext}",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  // Font-backed visual baselines must share one deterministic Vite asset stream.
  workers: 1,
  reporter: isCI
    ? [["line"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : "list",
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.005,
    },
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    locale: "de-DE",
    colorScheme: "dark",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm exec vite -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !isCI,
    timeout: 120_000,
  },
});
