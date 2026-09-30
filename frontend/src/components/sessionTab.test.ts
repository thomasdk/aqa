import { describe, expect, it, vi } from "vitest";
import {
  DATE_GROUPS,
  MAX_SESSION_TITLE_LENGTH,
  buildDeleteSessionMessage,
  buildSessionMetaLine,
  buildSessionRoundLabel,
  filterFavoriteSessions,
  groupSessionsByUpdatedDate,
  normalizeSessionTitleInput,
  partitionOpenSession,
  shouldPersistTitleEdit,
} from "./sessionTab";
import type { SessionSummary } from "./types";

const SESSION_A: SessionSummary = {
  file_id: "a",
  title: "Alpha",
  created: "2024-01-01T00:00:00.000Z",
  updated: "2024-01-05T00:00:00.000Z",
  round_count: 3,
  session_type: "exploration",
  is_open: true,
  is_favorite: false,
};

const SESSION_B: SessionSummary = {
  file_id: "b",
  title: "Beta",
  created: "2024-01-01T00:00:00.000Z",
  updated: "2024-01-04T00:00:00.000Z",
  round_count: 1,
  session_type: "exploration",
  is_open: false,
  is_favorite: false,
};

const SESSION_C: SessionSummary = {
  file_id: "c",
  title: "Gamma",
  created: "2024-01-01T00:00:00.000Z",
  updated: "2024-01-06T00:00:00.000Z",
  round_count: 0,
  session_type: "exploration",
  is_open: false,
  is_favorite: false,
};

describe("normalizeSessionTitleInput", () => {
  it("returns null for null", () => {
    expect(normalizeSessionTitleInput(null)).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(normalizeSessionTitleInput(undefined)).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(normalizeSessionTitleInput("")).toBeNull();
  });

  it("returns null for a whitespace-only string", () => {
    expect(normalizeSessionTitleInput("   ")).toBeNull();
  });

  it("returns null for tabs and newlines only", () => {
    expect(normalizeSessionTitleInput("\t\n  \n")).toBeNull();
  });

  it("trims surrounding whitespace from a valid title", () => {
    expect(normalizeSessionTitleInput("  Hallo Welt  ")).toBe("Hallo Welt");
  });

  it("collapses internal whitespace runs to a single space", () => {
    expect(normalizeSessionTitleInput("Hallo\n   Welt\tfoo")).toBe("Hallo Welt foo");
  });

  it("truncates overlong titles to MAX_SESSION_TITLE_LENGTH", () => {
    const huge = "x".repeat(MAX_SESSION_TITLE_LENGTH + 50);
    const normalized = normalizeSessionTitleInput(huge);
    expect(normalized).toHaveLength(MAX_SESSION_TITLE_LENGTH);
    expect(normalized).toBe("x".repeat(MAX_SESSION_TITLE_LENGTH));
  });

  it("returns null for a non-string value", () => {
    // cast through unknown to exercise the runtime guard without TS bail-out
    expect(normalizeSessionTitleInput(123 as unknown as string)).toBeNull();
  });
});

describe("shouldPersistTitleEdit", () => {
  it("returns false for null", () => {
    expect(shouldPersistTitleEdit(null, "Anything")).toBe(false);
  });

  it("returns false for an empty string", () => {
    expect(shouldPersistTitleEdit("", "Anything")).toBe(false);
  });

  it("returns false for a whitespace-only string", () => {
    expect(shouldPersistTitleEdit("   ", "Anything")).toBe(false);
  });

  it("returns false when the normalized input equals the current title", () => {
    expect(shouldPersistTitleEdit("  Hallo Welt  ", "Hallo Welt")).toBe(false);
  });

  it("returns true when the normalized input differs from the current title", () => {
    expect(shouldPersistTitleEdit("Neuer Titel", "Alter Titel")).toBe(true);
  });

  it("returns true when the input has internal whitespace to collapse", () => {
    expect(shouldPersistTitleEdit("Hallo\n  Welt", "Hallo Welt foo")).toBe(true);
  });
});

