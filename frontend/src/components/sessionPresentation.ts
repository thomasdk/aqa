import i18n, { formatDateTime } from "../i18n";

export const UNKNOWN_SESSION_DATE = "Unbekannt";

/**
 * Render valid timestamps in the browser's local zone; invalid or absent input
 * returns the localized unknown label instead of exposing `Invalid Date`.
 */
export function formatLocalSessionDateTime(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return i18n.t("common.unknown");
  }

  if (typeof value !== "string" || value.trim() === "") {
    return i18n.t("common.unknown");
  }

  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return i18n.t("common.unknown");
  }

  return formatDateTime(date, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatSessionRoundLabel(count: number): string {
  return i18n.t(count === 1 ? "sessions.oneRound" : "sessions.manyRounds", { count });
}
