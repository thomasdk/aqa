import { afterEach, describe, expect, it, vi } from "vitest";
import i18n, {
  LOCALE_STORAGE_KEY,
  formatDateTime,
  formatNumber,
  parseLocalizedInteger,
  localeTag,
  setLocale,
  detectLocale,
  translateErrorCode,
} from "./i18n";
import { de, en } from "./locales";
import { translationContextFor } from "./translationContext";

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

function variables(value: string): string[] {
  return [...value.matchAll(/\{\{\s*([^},\s]+)[^}]*\}\}/g)].map((match) => match[1]).sort();
}

function readLeaf(catalogue: unknown, path: string): string {
  return path
    .split(".")
    .reduce<unknown>(
      (current, segment) => (current as Record<string, unknown>)[segment],
      catalogue,
    ) as string;
}

describe("UI locale catalogue", () => {
  afterEach(async () => {
    window.localStorage.removeItem(LOCALE_STORAGE_KEY);
    delete window.__TAURI__;
    await i18n.changeLanguage("de");
  });

  it("keeps German and English key sets identical and non-empty", () => {
    expect(leafPaths(en).sort()).toEqual(leafPaths(de).sort());
    for (const path of leafPaths(en)) {
      const segments = path.split(".");
      const value = segments.reduce<unknown>(
        (current, segment) => (current as Record<string, unknown>)[segment],
        en,
      );
      expect(typeof value === "string" && value.trim().length > 0, path).toBe(true);
    }
  });

  it("uses concise English navigation labels without changing German tabs", () => {
    expect(en.nav.preview).toBe("Prompt Preview");
    expect(de.nav.preview).toBe("Prompt-Vorschau");
  });

  it("uses localized session-deletion singular and plural copy", async () => {
    await setLocale("en");
    expect(i18n.t("sessions.deleteAllMessage", { count: 0 })).toContain("0 sessions");
    expect(i18n.t("sessions.deleteAllMessage", { count: 1 })).toContain("1 session,");
    expect(i18n.t("sessions.bulkDeleted", { count: 2 })).toBe("Deleted 2 sessions.");
    expect(en.sessions.empty).toContain("Prepare");

    await setLocale("de");
    expect(i18n.t("sessions.deleteAllExceptFavoritesMessage", { count: 0 })).toContain(
      "0 nicht favorisierte Sitzungen",
    );
    expect(i18n.t("sessions.deleteAllExceptFavoritesMessage", { count: 1 })).toContain(
      "1 nicht favorisierte Sitzung",
    );
    expect(i18n.t("sessions.bulkDeleted", { count: 2 })).toBe("2 Sitzungen gelöscht.");
    expect(de.sessions.empty).toContain("Vorbereiten");
  });

  it("uses Perspective terminology across both resource-management vocabularies", () => {
    expect(de.prompts.rolesTitle).toBe("Perspektiven verwalten");
    expect(de.prompts.role).toBe("Perspektive");
    expect(de.prompts.defaultRoles).toBe("Standardperspektiven");
    expect(de.prompts.restoreRoleBody).toContain("Die Perspektive");
    expect(de.errors.roleRequired).toContain("Perspektivenanweisung");
    expect(en.prompts.rolesTitle).toBe("Perspectives");
    expect(en.prompts.role).toBe("Perspective");
    expect(en.prompts.defaultRoles).toBe("Default Perspectives");
    expect(en.prompts.restoreRoleBody).toContain("The perspective");
    expect(en.errors.roleRequired).toContain("perspective instruction");
  });

  it("keeps Prepare material types and required language guidance concise", () => {
    expect(Object.keys(en.setup.materialTypes)).toEqual([
      "interview",
      "focus_group",
      "document",
      "media",
      "fieldnotes",
      "memo",
      "other",
    ]);
    expect(en.setup.materialTypes).toEqual({
      interview: "Interview",
      focus_group: "Focus Group",
      document: "Text Document",
      media: "Multimedia Transcript",
      fieldnotes: "Field Notes",
      memo: "Research Memo",
      other: "Other",
    });
    expect(de.setup.materialTypes).toEqual({
      interview: "Interview",
      focus_group: "Fokusgruppe",
      document: "Textdokument",
      media: "Multimediatranskript",
      fieldnotes: "Feldnotizen",
      memo: "Forschungsmemo",
      other: "Sonstiges",
    });
    expect(en.setup.targetLanguage).toBe("Target Language");
    expect(en.setup.targetLanguagePlaceholder).toBe("e.g. English");
    expect(en.setup.aiAccess).not.toHaveProperty("configure");
    expect(en.setup.options).toBe("Options");
    expect(de.setup.options).toBe("Optionen");
  });

  it("keeps interpolation variables aligned with translator context", () => {
    for (const path of leafPaths(de)) {
      expect(variables(readLeaf(en, path)), path).toEqual(variables(readLeaf(de, path)));
      expect(translationContextFor(path), path).not.toBeNull();
    }
  });

  it("allows identical German and English copy only for intentional shared terms", () => {
    const identical = leafPaths(de).filter((path) => readLeaf(de, path) === readLeaf(en, path));
    expect(identical).toEqual([
      "app.title",
      "app.german",
      "app.english",
      "app.tagline",
      "nav.system",
      "common.optional",
      "release.versionLabel",
      "release.versionValue",
      "release.statusLabel",
      "setup.material",
      "setup.materialTokenEstimate",
      "setup.host",
      "setup.materialTypes.interview",
      "network.label",
      "network.url",
      "network.urlPlaceholder",
      "localAi.downloadSize",
      "localAi.status",
      "localAi.memoryVram",
      "prompts.estimatedTokens",
      "prompts.tokens",
      "prompts.id",
      "system.title",
      "toolbar.export",
      "activityLog.sourceServer",
      "activityLog.level.info",
    ]);
  });

  it("has US-English copy for every generic backend error code", () => {
    const codes = [
      "bad_request",
      "authentication_required",
      "forbidden",
      "target_language_required",
      "not_found",
      "conflict",
      "validation_failed",
      "rate_limited",
      "internal_error",
      "service_unavailable",
      "provider_authentication_failed",
      "provider_credit_required",
      "provider_rate_limited",
      "provider_timeout",
      "provider_model_rejected",
      "provider_unavailable",
      "provider_request_failed",
      "provider_connection_failed",
      "provider_response_invalid",
      "provider_model_crashed",
      "provider_health_check_failed",
      "provider_empty_response",
      "synthesis_no_usable_contributions",
      "host_update_persistence_failed",
    ];
    for (const code of codes) expect(i18n.exists(`apiErrors.${code}`), code).toBe(true);
  });

  it("persists a language change and applies locale-aware number formatting", async () => {
    await setLocale("en");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(formatNumber(1234.5)).toBe("1,234.5");

    await setLocale("de");
    expect(formatNumber(1234.5)).toBe("1.234,5");
  });

  it("parses only plain or correctly grouped safe integers in the active locale", () => {
    for (const [language, grouped] of [
      ["en", "131,072"],
      ["de", "131.072"],
    ] as const) {
      expect(parseLocalizedInteger("999", language)).toBe(999);
      expect(parseLocalizedInteger("32768", language)).toBe(32_768);
      expect(parseLocalizedInteger(grouped, language)).toBe(131_072);
    }
    for (const draft of [
      "",
      "1,00",
      "1.00",
      "1 000",
      "1,000.0",
      "-1000",
      "1e3",
      "9007199254740993",
    ]) {
      expect(parseLocalizedInteger(draft, "en")).toBeNull();
      expect(parseLocalizedInteger(draft, "de")).toBeNull();
    }
    expect(parseLocalizedInteger("8.000", "en")).toBeNull();
    expect(parseLocalizedInteger("8,000", "de")).toBeNull();
  });

  it("synchronizes app-owned native menus after a language change when running in Tauri", async () => {
    const invoke = vi.fn(async function <T>(command: string): Promise<T> {
      expect(command).toBe("set_native_menu_locale");
      return undefined as T;
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };

    await setLocale("de");

    expect(invoke).toHaveBeenCalledWith("set_native_menu_locale", { locale: "de" });
  });

  it("keeps the AQA language change when native menu synchronization fails", async () => {
    const invoke = vi.fn(async function <T>(): Promise<T> {
      throw new Error("native menu unavailable");
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };

    await expect(setLocale("en")).resolves.toBeUndefined();

    expect(i18n.resolvedLanguage).toBe("en");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(invoke).toHaveBeenCalledWith("set_native_menu_locale", { locale: "en" });
  });

  it("uses US English formatting for the English catalogue", async () => {
    await setLocale("en");
    expect(new Intl.DateTimeFormat(localeTag()).resolvedOptions().locale).toMatch(/^en-US/i);
  });

  it("uses a 24-hour clock for English date-times", async () => {
    await setLocale("en");
    const midnight = new Date(2024, 4, 12, 0, 5);
    const formatted = formatDateTime(midnight, { dateStyle: "medium", timeStyle: "short" });

    expect(formatted).toBe(
      new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
        hourCycle: "h23",
      }).format(midnight),
    );
    expect(formatted).toContain("00:05");
    expect(formatted).not.toMatch(/\b(?:AM|PM)\b/i);
  });

  it("defaults to English regardless of the browser language when no preference is stored", () => {
    expect(navigator.language).toMatch(/^de/i);
    expect(detectLocale()).toBe("en");
  });

  it("localizes stable error codes and bounds unknown codes", async () => {
    await setLocale("en");
    expect(translateErrorCode("local_ai_not_running")).toContain("Integrated AI");
    expect(translateErrorCode("target_language_required")).toBe(
      "This session needs a target language. Start a new discussion with a target language.",
    );
    expect(translateErrorCode("provider_credit_required")).toContain("credit or budget");
    expect(translateErrorCode("provider_model_rejected")).toContain("model ID");
    expect(
      translateErrorCode("context_limit_exceeded", {
        input_tokens: 43_166,
        available_input_tokens: 28_672,
        context_tokens: 32_768,
        reserved_output_tokens: 4_096,
      }),
    ).toContain("43,166 input tokens");
    expect(translateErrorCode("unknown_backend_code")).toBe("The action could not be completed.");

    await setLocale("de");
    expect(translateErrorCode("agent_generation_failed")).toBe(
      "Die Antwort der Perspektive konnte nicht erzeugt werden.",
    );

    await setLocale("en");
    expect(translateErrorCode("forbidden")).toBe("This action is not permitted.");
  });
});
