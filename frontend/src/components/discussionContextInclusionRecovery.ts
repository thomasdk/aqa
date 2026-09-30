import { ApiError } from "../api";

export function isNotFoundApiError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "not_found";
}

/**
 * Recover a message-context mutation after the backend has forgotten its
 * in-memory active session (for example after a server restart). The browser
 * still knows the safe session file id, so reopen it before reading fresh
 * state and retrying the original idempotent boolean update exactly once.
 */
export async function recoverContextInclusionAfterNotFound<T>(
  error: unknown,
  sessionFileId: string | null,
  reopenSession: (fileId: string) => Promise<unknown>,
  refreshState: () => Promise<T>,
  retryMutation: () => Promise<void>,
): Promise<T | undefined> {
  if (!sessionFileId || !isNotFoundApiError(error)) return undefined;

  await reopenSession(sessionFileId);
  const refreshedState = await refreshState();
  await retryMutation();
  return refreshedState;
}
