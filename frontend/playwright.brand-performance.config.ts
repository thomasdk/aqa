import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "brand-performance.spec.ts",
  outputDir: "./test-results/brand-performance",
  fullyParallel: false,
  timeout: 150_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4174",
    locale: "en-US",
    colorScheme: "dark",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "../.venv/bin/python ../tests/product_e2e_server.py",
    url: "http://127.0.0.1:4174/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
