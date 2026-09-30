import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  APPEARANCE_STORAGE_KEY,
  getAppearance,
  getAppearanceRevision,
  hydrateAppearance,
  initializeAppearance,
  selectAppearance,
  waitForNativeAppearance,
} from "./appearance";

vi.mock("./desktopBridge", () => ({ setNativeAppearance: vi.fn().mockResolvedValue(undefined) }));

let dispose: (() => void) | undefined;
let dark = false;
let listeners: Set<() => void>;

beforeEach(() => {
  window.localStorage.clear();
  dark = false;
  listeners = new Set();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      get matches() {
        return dark;
      },
      addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
    })),
  );
});
afterEach(async () => {
  await waitForNativeAppearance();
  dispose?.();
  vi.unstubAllGlobals();
});
function osChange(value: boolean) {
  dark = value;
  [...listeners].forEach((listener) => listener());
}

describe("appearance lifecycle", () => {
  it("defaults to system and follows OS changes live", async () => {
    dispose = initializeAppearance();
    await waitForNativeAppearance();
    expect(getAppearance()).toBe("system");
    expect(document.documentElement.dataset.theme).toBe("light");
    osChange(true);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("restores explicit choices and ignores OS changes", () => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");
    dispose = initializeAppearance();
    osChange(false);
    expect(getAppearance()).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(listeners.size).toBe(0);
  });

  it("uses server state over a stale origin cache but protects newer user choices", () => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");
    dispose = initializeAppearance();
    const revision = getAppearanceRevision();
    hydrateAppearance("light", revision);
    expect(getAppearance()).toBe("light");
    selectAppearance("dark");
    hydrateAppearance("system", revision);
    expect(getAppearance()).toBe("dark");
  });

  it("cleans listeners during rapid choices and shutdown", async () => {
    dispose = initializeAppearance();
    selectAppearance("dark");
    selectAppearance("system");
    selectAppearance("light");
    selectAppearance("system");
    await waitForNativeAppearance();
    expect(listeners.size).toBe(1);
    dispose();
    expect(listeners.size).toBe(0);
  });

  it("does not reattach listeners when native work finishes after disposal", async () => {
    dispose = initializeAppearance();
    dispose();
    await waitForNativeAppearance();
    expect(listeners.size).toBe(0);
  });

  it("handles missing storage and media-query APIs", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.stubGlobal("matchMedia", undefined);
    dispose = initializeAppearance();
    expect(getAppearance()).toBe("system");
    expect(document.documentElement.dataset.theme).toBe("light");
    selectAppearance("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    vi.restoreAllMocks();
  });
});
