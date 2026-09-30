import { beforeEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { formatLocalSessionDateTime, formatSessionRoundLabel } from "./sessionPresentation";

/**
 * Build the same string the production formatter would emit, but computed
 * from a known Date instance. This keeps the assertions timezone-independent:
 * no machine-specific literal, no risk of CI drift.
 */
const expectedGermanLocal = (iso: string): string =>
  new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));

const expectedEnglishLocal = (date: Date): string =>
  new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    hourCycle: "h23",
  }).format(date);

describe("formatLocalSessionDateTime", () => {
  beforeEach(async () => {
    await setLocale("de");
  });

  it("formats a valid ISO timestamp in the local timezone (de-DE)", () => {
    // Choose a UTC instant that is unambiguous; the formatter will render
    // whatever the test machine's local zone is — that's the whole point.
    const iso = "2024-05-12T14:30:00.000Z";
    expect(formatLocalSessionDateTime(iso)).toBe(expectedGermanLocal(iso));
  });

  it("formats a different valid ISO timestamp using the same rules", () => {
    const iso = "2023-01-03T08:15:00.000Z";
    expect(formatLocalSessionDateTime(iso)).toBe(expectedGermanLocal(iso));
  });

  it("uses US date ordering with a 24-hour English clock", async () => {
    await setLocale("en");
    const midnight = new Date(2024, 4, 12, 0, 5);
    try {
      const formatted = formatLocalSessionDateTime(midnight.toISOString());
      expect(formatted).toBe(expectedEnglishLocal(midnight));
      expect(formatted).toContain("00:05");
      expect(formatted).not.toMatch(/\b(?:AM|PM)\b/i);
    } finally {
      await setLocale("de");
    }
  });

  it("accepts an ISO string with a non-UTC offset", () => {
    const iso = "2024-07-04T22:00:00+02:00";
    expect(formatLocalSessionDateTime(iso)).toBe(expectedGermanLocal(iso));
  });

  it("returns 'Unbekannt' for null", () => {
    expect(formatLocalSessionDateTime(null)).toBe("Unbekannt");
  });

  it("returns 'Unbekannt' for undefined", () => {
    expect(formatLocalSessionDateTime(undefined)).toBe("Unbekannt");
  });

  it("returns 'Unbekannt' for the empty string", () => {
    expect(formatLocalSessionDateTime("")).toBe("Unbekannt");
  });

  it("returns 'Unbekannt' for a whitespace-only string", () => {
    expect(formatLocalSessionDateTime("   ")).toBe("Unbekannt");
  });

  it("returns 'Unbekannt' for a completely malformed string", () => {
    expect(formatLocalSessionDateTime("not-a-date")).toBe("Unbekannt");
  });

  it("returns 'Unbekannt' for a string that parses to NaN", () => {
    // new Date("2024-13-99") is not a real date; getTime() is NaN.
    expect(formatLocalSessionDateTime("2024-13-99T99:99:99")).toBe("Unbekannt");
  });

  it("never returns the literal 'Invalid Date'", () => {
    // The UI must never display the raw "Invalid Date" string.
    const inputs: Array<string | null | undefined> = [
      null,
      undefined,
      "",
      "  ",
      "not-a-date",
      "2024-13-99T99:99:99",
      "abc-def-ghi",
    ];
    for (const input of inputs) {
      const out = formatLocalSessionDateTime(input);
      expect(out).toBe("Unbekannt");
      expect(out).not.toBe("Invalid Date");
    }
  });
});

describe("formatSessionRoundLabel", () => {
  it("returns '0 Runden' for zero rounds", () => {
    expect(formatSessionRoundLabel(0)).toBe("0 Runden");
  });

  it("returns '1 Runde' (singular) for exactly one round", () => {
    expect(formatSessionRoundLabel(1)).toBe("1 Runde");
  });

  it("returns 'N Runden' (plural) for any count above one", () => {
    expect(formatSessionRoundLabel(2)).toBe("2 Runden");
    expect(formatSessionRoundLabel(7)).toBe("7 Runden");
    expect(formatSessionRoundLabel(42)).toBe("42 Runden");
  });
});
