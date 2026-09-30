import { afterEach, describe, expect, it } from "vitest";
import {
  clearLastActiveDiscussionId,
  LAST_ACTIVE_DISCUSSION_STORAGE_KEY,
  persistLastActiveDiscussionId,
  readLastActiveDiscussionId,
} from "./lastActiveDiscussion";

afterEach(() => {
  window.localStorage.removeItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY);
});

describe("last active discussion storage", () => {
  it("persists only the opaque discussion id", () => {
    persistLastActiveDiscussionId("session-123");

    expect(window.localStorage.getItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY)).toBe("session-123");
    expect(readLastActiveDiscussionId()).toBe("session-123");
    expect(window.localStorage.length).toBeGreaterThan(0);
  });

  it("ignores blank or whitespace-padded ids", () => {
    persistLastActiveDiscussionId("  ");
    persistLastActiveDiscussionId("../deleted");
    expect(readLastActiveDiscussionId()).toBeNull();

    window.localStorage.setItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY, " session-123 ");
    expect(readLastActiveDiscussionId()).toBeNull();
  });

  it("clears the pointer without retaining session data", () => {
    persistLastActiveDiscussionId("session-123");
    clearLastActiveDiscussionId();

    expect(readLastActiveDiscussionId()).toBeNull();
    expect(window.localStorage.getItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY)).toBeNull();
  });
});
