import type { SessionSummary } from "./types";
import i18n from "../i18n";

export const MAX_SESSION_TITLE_LENGTH = 200;

/**
 * Collapse whitespace, reject blank titles, and truncate to the server limit.
 */
export function normalizeSessionTitleInput(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "string") return null;
  const collapsed = raw.replace(/\s+/g, " ").trim();
  if (collapsed.length === 0) return null;
  if (collapsed.length > MAX_SESSION_TITLE_LENGTH) {
    return collapsed.slice(0, MAX_SESSION_TITLE_LENGTH);
  }
  return collapsed;
}

/** Reject blank or unchanged title edits before persistence. */
export function shouldPersistTitleEdit(
  raw: string | null | undefined,
  currentTitle: string,
): boolean {
  const normalized = normalizeSessionTitleInput(raw);
  if (normalized === null) return false;
  if (normalized === currentTitle) return false;
  return true;
}

export function buildSessionRoundLabel(count: number): string {
  return i18n.t(count === 1 ? "sessions.oneRound" : "sessions.manyRounds", { count });
}

export function buildDeleteSessionMessage(
  session: Pick<SessionSummary, "title" | "is_open">,
): string {
  const safeTitle = session.title?.trim() || i18n.t("sessions.thisSession");
  return i18n.t(session.is_open ? "sessions.deleteOpenMessage" : "sessions.deleteMessage", {
    title: safeTitle,
  });
}

/** Separate the first open session and sort the remaining copy newest-first. */
export function partitionOpenSession(sessions: readonly SessionSummary[]): {
  openSession: SessionSummary | null;
  others: SessionSummary[];
} {
  let openSession: SessionSummary | null = null;
  const others: SessionSummary[] = [];
  for (const session of sessions) {
    if (session.is_open && openSession === null) {
      openSession = session;
    } else {
      others.push(session);
    }
  }
  others.sort((a, b) => b.updated.localeCompare(a.updated));
  return { openSession, others };
}

export function buildSessionMetaLine(
  updated: string | null | undefined,
  roundCount: number,
  formatDate: (value: string | null | undefined) => string,
): string {
  const dateLabel = formatDate(updated);
  const roundLabel = buildSessionRoundLabel(roundCount);
  return `${dateLabel} · ${roundLabel}`;
}

export type DateGroupKey =
  "today" | "yesterday" | "last_7_days" | "last_30_days" | "older_than_30_days";

export interface DateGroupDefinition {
  key: DateGroupKey;
}

/** Canonical display order for session date groups. */
export const DATE_GROUPS: readonly DateGroupDefinition[] = [
  { key: "today" },
  { key: "yesterday" },
  { key: "last_7_days" },
  { key: "last_30_days" },
  { key: "older_than_30_days" },
];

function localizedDateGroupLabel(key: DateGroupKey): string {
  const translationKey =
    key === "last_7_days"
      ? "last7"
      : key === "last_30_days"
        ? "last30"
        : key === "older_than_30_days"
          ? "older"
          : key;
  return i18n.t(`sessions.${translationKey}`);
}

export interface DateGroup {
  key: DateGroupKey;
  label: string;
  sessions: SessionSummary[];
}

export type FavoriteFilterMode = "all" | "favorites";

function toDate(value: Date | number | string): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed.length === 0) return null;
    const d = new Date(trimmed);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function startOfLocalDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate(), 0, 0, 0, 0);
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Use local-calendar boundaries so sessions around midnight are classified by
 * calendar day. Future or invalid timestamps use the fallback group.
 */
function classifyByLocalDayDiff(updated: string | null | undefined, now: Date): DateGroupKey {
  const parsed = updated === null || updated === undefined ? null : toDate(updated);
  if (parsed === null) {
    return "older_than_30_days";
  }
  const nowStart = startOfLocalDay(now);
  const sessionStart = startOfLocalDay(parsed);
  const dayDiff = Math.round((nowStart.getTime() - sessionStart.getTime()) / MS_PER_DAY);
  if (dayDiff <= 0) {
    return dayDiff === 0 ? "today" : "older_than_30_days";
  }
  if (dayDiff === 1) return "yesterday";
  if (dayDiff >= 2 && dayDiff <= 7) return "last_7_days";
  if (dayDiff >= 8 && dayDiff <= 30) return "last_30_days";
  return "older_than_30_days";
}

function cloneSession(session: SessionSummary): SessionSummary {
  return { ...session };
}

/**
 * Sort a group of sessions newest-updated-first, with invalid timestamps
 * pushed to the end. Mutates the input array in place; callers that
 * need immutability must pre-clone.
 */
function sortByUpdatedDesc(sessions: SessionSummary[]): void {
  sessions.sort((a, b) => {
    const aTime = toDate(a.updated)?.getTime();
    const bTime = toDate(b.updated)?.getTime();
    if (aTime === undefined && bTime === undefined) return 0;
    if (aTime === undefined) return 1;
    if (bTime === undefined) return -1;
    return bTime - aTime;
  });
}

/**
 * Group a non-mutated session list by local-calendar age. Empty groups are
 * omitted; entries are newest-first, with invalid dates last in the fallback.
 */
export function groupSessionsByUpdatedDate(
  sessions: readonly SessionSummary[],
  now: Date | number,
): DateGroup[] {
  const nowDate = toDate(now);
  if (nowDate === null) {
    // An invalid clock value must not throw from the session-list render path.
    const fallback: SessionSummary[] = sessions.map(cloneSession);
    sortByUpdatedDesc(fallback);
    return [
      {
        key: "older_than_30_days",
        label: localizedDateGroupLabel("older_than_30_days"),
        sessions: fallback,
      },
    ];
  }

  const buckets = new Map<DateGroupKey, SessionSummary[]>();
  for (const def of DATE_GROUPS) {
    buckets.set(def.key, []);
  }

  for (const session of sessions) {
    const key = classifyByLocalDayDiff(session.updated, nowDate);
    buckets.get(key)!.push(cloneSession(session));
  }

  const result: DateGroup[] = [];
  for (const def of DATE_GROUPS) {
    const bucket = buckets.get(def.key)!;
    if (bucket.length === 0) continue;
    sortByUpdatedDesc(bucket);
    result.push({
      key: def.key,
      label: localizedDateGroupLabel(def.key),
      sessions: bucket,
    });
  }
  return result;
}

/**
 * Preserve order and return fresh objects so callers may sort or annotate the
 * result without mutating the source list.
 */
export function filterFavoriteSessions(
  sessions: readonly SessionSummary[],
  mode: FavoriteFilterMode,
): SessionSummary[] {
  if (mode === "all") {
    return sessions.map(cloneSession);
  }
  const out: SessionSummary[] = [];
  for (const session of sessions) {
    if (session.is_favorite === true) {
      out.push(cloneSession(session));
    }
  }
  return out;
}
