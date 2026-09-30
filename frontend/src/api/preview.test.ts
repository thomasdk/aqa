import { afterEach, describe, expect, it, vi } from "vitest";
import { getPromptPreview, listPreviewTemplates } from "./preview";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("prompt preview API", () => {
  it("uses the shared client and encodes preview selections", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ system_prompt: "ok" })));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await getPromptPreview(
      "role/with space",
      true,
      "offene exploration",
      "continuation",
      controller.signal,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/preview/role%2Fwith%20space?multi_agent=true&session_type=offene+exploration&scenario=continuation",
      { signal: controller.signal },
    );
  });

  it("loads template metadata through an abortable request", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify([])));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await listPreviewTemplates(controller.signal);

    expect(fetchMock).toHaveBeenCalledWith("/api/preview/templates", {
      signal: controller.signal,
    });
  });
});