describe("buildSessionRoundLabel", () => {
  it("renders zero rounds as plural (matches 'no rounds')", () => {
    expect(buildSessionRoundLabel(0)).toBe("0 Runden");
  });

  it("renders one round as singular", () => {
    expect(buildSessionRoundLabel(1)).toBe("1 Runde");
  });

  it("renders many rounds as plural", () => {
    expect(buildSessionRoundLabel(2)).toBe("2 Runden");
    expect(buildSessionRoundLabel(99)).toBe("99 Runden");
  });
});

describe("buildDeleteSessionMessage", () => {
  it("mentions the open-discussion warning for an active session", () => {
    const msg = buildDeleteSessionMessage({
      title: "Meine Diskussion",
      is_open: true,
    });
    expect(msg).toContain("Meine Diskussion");
    expect(msg).toContain("laufende Diskussion");
  });

  it("omits the open-discussion warning for an inactive session", () => {
    const msg = buildDeleteSessionMessage({
      title: "Meine Diskussion",
      is_open: false,
    });
    expect(msg).toContain("Meine Diskussion");
    expect(msg).not.toContain("laufende Diskussion");
  });

  it("uses a fallback label when the title is blank", () => {
    const msg = buildDeleteSessionMessage({ title: "   ", is_open: false });
    expect(msg).toContain("diese Sitzung");
  });

  it("uses a fallback label when the title is missing", () => {
    const msg = buildDeleteSessionMessage({
      title: undefined as unknown as string,
      is_open: false,
    });
    expect(msg).toContain("diese Sitzung");
  });
});

describe("partitionOpenSession", () => {
  it("returns null for openSession when no session is open", () => {
    const { openSession, others } = partitionOpenSession([SESSION_B, SESSION_C]);
    expect(openSession).toBeNull();
    // Sorted by `updated` desc: c (2024-01-06) before b (2024-01-04)
    expect(others.map((s) => s.file_id)).toEqual(["c", "b"]);
  });

  it("isolates the open session and lists the rest newest-first", () => {
    const { openSession, others } = partitionOpenSession([SESSION_B, SESSION_A, SESSION_C]);
    expect(openSession?.file_id).toBe("a");
    // Sorted by `updated` desc: c (2024-01-06), b (2024-01-04)
    expect(others.map((s) => s.file_id)).toEqual(["c", "b"]);
  });

  it("handles an empty list without throwing", () => {
    const { openSession, others } = partitionOpenSession([]);
    expect(openSession).toBeNull();
    expect(others).toEqual([]);
  });

  it("keeps only the first open session when multiple claim is_open", () => {
    const second: SessionSummary = { ...SESSION_A, file_id: "a2", is_open: true };
    const { openSession, others } = partitionOpenSession([SESSION_A, second]);
    expect(openSession?.file_id).toBe("a");
    // The second is_open row still appears in others because the contract
    // is "at most one is_open" but defensive code must not lose data.
    expect(others.find((s) => s.file_id === "a2")).toBeDefined();
  });
});

describe("buildSessionMetaLine", () => {
  it("joins the formatted date and round label with a separator", () => {
    const fakeFormat = (v: string | null | undefined) => (v ? "01.01.2024" : "Unbekannt");
    const line = buildSessionMetaLine("2024-01-01T00:00:00.000Z", 3, fakeFormat);
    expect(line).toBe("01.01.2024 · 3 Runden");
  });

  it("renders '1 Runde' for a single round", () => {
    const fakeFormat = (v: string | null | undefined) => (v ? "01.01.2024" : "Unbekannt");
    expect(buildSessionMetaLine("2024-01-01T00:00:00.000Z", 1, fakeFormat)).toBe(
      "01.01.2024 · 1 Runde",
    );
  });

  it("calls the date formatter even when updated is null", () => {
    const formatDate = vi.fn(() => "Unbekannt");
    buildSessionMetaLine(null, 0, formatDate);
    expect(formatDate).toHaveBeenCalledWith(null);
  });
});

// Fixtures use local-time ISO strings (no `Z` suffix) so calendar-day comparisons
// remain stable in any CI timezone.

