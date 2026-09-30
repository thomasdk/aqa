import { fetchJSON } from "./client";
import type { ApplicationActivityResponseContract } from "./contracts";

export type ApplicationActivityResponse = ApplicationActivityResponseContract;
export type ApplicationActivityEvent = ApplicationActivityResponse["events"][number];
export type ApplicationActivityLevel = ApplicationActivityEvent["level"];

export function getApplicationActivity(
  after: number,
  signal?: AbortSignal,
): Promise<ApplicationActivityResponse> {
  return fetchJSON(`/api/application/activity?after=${after}&limit=200`, { signal });
}
