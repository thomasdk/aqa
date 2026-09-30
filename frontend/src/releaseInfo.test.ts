import { describe, expect, it } from "vitest";
import { formatReleaseDate, releaseInfo } from "./releaseInfo";

describe("release information", () => {
  it("provides the shared version, release status, and project-link contract", () => {
    expect(releaseInfo.version).toBe("1.0.0");
    expect(releaseInfo.releaseStatus).toBe("stable");
    expect(releaseInfo.releaseDate).toBe("2026-09-30");
    expect(releaseInfo.links.universityProject).toBe(
      "https://www.sowi.uni-stuttgart.de/abteilungen/ses/forschung/augmented-qualitative-analysis-aqa/",
    );
    expect(releaseInfo.links.githubRepository).toBeNull();
  });

  it("formats an assigned calendar date without build-time or timezone dependence", () => {
    expect(formatReleaseDate("2026-09-30", "en-US")).toBe("September 30, 2026");
    expect(formatReleaseDate("2026-09-30", "de-DE")).toBe("30. September 2026");
  });
});
