import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { de, en } from "./locales";
import { setNativeMenuLocale } from "./desktopBridge";

export type AppLocale = "de" | "en";
export const LOCALE_STORAGE_KEY = "aqa.uiLocale.v1";
export const SUPPORTED_LOCALES: readonly AppLocale[] = ["de", "en"];

function supported(value: unknown): value is AppLocale {
  return typeof value === "string" && SUPPORTED_LOCALES.includes(value.split("-")[0] as AppLocale);
}

export function readStoredLocale(): AppLocale | null {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return supported(stored) ? (stored.split("-")[0] as AppLocale) : null;
  } catch {
    return null;
  }
}

export function detectLocale(): AppLocale {
  return readStoredLocale() ?? "en";
}

const initialLocale = detectLocale();

let nativeMenuSync: Promise<void> = Promise.resolve();

function syncNativeMenuLocale(locale: AppLocale): Promise<void> {
  nativeMenuSync = nativeMenuSync.catch(() => undefined).then(() => setNativeMenuLocale(locale));
  return nativeMenuSync;
}

void syncNativeMenuLocale(initialLocale).catch(() => undefined);

void i18n.use(initReactI18next).init({
  resources: {
    de: { translation: de },
    en: { translation: en },
  },
  lng: initialLocale,
  fallbackLng: "en",
  supportedLngs: ["de", "en"],
  interpolation: { escapeValue: false },
  returnNull: false,
  showSupportNotice: false,
});

export async function setLocale(locale: AppLocale): Promise<void> {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // A language change must still work when storage is unavailable.
  }
  await i18n.changeLanguage(locale);
  // Native menus are supplementary to the AQA language change. Keep the
  // locale change usable if the desktop bridge is unavailable or fails.
  await syncNativeMenuLocale(locale).catch(() => undefined);
}

export function localeTag(language = i18n.resolvedLanguage): "de-DE" | "en-US" {
  return language?.startsWith("en") ? "en-US" : "de-DE";
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(localeTag(), options).format(value);
}

/** Accept plain digits or complete three-digit groups for the selected UI locale. */
export function parseLocalizedInteger(
  value: string,
  language = i18n.resolvedLanguage,
): number | null {
  const separator = localeTag(language) === "de-DE" ? "." : ",";
  const grouped = separator === "." ? /^\d{1,3}(?:\.\d{3})+$/ : /^\d{1,3}(?:,\d{3})+$/;
  if (!/^\d+$/.test(value) && !grouped.test(value)) return null;
  const parsed = Number(value.split(separator).join(""));
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function formatDateTime(value: Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(localeTag(), {
    ...options,
    hourCycle: "h23",
  }).format(value);
}

export function translateErrorCode(
  code: string | null | undefined,
  params: Record<string, unknown> = {},
): string {
  const key = code ? `apiErrors.${code}` : "";
  if (!key || !i18n.exists(key)) return i18n.t("errors.requestFailed");
  const safeParams = Object.fromEntries(
    Object.entries(params)
      .filter(
        (entry): entry is [string, string | number] =>
          typeof entry[1] === "string" || typeof entry[1] === "number",
      )
      .map(([name, value]) => [name, typeof value === "number" ? formatNumber(value) : value]),
  );
  return i18n.t(key, safeParams);
}

/** Translate a structured API error without ever exposing its raw message. */
export function translateClientError(error: unknown, fallbackKey: string): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    const candidate = error as {
      code?: unknown;
      params?: unknown;
    };
    if (typeof candidate.code === "string" && candidate.code) {
      const params =
        typeof candidate.params === "object" &&
        candidate.params !== null &&
        !Array.isArray(candidate.params)
          ? (candidate.params as Record<string, unknown>)
          : {};
      return translateErrorCode(candidate.code, params);
    }
  }
  return i18n.t(fallbackKey);
}

export default i18n;
