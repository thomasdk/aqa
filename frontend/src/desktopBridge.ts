type TauriInvoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;

declare global {
  interface Window {
    __TAURI__?: {
      core?: {
        invoke?: TauriInvoke;
      };
    };
  }
}

export function hasNativeMarkdownExport(): boolean {
  return typeof window.__TAURI__?.core?.invoke === "function";
}

export async function saveMarkdownExport(
  suggestedFilename: string,
  contents: string,
): Promise<string | null> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {
    throw new Error("Native Markdown export is unavailable");
  }
  return invoke<string | null>("save_markdown_export", {
    suggestedFilename,
    contents,
  });
}

export function hasNativeLocalAIImportPicker(): boolean {
  return typeof window.__TAURI__?.core?.invoke === "function";
}

export async function pickLocalAIImportDirectory(): Promise<string | null> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {
    throw new Error("Native Local AI directory selection is unavailable");
  }
  return invoke<string | null>("pick_local_ai_import_directory");
}

export type ManagedPathKind =
  "session" | "local_ai_models" | "perspectives" | "session_types" | "prompt_library";

export function hasNativeManagedPathReveal(): boolean {
  return typeof window.__TAURI__?.core?.invoke === "function";
}

export async function revealManagedPath(kind: ManagedPathKind, fileId?: string): Promise<void> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {
    throw new Error("Native managed-folder reveal is unavailable");
  }
  await invoke("reveal_managed_path", {
    kind,
    ...(fileId ? { fileId } : {}),
  });
}

export type NativeMenuLocale = "de" | "en";

/**
 * Keep app-owned native menu copy aligned with the AQA locale. In browser
 * mode there is no native menu, so this intentionally becomes a no-op.
 */
export async function setNativeMenuLocale(locale: NativeMenuLocale): Promise<void> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) return;
  await invoke("set_native_menu_locale", { locale });
}

export async function updateGenerationSleepInhibition(
  operationId: string,
  active: boolean,
  enabled: boolean,
): Promise<void> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) return;
  await invoke("update_generation_sleep_inhibition", { operationId, active, enabled });
}

/** Apply the preference to app-owned desktop chrome; system clears any override. */
export async function setNativeAppearance(appearance: "system" | "light" | "dark"): Promise<void> {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) return;
  await invoke("set_native_appearance", { appearance });
}

const OPEN_ABOUT_EVENT = "aqa:open-about";
const OPEN_ABOUT_HASH = "#aqa-about";

export function subscribeNativeAboutOpen(listener: () => void): () => void {
  const handleHashChange = () => {
    if (window.location.hash !== OPEN_ABOUT_HASH) return;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    listener();
  };
  window.addEventListener(OPEN_ABOUT_EVENT, listener);
  window.addEventListener("hashchange", handleHashChange);
  handleHashChange();
  return () => {
    window.removeEventListener(OPEN_ABOUT_EVENT, listener);
    window.removeEventListener("hashchange", handleHashChange);
  };
}
