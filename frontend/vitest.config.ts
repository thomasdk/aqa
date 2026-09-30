/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Locale state is persisted through Node's process-wide localStorage
    // backing file. Run files serially so tests cannot overwrite another
    // file's selected locale while it is asserting persisted UI state.
    fileParallelism: false,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/api/generated.ts", "src/vite-env.d.ts"],
      reporter: ["text", "json-summary", "lcov"],
      reportsDirectory: "coverage",
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
