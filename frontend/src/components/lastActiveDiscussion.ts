/**
 * Stores only the opaque id of the discussion the user most recently opened
 * or started. The full session remains server-owned and is never copied into
 * browser storage.
 */
export const LAST_ACTIVE_DISCUSSION_STORAGE_KEY = "aqa.lastActiveDiscussion.v1";

function isCanonicalDiscussionId(value: string | null): value is string {
  return value !== null && value.length > 0 && value === value.trim() && !/[\\/\s]/.test(value);
}

export function readLastActiveDiscussionId(): string | null {
  try {
    const value = window.localStorage.getItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY);
    return isCanonicalDiscussionId(value) ? value : null;
  } catch {
    return null;
  }
}

export function persistLastActiveDiscussionId(fileId: string): void {
  if (!isCanonicalDiscussionId(fileId)) return;
  try {
    window.localStorage.setItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY, fileId);
  } catch {
    // Browser storage is a convenience, never a prerequisite for a discussion.
  }
}

export function clearLastActiveDiscussionId(): void {
  try {
    window.localStorage.removeItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY);
  } catch {
    // Ignore unavailable browser storage; the in-memory UI state is authoritative.
  }
}
