import { describe, expect, it, vi } from "vitest";
import { recoverContextInclusionAfterNotFound } from "./discussionContextInclusionRecovery";
import { ApiError } from "../api";

describe("recoverContextInclusionAfterNotFound", () => {
  it("reopens the known session, refreshes state, and retries a 404 context change", async () => {
    const reopen = vi.fn().mockResolvedValue(undefined);
    const refreshedState = { messages: [{ id: "m1" }] };
    const refresh = vi.fn().mockResolvedValue(refreshedState);
    const retry = vi.fn().mockResolvedValue(undefined);

    const result = await recoverContextInclusionAfterNotFound(
      new ApiError(404, "Message not found", "not_found"),
      "session-123",
      reopen,
      refresh,
      retry,
    );

    expect(result).toBe(refreshedState);
    expect(reopen).toHaveBeenCalledWith("session-123");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledTimes(1);
    expect(reopen.mock.invocationCallOrder[0]).toBeLessThan(refresh.mock.invocationCallOrder[0]);
    expect(refresh.mock.invocationCallOrder[0]).toBeLessThan(retry.mock.invocationCallOrder[0]);
  });

  it("does nothing for non-404 errors or when no session can be reopened", async () => {
    const reopen = vi.fn();
    const refresh = vi.fn();
    const retry = vi.fn();

    await expect(
      recoverContextInclusionAfterNotFound(
        new ApiError(409, "locked", "conflict"),
        "session-123",
        reopen,
        refresh,
        retry,
      ),
    ).resolves.toBeUndefined();
    await expect(
      recoverContextInclusionAfterNotFound(
        new ApiError(404, "missing", "not_found"),
        null,
        reopen,
        refresh,
        retry,
      ),
    ).resolves.toBeUndefined();

    expect(reopen).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
    expect(retry).not.toHaveBeenCalled();
  });
});
