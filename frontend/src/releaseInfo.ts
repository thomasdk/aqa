import rawReleaseInfo from "../../release-info.json";

export type ReleaseStatus = "prerelease" | "stable";

export type ReleaseInfo = {
  version: string;
  releaseDate: string | null;
  releaseStatus: ReleaseStatus;
  copyright: string;
  license: string;
  links: {
    universityProject: string;
    githubRepository: string | null;
  };
};

export const releaseInfo = rawReleaseInfo as ReleaseInfo;

export function formatReleaseDate(releaseDate: string, locale: "de-DE" | "en-US"): string {
  const [year, month, day] = releaseDate.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}
