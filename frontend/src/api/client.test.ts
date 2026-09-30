import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchJSON } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shared API client", () => {
  it("preserves the structured FastAPI error contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "Local AI is not running",
            error: { code: "local_ai_not_running", params: { model: "gemma" } },
          }),
          { status: 409 },
        ),
      ),
    );

    await expect(fetchJSON("/api/example")).rejects.toEqual(
      new ApiError(409, "Local AI is not running", "local_ai_not_running", {
        model: "gemma",
      }),
    );
  });

  it("forwards AbortSignal to fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await fetchJSON("/api/example", { signal: controller.signal });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/example",
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("does not expose arbitrary non-JSON error bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>private path</html>", { status: 500 })),
    );

    await expect(fetchJSON("/api/example")).rejects.toMatchObject({
      status: 500,
      detail: "Request failed",
      code: null,
    });
  });
});
