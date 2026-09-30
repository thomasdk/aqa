import type {
  BulkDeleteSessionsResult,
  DeleteSessionResult,
  SessionSnapshot,
  SessionSummary,
} from "../components/types";
import { fetchJSON } from "./client";
import type { RevealSessionContract } from "./contracts";

export function listSessions(): Promise<SessionSummary[]> {
  return fetchJSON("/api/sessions");
}

export function openSession(fileId: string): Promise<SessionSnapshot> {
  return fetchJSON(`/api/sessions/${encodeURIComponent(fileId)}/open`, {
    method: "POST",
  });
}

export function renameSession(fileId: string, title: string): Promise<SessionSummary> {
  return fetchJSON(`/api/sessions/${encodeURIComponent(fileId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function setSessionFavorite(fileId: string, isFavorite: boolean): Promise<SessionSummary> {
  return fetchJSON(`/api/sessions/${encodeURIComponent(fileId)}/favorite`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_favorite: isFavorite }),
  });
}

export function revealSession(fileId: string): Promise<RevealSessionContract> {
  return fetchJSON(`/api/sessions/${encodeURIComponent(fileId)}/reveal`, {
    method: "POST",
  });
}

export function deleteSession(fileId: string): Promise<DeleteSessionResult> {
  return fetchJSON(`/api/sessions/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
  });
}

export function bulkDeleteSessions(
  mode: "all" | "except_favorites",
  expectedFileIds: readonly string[],
): Promise<BulkDeleteSessionsResult> {
  return fetchJSON("/api/sessions/bulk-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, expected_file_ids: expectedFileIds }),
  });
}
