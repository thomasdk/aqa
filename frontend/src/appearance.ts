import { setNativeAppearance } from "./desktopBridge";
import { useSyncExternalStore } from "react";

export type Appearance = "system" | "light" | "dark";
export const APPEARANCE_STORAGE_KEY = "aqa.appearance";
let preference: Appearance = "system";
let revision = 0;
let lifecycleGeneration = 0;
let disposed = false;
let nativeWrite: Promise<void> = Promise.resolve();
let removeMediaListener: (() => void) | undefined;
const subscribers = new Set<() => void>();

export function isAppearance(value: unknown): value is Appearance {
  return value === "system" || value === "light" || value === "dark";
}

function readCachedAppearance(): Appearance {
  try {
    const cached = window.localStorage.getItem(APPEARANCE_STORAGE_KEY);
    return isAppearance(cached) ? cached : "system";
  } catch {
    return "system";
  }
}

function applyAppearance(): void {
  if (disposed) return;
  removeMediaListener?.();
  removeMediaListener = undefined;
  let media: MediaQueryList | undefined;
  if (preference === "system") {
    try {
      media = window.matchMedia?.("(prefers-color-scheme: dark)");
    } catch {
      // A restricted webview can omit media-query support; use the light palette.
    }
  }
  const apply = () => {
    const resolved = preference === "system" ? (media?.matches ? "dark" : "light") : preference;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
  };
  apply();
  if (media?.addEventListener) {
    try {
      media.addEventListener("change", apply);
      removeMediaListener = () => media.removeEventListener?.("change", apply);
    } catch {
      // Keep the resolved palette when a restricted media API rejects listeners.
    }
  }
}

function setAppearance(value: Appearance): void {
  preference = value;
  try {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, value);
  } catch {
    // The current appearance remains usable without the startup cache.
  }
  applyAppearance();
  const currentRevision = revision;
  const currentGeneration = lifecycleGeneration;
  nativeWrite = nativeWrite
    .catch(() => undefined)
    .then(() => setNativeAppearance(value))
    .then(() => {
      if (
        lifecycleGeneration === currentGeneration &&
        revision === currentRevision &&
        preference === value
      )
        applyAppearance();
    })
    .catch(() => undefined);
  subscribers.forEach((listener) => listener());
}

/** Cache paints startup only; a successful server read owns the persisted choice. */
export function initializeAppearance(): () => void {
  disposed = false;
  lifecycleGeneration += 1;
  setAppearance(readCachedAppearance());
  return () => {
    disposed = true;
    lifecycleGeneration += 1;
    removeMediaListener?.();
    removeMediaListener = undefined;
  };
}

export function getAppearanceRevision(): number {
  return revision;
}

export function hydrateAppearance(value: Appearance, expectedRevision: number): void {
  if (revision === expectedRevision && isAppearance(value)) setAppearance(value);
}

export function selectAppearance(value: Appearance): void {
  revision += 1;
  setAppearance(value);
}

export function getAppearance(): Appearance {
  return preference;
}

function subscribe(listener: () => void): () => void {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

export function useAppearance(): Appearance {
  return useSyncExternalStore(subscribe, getAppearance, () => "system");
}

export function waitForNativeAppearance(): Promise<void> {
  return nativeWrite;
}