const FIXED_NOW = new Date(2024, 5, 10, 12, 0, 0); // 2024-06-10 12:00 local

function localIso(year: number, month: number, day: number, hour = 12): string {
  // month is 0-indexed to match Date constructor semantics
  const d = new Date(year, month, day, hour, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.` +
    `${String(d.getMilliseconds()).padStart(3, "0")}`
  );
}

function makeSession(
  fileId: string,
  updated: string,
  overrides: Partial<SessionSummary> = {},
): SessionSummary {
  return {
    file_id: fileId,
    title: `Title ${fileId}`,
    created: updated,
    updated,
    round_count: 0,
    session_type: "exploration",
    is_open: false,
    is_favorite: false,
    ...overrides,
  };
}

describe("DATE_GROUPS", () => {
  it("keeps locale-neutral groups in visual date order", () => {
    expect(DATE_GROUPS.map((g) => g.key)).toEqual([
      "today",
      "yesterday",
      "last_7_days",
      "last_30_days",
      "older_than_30_days",
    ]);
  });

  it("uses stable, unique keys for every group", () => {
    const keys = DATE_GROUPS.map((g) => g.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("groupSessionsByUpdatedDate", () => {
  it("classifies a session from the current local day into Heute", () => {
    const sessions = [makeSession("now", localIso(2024, 5, 10, 9))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["today"]);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual(["now"]);
  });

  it("classifies a session from the previous local day into Gestern", () => {
    const sessions = [makeSession("yest", localIso(2024, 5, 9, 23))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["yesterday"]);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual(["yest"]);
  });

  it("classifies a session from 2 calendar days ago into Letzte 7 Tage", () => {
    const sessions = [makeSession("d2", localIso(2024, 5, 8, 8))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["last_7_days"]);
  });

  it("classifies a session from exactly 7 calendar days ago into Letzte 7 Tage", () => {
    const sessions = [makeSession("d7", localIso(2024, 5, 3, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["last_7_days"]);
  });

  it("classifies a session from 8 calendar days ago into Letzte 30 Tage", () => {
    const sessions = [makeSession("d8", localIso(2024, 5, 2, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["last_30_days"]);
  });

  it("classifies a session from exactly 30 calendar days ago into Letzte 30 Tage", () => {
    const sessions = [makeSession("d30", localIso(2024, 4, 11, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["last_30_days"]);
  });

  it("classifies a session from 31 calendar days ago into Älter als 30 Tage", () => {
    const sessions = [makeSession("d31", localIso(2024, 4, 10, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["older_than_30_days"]);
  });

  it("classifies a session several years old into Älter als 30 Tage", () => {
    const sessions = [makeSession("old", localIso(2020, 0, 1, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["older_than_30_days"]);
  });

  it("classifies a future timestamp into Älter als 30 Tage", () => {
    const sessions = [makeSession("future", localIso(2030, 0, 1, 12))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["older_than_30_days"]);
  });

  it("classifies an invalid timestamp into Älter als 30 Tage", () => {
    const sessions = [makeSession("bad", "not-a-date"), makeSession("empty", "")];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["older_than_30_days"]);
    expect(groups[0].sessions.map((s) => s.file_id).sort()).toEqual(["bad", "empty"].sort());
  });

  it("omits empty groups from the result", () => {
    const sessions = [makeSession("now", localIso(2024, 5, 10, 9))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["today"]);
    expect(groups).toHaveLength(1);
  });

  it("returns the groups in the canonical DATE_GROUPS order", () => {
    const sessions = [
      makeSession("d31", localIso(2024, 4, 10, 12)),
      makeSession("yest", localIso(2024, 5, 9, 23)),
      makeSession("now", localIso(2024, 5, 10, 9)),
      makeSession("d8", localIso(2024, 5, 2, 12)),
      makeSession("d2", localIso(2024, 5, 8, 8)),
    ];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual([
      "today",
      "yesterday",
      "last_7_days",
      "last_30_days",
      "older_than_30_days",
    ]);
  });

  it("sorts each group newest-updated-first (local time)", () => {
    const later = makeSession("later", localIso(2024, 5, 10, 17));
    const earlier = makeSession("earlier", localIso(2024, 5, 10, 9));
    const groups = groupSessionsByUpdatedDate([earlier, later], FIXED_NOW);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual(["later", "earlier"]);
  });

  it("places invalid-date sessions last inside the fallback group", () => {
    const valid = makeSession("valid", localIso(2024, 4, 1, 12));
    const bad = makeSession("bad", "not-a-date");
    const groups = groupSessionsByUpdatedDate([bad, valid], FIXED_NOW);
    expect(groups.map((g) => g.key)).toEqual(["older_than_30_days"]);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual(["valid", "bad"]);
  });

  it("places every input session into exactly one group (partition property)", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 12)),
      makeSession("b", localIso(2024, 5, 9, 12)),
      makeSession("c", localIso(2024, 5, 5, 12)),
      makeSession("d", localIso(2024, 4, 25, 12)),
      makeSession("e", localIso(2024, 3, 1, 12)),
      makeSession("f", "not-a-date"),
    ];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    const seen = groups.flatMap((g) => g.sessions.map((s) => s.file_id));
    expect(seen.sort()).toEqual(["a", "b", "c", "d", "e", "f"].sort());
  });

  it("does not prioritize is_open inside a group; it stays a row badge", () => {
    const open = makeSession("open", localIso(2024, 5, 10, 17), {
      is_open: true,
    });
    const closed = makeSession("closed", localIso(2024, 5, 10, 9));
    const groups = groupSessionsByUpdatedDate([closed, open], FIXED_NOW);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual(["open", "closed"]);
  });

  it("interleaves favorite and non-favorite rows strictly by updated", () => {
    const newFav = makeSession("newFav", localIso(2024, 5, 10, 17), {
      is_favorite: true,
    });
    const oldFav = makeSession("oldFav", localIso(2024, 5, 10, 9), {
      is_favorite: true,
    });
    const newNonFav = makeSession("newNonFav", localIso(2024, 5, 10, 14));
    const oldNonFav = makeSession("oldNonFav", localIso(2024, 5, 10, 7));
    const groups = groupSessionsByUpdatedDate([oldNonFav, newFav, oldFav, newNonFav], FIXED_NOW);
    expect(groups[0].sessions.map((s) => s.file_id)).toEqual([
      "newFav",
      "newNonFav",
      "oldFav",
      "oldNonFav",
    ]);
  });

  it("treats a favorite toggle as a no-op for sort/group: only `updated` decides the position", () => {
    // Favorite state does not participate in date grouping or sorting.
    const earlier = makeSession("earlier", localIso(2024, 5, 10, 9));
    const later = makeSession("later", localIso(2024, 5, 10, 17));
    const before = groupSessionsByUpdatedDate(
      [
        { ...earlier, is_favorite: false },
        { ...later, is_favorite: true },
      ],
      FIXED_NOW,
    );
    const after = groupSessionsByUpdatedDate(
      [
        { ...earlier, is_favorite: true },
        { ...later, is_favorite: false },
      ],
      FIXED_NOW,
    );
    const ids = (g: typeof before) => g.flatMap((x) => x.sessions.map((s) => s.file_id));
    const keys = (g: typeof before) => g.map((x) => x.key);
    expect(keys(before)).toEqual(keys(after));
    expect(ids(before)).toEqual(ids(after));
    // The exact order is the recency order: later, earlier.
    expect(ids(before)).toEqual(["later", "earlier"]);
  });

  it("leaves `updated` untouched when only is_favorite changes between two calls", () => {
    // Pure data check: changing ONLY is_favorite must not change `updated`.
    // This pins the contract that grouping depends solely on `updated` and
    // that a favorite toggle cannot accidentally bubble into a timestamp
    // bump at the type/contract boundary that the helper consumes.
    const a = makeSession("a", localIso(2024, 5, 10, 17), { is_favorite: false });
    const b = makeSession("b", localIso(2024, 5, 10, 9), { is_favorite: true });
    const toggledA = { ...a, is_favorite: true };
    const toggledB = { ...b, is_favorite: false };
    expect(toggledA.updated).toBe(a.updated);
    expect(toggledB.updated).toBe(b.updated);
    const before = groupSessionsByUpdatedDate([a, b], FIXED_NOW);
    const after = groupSessionsByUpdatedDate([toggledA, toggledB], FIXED_NOW);
    expect(after[0].sessions.map((s) => s.file_id)).toEqual(
      before[0].sessions.map((s) => s.file_id),
    );
  });

  it("does not mutate the input array or its sessions", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9)),
      makeSession("b", localIso(2024, 5, 8, 9)),
    ];
    const snapshot = JSON.parse(JSON.stringify(sessions));
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW);
    expect(sessions).toEqual(snapshot);
    // Output must not share references with the input — consumers may keep
    // both lists around (e.g. for an unfiltered "all" view).
    expect(groups[0].sessions[0]).not.toBe(sessions[0]);
  });

  it("accepts a timestamp number as well as a Date for `now`", () => {
    const sessions = [makeSession("now", localIso(2024, 5, 10, 9))];
    const groups = groupSessionsByUpdatedDate(sessions, FIXED_NOW.getTime());
    expect(groups.map((g) => g.key)).toEqual(["today"]);
  });

  it("returns an empty array for an empty input", () => {
    expect(groupSessionsByUpdatedDate([], FIXED_NOW)).toEqual([]);
  });
});

describe("filterFavoriteSessions", () => {
  it("returns every session in 'all' mode", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9), { is_favorite: false }),
      makeSession("b", localIso(2024, 5, 9, 9), { is_favorite: true }),
      makeSession("c", localIso(2024, 5, 8, 9), { is_favorite: false }),
    ];
    const filtered = filterFavoriteSessions(sessions, "all");
    expect(filtered.map((s) => s.file_id)).toEqual(["a", "b", "c"]);
  });

  it("returns only favorites in 'favorites' mode", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9), { is_favorite: false }),
      makeSession("b", localIso(2024, 5, 9, 9), { is_favorite: true }),
      makeSession("c", localIso(2024, 5, 8, 9), { is_favorite: false }),
      makeSession("d", localIso(2024, 5, 7, 9), { is_favorite: true }),
    ];
    const filtered = filterFavoriteSessions(sessions, "favorites");
    expect(filtered.map((s) => s.file_id)).toEqual(["b", "d"]);
  });

  it("returns an empty array for 'favorites' when nothing is favorited", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9), { is_favorite: false }),
      makeSession("b", localIso(2024, 5, 9, 9), { is_favorite: false }),
    ];
    expect(filterFavoriteSessions(sessions, "favorites")).toEqual([]);
  });

  it("returns an empty array for empty input in either mode", () => {
    expect(filterFavoriteSessions([], "all")).toEqual([]);
    expect(filterFavoriteSessions([], "favorites")).toEqual([]);
  });

  it("does not mutate the input array or its sessions", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9), { is_favorite: true }),
      makeSession("b", localIso(2024, 5, 9, 9), { is_favorite: false }),
    ];
    const snapshot = JSON.parse(JSON.stringify(sessions));
    const filtered = filterFavoriteSessions(sessions, "favorites");
    expect(sessions).toEqual(snapshot);
    expect(filtered[0]).not.toBe(sessions[0]);
  });

  it("preserves the original ordering of the input list", () => {
    const sessions = [
      makeSession("a", localIso(2024, 5, 10, 9), { is_favorite: true }),
      makeSession("b", localIso(2024, 5, 9, 9), { is_favorite: false }),
      makeSession("c", localIso(2024, 5, 8, 9), { is_favorite: true }),
      makeSession("d", localIso(2024, 5, 7, 9), { is_favorite: true }),
    ];
    expect(filterFavoriteSessions(sessions, "favorites").map((s) => s.file_id)).toEqual([
      "a",
      "c",
      "d",
    ]);
  });
});
