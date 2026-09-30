import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LocalAIStatus } from "../types";
import { waitForManagedLocalAI } from "./useWorkbenchCatalogs";

const startingStatus = {
  state: "starting",
  host_ready: false,
} as LocalAIStatus;

const runningStatus = {
  ...startingStatus,
  state: "running",
  host_ready: true,
} as LocalAIStatus;

const response = (status: LocalAIStatus, code = 200): Response =>
  ({
    ok: code >= 200 && code < 300,
    status: code,
    text: async () =>
      code >= 400 ? JSON.stringify({ detail: "temporary" }) : JSON.stringify(status),
    json: async () => status,
  }) as Response;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("waitForManagedLocalAI", () => {
  it("allows a legitimate managed startup to continue beyond 30 seconds", async () => {
    let statusRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        statusRequests += 1;
        return response(statusRequests >= 81 ? runningStatus : startingStatus);
      }),
    );

    const expectation = expect(
      waitForManagedLocalAI(startingStatus, vi.fn()),
    ).resolves.toMatchObject({
      state: "running",
      host_ready: true,
    });
    for (let poll = 0; poll < 81; poll += 1) {
      await vi.advanceTimersByTimeAsync(500);
    }

    await expectation;
  });

  it("recovers from a transient status request failure while startup remains bounded", async () => {
    let statusRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        statusRequests += 1;
        if (statusRequests === 1) return response(startingStatus, 503);
        return response(statusRequests >= 3 ? runningStatus : startingStatus);
      }),
    );

    const result = waitForManagedLocalAI(startingStatus, vi.fn());
    for (let poll = 0; poll < 3; poll += 1) {
      await vi.advanceTimersByTimeAsync(500);
    }

    await expect(result).resolves.toMatchObject({ state: "running" });
  });

  it("ends the readiness wait after the bounded startup window", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(startingStatus)),
    );

    const expectation = expect(waitForManagedLocalAI(startingStatus, vi.fn())).rejects.toThrow(
      "Managed Integrated AI did not become ready.",
    );
    for (let poll = 0; poll < 260; poll += 1) {
      await vi.advanceTimersByTimeAsync(500);
    }

    await expectation;
  });

  it("stops immediately when the backend reports a terminal lifecycle state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response({ ...startingStatus, state: "error" })),
    );

    const result = waitForManagedLocalAI(startingStatus, vi.fn());
    const expectation = expect(result).rejects.toThrow(
      "Managed Integrated AI did not become ready.",
    );
    await vi.advanceTimersByTimeAsync(500);
    await expectation;
  });
});
