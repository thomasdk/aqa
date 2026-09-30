import { afterEach, describe, expect, it, vi } from "vitest";
import {
  hasNativeLocalAIImportPicker,
  hasNativeManagedPathReveal,
  pickLocalAIImportDirectory,
  revealManagedPath,
  saveMarkdownExport,
  setNativeMenuLocale,
  setNativeAppearance,
  subscribeNativeAboutOpen,
} from "./desktopBridge";

afterEach(() => {
  delete window.__TAURI__;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
});

describe("Tauri desktop bridge", () => {
  it("invokes the narrowly scoped native file and folder commands", async () => {
    const invoke = vi.fn(async function <T>(command: string): Promise<T> {
      if (command === "save_markdown_export") return "discussion.md" as T;
      if (command === "pick_local_ai_import_directory") return "/tmp/legacy-aqa" as T;
      return undefined as T;
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };

    expect(hasNativeLocalAIImportPicker()).toBe(true);
    expect(hasNativeManagedPathReveal()).toBe(true);
    await expect(saveMarkdownExport("discussion.md", "# Discussion")).resolves.toBe(
      "discussion.md",
    );
    await expect(pickLocalAIImportDirectory()).resolves.toBe("/tmp/legacy-aqa");
    await expect(revealManagedPath("session", "safe-session")).resolves.toBeUndefined();
    await expect(revealManagedPath("prompt_library")).resolves.toBeUndefined();

    expect(invoke).toHaveBeenNthCalledWith(1, "save_markdown_export", {
      suggestedFilename: "discussion.md",
      contents: "# Discussion",
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "pick_local_ai_import_directory");
    expect(invoke).toHaveBeenNthCalledWith(3, "reveal_managed_path", {
      kind: "session",
      fileId: "safe-session",
    });
    expect(invoke).toHaveBeenNthCalledWith(4, "reveal_managed_path", {
      kind: "prompt_library",
    });
  });

  it("rejects native-only actions outside Tauri", async () => {
    expect(hasNativeLocalAIImportPicker()).toBe(false);
    expect(hasNativeManagedPathReveal()).toBe(false);
    await expect(pickLocalAIImportDirectory()).rejects.toThrow("unavailable");
    await expect(revealManagedPath("local_ai_models")).rejects.toThrow("unavailable");
    await expect(setNativeMenuLocale("de")).resolves.toBeUndefined();
  });

  it("updates app-owned native menu labels without affecting browser locale behavior", async () => {
    const invoke = vi.fn(async function <T>(command: string): Promise<T> {
      expect(command).toBe("set_native_menu_locale");
      return undefined as T;
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };

    await expect(setNativeMenuLocale("de")).resolves.toBeUndefined();
    expect(invoke).toHaveBeenCalledWith("set_native_menu_locale", { locale: "de" });
  });

  it("subscribes and unsubscribes browser and native-menu About signals", () => {
    const listener = vi.fn();
    window.history.replaceState(null, "", "#aqa-about");
    const unsubscribe = subscribeNativeAboutOpen(listener);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("");

    window.dispatchEvent(new Event("aqa:open-about"));
    expect(listener).toHaveBeenCalledTimes(2);

    window.history.replaceState(null, "", "#aqa-about");
    window.dispatchEvent(new Event("hashchange"));
    expect(listener).toHaveBeenCalledTimes(3);
    expect(window.location.hash).toBe("");

    unsubscribe();
    window.dispatchEvent(new Event("aqa:open-about"));
    expect(listener).toHaveBeenCalledTimes(3);
  });
});

describe("native appearance", () => {
  it("is a no-op in browsers and forwards each preference in Tauri", async () => {
    await expect(setNativeAppearance("system")).resolves.toBeUndefined();
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    for (const appearance of ["system", "light", "dark"] as const) {
      await setNativeAppearance(appearance);
      expect(invoke).toHaveBeenLastCalledWith("set_native_appearance", { appearance });
    }
  });
});
