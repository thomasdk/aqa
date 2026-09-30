import { describe, expect, it } from "vitest";
import {
  INITIAL_DISCUSSION_GENERATION,
  beginDiscussionGeneration,
  invalidateDiscussionGeneration,
  isCurrentDiscussionGeneration,
  type DiscussionGeneration,
} from "./discussionGeneration";

describe("discussionGeneration (monotonic token race guards)", () => {
  it("starts with id 0", () => {
    expect(INITIAL_DISCUSSION_GENERATION).toEqual({ id: 0 });
  });

  it("bumps the id on every begin and returns a new object", () => {
    const g1 = beginDiscussionGeneration(INITIAL_DISCUSSION_GENERATION);
    expect(g1.id).toBe(1);
    expect(g1).not.toBe(INITIAL_DISCUSSION_GENERATION);

    const g2 = beginDiscussionGeneration(g1);
    expect(g2.id).toBe(2);
    expect(g2).not.toBe(g1);
  });

  it("accepts its own events and rejects previous generations", () => {
    const previous = beginDiscussionGeneration(INITIAL_DISCUSSION_GENERATION);
    const current = beginDiscussionGeneration(previous);

    expect(isCurrentDiscussionGeneration(current, current.id)).toBe(true);
    expect(isCurrentDiscussionGeneration(current, previous.id)).toBe(false);
  });

  it("invalidates a stopped generation so late errors are rejected", () => {
    const started = beginDiscussionGeneration(INITIAL_DISCUSSION_GENERATION);
    const invalidated = invalidateDiscussionGeneration(started);

    expect(invalidated.id).toBeGreaterThan(started.id);
    expect(isCurrentDiscussionGeneration(invalidated, started.id)).toBe(false);
    expect(invalidated).not.toBe(started);
  });

  it("keeps an old run stale after a replacement begins", () => {
    const oldRun = beginDiscussionGeneration(INITIAL_DISCUSSION_GENERATION);
    const newRun = beginDiscussionGeneration(oldRun);

    expect(isCurrentDiscussionGeneration(newRun, oldRun.id)).toBe(false);
    expect(isCurrentDiscussionGeneration(newRun, newRun.id)).toBe(true);
  });

  it("treats an id from the initial state as stale once begun", () => {
    const current = beginDiscussionGeneration(INITIAL_DISCUSSION_GENERATION);

    expect(isCurrentDiscussionGeneration(current, INITIAL_DISCUSSION_GENERATION.id)).toBe(false);
  });

  it("preserves identity only through immutable updates", () => {
    const prev: DiscussionGeneration = { id: 5 };
    const next = beginDiscussionGeneration(prev);
    expect(prev.id).toBe(5);
    expect(next.id).toBe(6);
  });
});
