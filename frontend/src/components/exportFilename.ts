const MAX_TITLE_SLUG_LENGTH = 36;
const SESSION_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[:-](\d{2})/;
const AUTOMATIC_TITLE_PREFIX = /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+(?:Z\d{4}:\s*)?/i;

function fallbackTimestamp(now: Date): string {
  const part = (value: number) => value.toString().padStart(2, "0");
  return `${now.getFullYear()}-${part(now.getMonth() + 1)}-${part(now.getDate())}_${part(now.getHours())}-${part(now.getMinutes())}`;
}

function sessionTimestamp(fileId: string | null, title: string, now: Date): string {
  const match = fileId?.match(SESSION_TIMESTAMP) ?? title.match(SESSION_TIMESTAMP);
  return match ? `${match[1]}_${match[2]}-${match[3]}` : fallbackTimestamp(now);
}

function titleSlug(title: string): string {
  const words = title
    .replace(AUTOMATIC_TITLE_PREFIX, "")
    .replace(/^\w+\d*:\s*/u, "")
    .replace(/ß/g, "ss")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("en-US")
    .match(/[a-z0-9]+/g);
  if (!words) return "";

  let slug = "";
  for (const word of words) {
    const candidate = slug ? `${slug}-${word}` : word;
    if (candidate.length > MAX_TITLE_SLUG_LENGTH) {
      if (!slug) slug = word.slice(0, MAX_TITLE_SLUG_LENGTH);
      break;
    }
    slug = candidate;
  }
  return slug.replace(/-+$/u, "");
}

export function buildDiscussionExportFilename(
  title: string,
  activeSessionFileId: string | null,
  now = new Date(),
): string {
  const prefix = `${sessionTimestamp(activeSessionFileId, title, now)}_AQA`;
  const slug = titleSlug(title);
  return `${prefix}${slug ? `_${slug}` : ""}.md`;
}
