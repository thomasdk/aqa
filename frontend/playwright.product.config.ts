import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "product.spec.ts",
  outputDir: "./test-results/product",
  fullyParallel: false,
  timeout: 60_000,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: 1,
  reporter: isCI
    ? [["line"], ["html", { outputFolder: "playwright-product-report", open: "never" }]]
    : "list",
  use: {
    baseURL: "http://127.0.0.1:4174",
    locale: "de-DE",
    colorScheme: "dark",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "python ../tests/product_e2e_server.py",
    url: "http://127.0.0.1:4174/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
