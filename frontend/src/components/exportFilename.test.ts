// @vitest-environment node

import { describe, expect, it } from "vitest";
import { buildDiscussionExportFilename } from "./exportFilename";

describe("buildDiscussionExportFilename", () => {
  it("puts the stable session timestamp before AQA and a short semantic slug", () => {
    expect(
      buildDiscussionExportFilename(
        "2026-09-04 16:13 Z0001: I1: Und da starten wir mit dem Themenbereich Bauen im Bestand",
        "2026-09-04_16-13_957bd107",
      ),
    ).toBe("2026-09-04_16-13_AQA_und-da-starten-wir-mit-dem.md");
  });

  it("keeps a manually edited title while enforcing the slug length cap", () => {
    const filename = buildDiscussionExportFilename(
      "Äußerst ausführliche qualitative Auswertung des gesamten Interviewmaterials",
      "2026-09-04_16-13_957bd107",
    );
    expect(filename).toBe("2026-09-04_16-13_AQA_ausserst-ausfuhrliche-qualitative.md");
    expect(filename.split("_AQA_")[1].replace(/\.md$/u, "").length).toBeLessThanOrEqual(36);
  });

  it("omits the slug when no meaningful title exists", () => {
    expect(buildDiscussionExportFilename("   ", "session-open", new Date(2026, 8, 4, 9, 7))).toBe(
      "2026-09-04_09-07_AQA.md",
    );
  });
});
