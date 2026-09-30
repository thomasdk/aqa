import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deletePromptSessionType,
  deleteQuickAction,
  deleteRole,
  getDefaultMaterial,
  getMaterialWithLineNumbers,
  listQuickActions,
  restoreDefaultPromptGlobal,
  restoreDefaultPromptSessionType,
  restoreDefaultQuickAction,
  restoreDefaultRole,
  revealPromptGlobalsDirectory,
  revealPromptSessionTypesDirectory,
  revealRoleSource,
  revealSession,
} from "../api";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("generated API boundary contracts", () => {
  it("loads default material and transforms material through documented responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ material: "Example", material_type: "interview" }))
      .mockResolvedValueOnce(jsonResponse({ material: "1 Example" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getDefaultMaterial()).resolves.toEqual({
      material: "Example",
      material_type: "interview",
    });
    await expect(getMaterialWithLineNumbers("Example")).resolves.toEqual({ material: "1 Example" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/defaults/material", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/material/with-line-numbers",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ material: "Example" }) }),
    );
  });

  it("uses generated Quick Action acknowledgement responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ deleted: "focus" }))
      .mockResolvedValueOnce(jsonResponse({ restored: ["focus"] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteQuickAction("focus")).resolves.toEqual({ deleted: "focus" });
    await expect(restoreDefaultQuickAction("focus")).resolves.toEqual({ restored: ["focus"] });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/quick-actions/focus", { method: "DELETE" });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/quick-actions/focus/restore-default", {
      method: "POST",
    });
  });

  it("loads Quick Actions with authoritative restore availability", async () => {
    const response = {
      actions: [
        {
          id: "debate",
          label: "Debate",
          prompt: "Continue the discussion.",
          is_shipped: true,
          origin: "shipped_default",
        },
      ],
      can_restore_defaults: false,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listQuickActions()).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith("/api/quick-actions", undefined);
  });

  it("uses generated role delete, restore, and reveal acknowledgements", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }))
      .mockResolvedValueOnce(jsonResponse({ restored: ["critical"] }))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deleteRole("critical")).resolves.toEqual({ status: "ok" });
    await expect(restoreDefaultRole("critical")).resolves.toEqual({ restored: ["critical"] });
    await expect(revealRoleSource("critical")).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/prompts/roles/critical", {
      method: "DELETE",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/prompts/roles/critical/restore-default", {
      method: "POST",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/prompts/roles/critical/reveal", {
      method: "POST",
    });
  });

  it("uses generated session-type delete, restore, and reveal acknowledgements", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ deleted: "custom" }))
      .mockResolvedValueOnce(jsonResponse({ restored: ["custom"] }))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(deletePromptSessionType("custom")).resolves.toEqual({ deleted: "custom" });
    await expect(restoreDefaultPromptSessionType("custom")).resolves.toEqual({
      restored: ["custom"],
    });
    await expect(revealPromptSessionTypesDirectory()).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/prompts/session-types/custom", {
      method: "DELETE",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/prompts/session-types/custom/restore-default",
      { method: "POST" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/prompts/session-types/reveal-directory", {
      method: "POST",
    });
  });

  it("uses generated global-prompt restore and reveal acknowledgements", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ restored: ["safety"] }))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(restoreDefaultPromptGlobal("safety")).resolves.toEqual({ restored: ["safety"] });
    await expect(revealPromptGlobalsDirectory()).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/prompts/globals/safety/restore-default", {
      method: "POST",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/prompts/globals/reveal-directory", {
      method: "POST",
    });
  });

  it("uses the generated stored-session reveal acknowledgement", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(revealSession("session/1")).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session%2F1/reveal", { method: "POST" });
  });
});
