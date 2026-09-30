import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createGenerationOperationId,
  resetGenerationSleepInhibitionForTests,
  setGenerationOperationActive,
  setPreventSleepWhileGenerating,
} from "./generationSleepInhibition";

describe("generation sleep inhibition", () => {
  beforeEach(() => {
    resetGenerationSleepInhibitionForTests();
  });

  afterEach(() => {
    delete window.__TAURI__;
    vi.restoreAllMocks();
  });

  it("scopes native inhibition to active operations and releases them independently", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const first = createGenerationOperationId();
    const second = createGenerationOperationId();

    setGenerationOperationActive(first, true);
    setGenerationOperationActive(second, true);
    setGenerationOperationActive(first, false);
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(3));

    expect(invoke.mock.calls).toEqual([
      ["update_generation_sleep_inhibition", { operationId: first, active: true, enabled: true }],
      ["update_generation_sleep_inhibition", { operationId: second, active: true, enabled: true }],
      ["update_generation_sleep_inhibition", { operationId: first, active: false, enabled: true }],
    ]);
  });

  it("promptly reapplies a changed preference to active generation work", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const operationId = createGenerationOperationId();
    setGenerationOperationActive(operationId, true);
    setPreventSleepWhileGenerating(false);
    setPreventSleepWhileGenerating(true);
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(3));

    expect(invoke.mock.calls.map((call) => call[1])).toEqual([
      { operationId, active: true, enabled: true },
      { operationId, active: true, enabled: false },
      { operationId, active: true, enabled: true },
    ]);
  });

  it("does not require a native bridge in browser development", () => {
    expect(() => setGenerationOperationActive(createGenerationOperationId(), true)).not.toThrow();
  });
});
