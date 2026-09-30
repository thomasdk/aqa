import { act, createElement, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import type { SessionSnapshot } from "../../api";
import type { SessionHydrationController } from "./useSessionHydration";
import { useSessionHydration } from "./useSessionHydration";
import type { DiscussionStreamingController } from "./useDiscussionStreaming";
import type { SessionType } from "../types";

const SESSION_TYPES: SessionType[] = [
  {
    key: "exploration",
    label: "Exploration",
    inputs: [
      {
        key: "main_input",
        label: "Research question",
        prompt_heading: "RESEARCH QUESTION",
        required: true,
      },
    ],
  },
  {
    key: "critique",
    label: "Critique",
    inputs: [
      {
        key: "main_input",
        label: "Critique question",
        prompt_heading: "CRITIQUE QUESTION",
        default_text: "Default critique question",
        required: true,
      },
      {
        key: "additional_instructions",
        label: "Focus",
        prompt_heading: "FOCUS",
        default_text: "Default critique focus",
        required: false,
      },
    ],
  },
];

const SNAPSHOT: SessionSnapshot = {
  file_id: "saved-session",
  title: "Saved discussion",
  material: "Saved material",
  initial_question: "Saved question",
  material_context: {
    material_type: "document",
    session_type: "exploration",
    target_language: "English",
    input_values: {
      additional_instructions: "",
      main_input: "Saved question",
      research_material_context: "",
    },
    input_definitions: SESSION_TYPES[0].inputs,
    include_unchanged_research_material_context_in_prompt: true,
  },
  agents: [
    {
      name: "Saved agent",
      client_id: "saved-agent",
      prompt_id: "perspective-a",
      color: "#2563eb",
      temperature: null,
      api_host: "http://host",
      llm_id: "model",
      max_tokens: null,
      enabled: true,
      perspective_number: 1,
    },
  ],
  synthesis: { enabled: true, api_host: "http://host", llm_id: "model", temperature: null },
  sequential_mode: true,
  round_number: 1,
  has_active_discussion: true,
  round_provider_provenance: [],
  messages: [],
};

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  } as Response;
}

function installFetch(
  snapshot = SNAPSHOT,
  defaultMaterial = { material: "", material_type: "document" },
  renameStatus = 200,
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && input === "/api/sessions/saved-session/open") {
        return Promise.resolve(jsonResponse(snapshot));
      }
      if (method === "PATCH" && input === "/api/sessions/saved-session") {
        if (renameStatus >= 400) {
          return Promise.resolve({
            ...jsonResponse({ detail: "rename failed" }),
            ok: false,
            status: renameStatus,
          } as Response);
        }
        return Promise.resolve(
          jsonResponse({ file_id: "saved-session", title: "Renamed discussion" }),
        );
      }
      if (input === "/api/defaults/material") {
        return Promise.resolve(jsonResponse(defaultMaterial));
      }
      if (input.startsWith("/api/discussions/defaults/agents")) {
        const key = new URL(input, "http://localhost").searchParams.get("session_type");
        return Promise.resolve(
          jsonResponse(key === "critique" ? ["perspective-b", "perspective-c"] : ["perspective-a"]),
        );
      }
      if (input === "/api/sessions") return Promise.resolve(jsonResponse([]));
      return Promise.resolve(jsonResponse({}));
    }),
  );
}

function history(model: string, count: number): SessionSnapshot["round_provider_provenance"] {
  return Array.from({ length: count }, (_, index) => ({
    round_number: index + 1,
    providers: [
      {
        kind: "perspective" as const,
        client_id: "synthetic-agent",
        prompt_id: "perspective-a",
        prompt_label: "Perspective A",
        perspective_number: 1,
        temperature: null,
        host_configuration_id: `host-${model}`,
        host_label: `Host ${model}`,
        api_host: `https://${model}.invalid/v1`,
        model_id: model,
      },
    ],
  }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

type Harness = { controller: () => SessionHydrationController; root: Root };

function mountSession(): Harness {
  let current: SessionHydrationController | null = null;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  function TestHarness() {
    const streamingRef = useRef<DiscussionStreamingController | null>({
      clear: vi.fn(),
      hydrateSnapshot: vi.fn(),
      invalidate: vi.fn(),
    } as unknown as DiscussionStreamingController);
    current = useSessionHydration({
      defaultHostSelection: () => ({ api_host: null, llm_id: null }),
      onNavigateToDiscussion: vi.fn(),
      onNavigateToSetup: vi.fn(),
      perspectives: [{ id: "perspective-a", label: "Perspective A" }],
      sessionTypes: SESSION_TYPES,
      setError: vi.fn(),
      setInterpretationError: vi.fn(),
      startupViewWasRestored: false,
      streamingRef,
      t: ((key: string) => key) as unknown as TFunction,
    });
    return null;
  }

  act(() => root.render(createElement(TestHarness)));
  return {
    controller: () => {
      if (!current) throw new Error("Session controller was not rendered");
      return current;
    },
    root,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.removeItem("aqa.lastActiveDiscussion.v1");
  document.body.innerHTML = "";
});

describe("useSessionHydration", () => {
  it("isolates three-round A from a fresh one-round B and restores each saved history", async () => {
    installFetch();
    const baseFetch = fetch;
    const a = {
      ...SNAPSHOT,
      file_id: "A",
      round_number: 3,
      round_provider_provenance: history("model-a", 3),
    };
    const b = {
      ...SNAPSHOT,
      file_id: "B",
      round_number: 1,
      round_provider_provenance: history("model-b", 1),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        if (input === "/api/sessions/A/open") return Promise.resolve(jsonResponse(a));
        if (input === "/api/sessions/B/open") return Promise.resolve(jsonResponse(b));
        if (input === "/api/discussions/provider-provenance")
          return Promise.resolve(jsonResponse(b.round_provider_provenance));
        return baseFetch(input, init);
      }),
    );
    const harness = mountSession();
    await act(async () => {
      await harness.controller().openSavedSession("A");
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-a", 3));
    await act(async () => {
      await harness.controller().startFreshDraft();
    });
    expect(harness.controller().roundProviderProvenance).toEqual([]);
    act(() => harness.controller().setDiscussionStarted("B", "Discussion B"));
    await act(async () => {
      await harness.controller().refreshProviderProvenance();
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-b", 1));
    await act(async () => {
      await harness.controller().openSavedSession("A");
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-a", 3));
    await act(async () => {
      await harness.controller().openSavedSession("B");
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-b", 1));
    act(() => harness.root.unmount());
  });

  it("ignores delayed history from A after reset, start, or an A-to-B-to-A switch", async () => {
    installFetch();
    const baseFetch = fetch;
    const pending = [deferred<Response>(), deferred<Response>()];
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        if (input === "/api/discussions/provider-provenance")
          return pending[historyCalls++].promise;
        return baseFetch(input, init);
      }),
    );
    const harness = mountSession();
    act(() => harness.controller().setDiscussionStarted("A", "Discussion A"));
    let staleAfterReset!: Promise<void>;
    act(() => {
      staleAfterReset = harness.controller().refreshProviderProvenance();
    });
    await act(async () => {
      await harness.controller().startFreshDraft();
    });
    act(() => harness.controller().setDiscussionStarted("B", "Discussion B"));
    pending[0].resolve(jsonResponse(history("model-a", 3)));
    await act(async () => {
      await staleAfterReset;
    });
    expect(harness.controller().roundProviderProvenance).toEqual([]);

    let staleAfterSwitch!: Promise<void>;
    act(() => {
      staleAfterSwitch = harness.controller().refreshProviderProvenance();
    });
    act(() => {
      harness.controller().setDiscussionStarted("A", "Discussion A");
      harness.controller().setDiscussionStarted("B", "Discussion B");
    });
    pending[1].resolve(jsonResponse(history("wrong-b", 3)));
    await act(async () => {
      await staleAfterSwitch;
    });
    expect(harness.controller().roundProviderProvenance).toEqual([]);
    act(() => harness.root.unmount());
  });

  it("keeps the newest same-discussion history when refreshes resolve out of order", async () => {
    installFetch();
    const baseFetch = fetch;
    const older = deferred<Response>();
    const newer = deferred<Response>();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        if (input === "/api/discussions/provider-provenance")
          return (calls++ === 0 ? older : newer).promise;
        return baseFetch(input, init);
      }),
    );
    const harness = mountSession();
    act(() => harness.controller().setDiscussionStarted("B", "Discussion B"));
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = harness.controller().refreshProviderProvenance();
      second = harness.controller().refreshProviderProvenance();
    });
    newer.resolve(jsonResponse(history("model-b", 1)));
    await act(async () => {
      await second;
    });
    older.resolve(jsonResponse(history("obsolete-b", 3)));
    await act(async () => {
      await first;
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-b", 1));
    act(() => harness.root.unmount());
  });

  it("does not retain A's rows when a new stream fails before receiving a session ID", async () => {
    installFetch({ ...SNAPSHOT, round_provider_provenance: history("model-a", 3) });
    const harness = mountSession();
    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    expect(harness.controller().roundProviderProvenance).toHaveLength(3);
    act(() => harness.controller().setDiscussionStarted(null, ""));
    expect(harness.controller().roundProviderProvenance).toEqual([]);
    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-a", 3));
    act(() => harness.root.unmount());
  });

  it("ignores an older saved-session response after opening another discussion", async () => {
    installFetch();
    const baseFetch = fetch;
    const delayedA = deferred<Response>();
    const opened: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        if (input === "/api/sessions/A/open") {
          opened.push("A");
          return delayedA.promise;
        }
        if (input === "/api/sessions/B/open") {
          opened.push("B");
          return Promise.resolve(
            jsonResponse({
              ...SNAPSHOT,
              file_id: "B",
              round_provider_provenance: history("model-b", 1),
            }),
          );
        }
        return baseFetch(input, init);
      }),
    );
    const harness = mountSession();
    let openA!: Promise<void>;
    act(() => {
      openA = harness.controller().openSavedSession("A");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(opened).toEqual(["A"]);
    let openB!: Promise<void>;
    act(() => {
      openB = harness.controller().openSavedSession("B");
    });
    expect(opened).toEqual(["A"]);
    delayedA.resolve(
      jsonResponse({
        ...SNAPSHOT,
        file_id: "A",
        round_provider_provenance: history("model-a", 3),
      }),
    );
    await act(async () => {
      await Promise.all([openA, openB]);
    });
    expect(opened).toEqual(["A", "B"]);
    expect(harness.controller().activeSessionFileId).toBe("B");
    expect(harness.controller().roundProviderProvenance).toEqual(history("model-b", 1));
    act(() => harness.root.unmount());
  });
  it("caches the canonical default material for restoration without replacing saved state", async () => {
    installFetch(
      {
        ...SNAPSHOT,
        material_context: { ...SNAPSHOT.material_context, material_type: "interview" },
      },
      { material: "Canonical sample", material_type: "document" },
    );
    const harness = mountSession();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(harness.controller().defaultMaterial).toBe("Canonical sample");
    expect(harness.controller().defaultMaterialType).toBe("document");
    expect(harness.controller().material).toBe("Canonical sample");
    expect(harness.controller().materialType).toBe("document");

    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    expect(harness.controller().defaultMaterial).toBe("Canonical sample");
    expect(harness.controller().defaultMaterialType).toBe("document");
    expect(harness.controller().material).toBe("Saved material");
    expect(harness.controller().materialType).toBe("interview");
    act(() => harness.root.unmount());
  });

  it("exposes a failed title save until the user edits or cancels it", async () => {
    installFetch(SNAPSHOT, { material: "Canonical sample", material_type: "document" }, 500);
    const harness = mountSession();
    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    act(() => harness.controller().beginDiscussionTitleEdit(false));
    act(() => harness.controller().updateDiscussionTitleDraft("Unsaved title"));
    await act(async () => {
      await harness.controller().saveDiscussionTitle();
    });
    expect(harness.controller().discussionTitleSaveFailed).toBe(true);
    expect(harness.controller().isEditingDiscussionTitle).toBe(true);

    act(() => harness.controller().updateDiscussionTitleDraft("Retry title"));
    expect(harness.controller().discussionTitleSaveFailed).toBe(false);
    act(() => harness.controller().cancelDiscussionTitleEdit());
    expect(harness.controller().discussionTitleSaveFailed).toBe(false);
    act(() => harness.root.unmount());
  });

  it("returns a typed focus target for the first missing required setup input", () => {
    installFetch();
    const harness = mountSession();

    expect(harness.controller().validateStart()).toEqual({ kind: "material" });

    act(() => harness.controller().updateMaterial("Material"));
    expect(harness.controller().validateStart()).toEqual({ kind: "target-language" });

    act(() => harness.controller().updateTargetLanguage("English"));
    expect(harness.controller().validateStart()).toEqual({
      kind: "session-input",
      key: "main_input",
    });

    act(() => harness.controller().updateSessionInputValue("main_input", "Question"));
    expect(harness.controller().validateStart()).toBeNull();
    act(() => harness.root.unmount());
  });

  it("does not let draft catalogue commands overwrite an authoritative saved snapshot", async () => {
    installFetch();
    const harness = mountSession();

    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    expect(harness.controller().agents[0]?.name).toBe("Saved agent");

    act(() => {
      harness.controller().updateDraftAgents([]);
      harness.controller().updateDraftSynthesis((previous) => ({ ...previous, enabled: false }));
    });

    expect(harness.controller().agents).toHaveLength(1);
    expect(harness.controller().synthesis.enabled).toBe(true);
    act(() => harness.root.unmount());
  });

  it("restores sequential answers for a fresh discussion draft", async () => {
    installFetch();
    const harness = mountSession();

    act(() => harness.controller().selectSequentialMode(false));
    expect(harness.controller().sequentialMode).toBe(false);

    await act(async () => {
      await harness.controller().startFreshDraft();
    });

    expect(harness.controller().sequentialMode).toBe(true);
    act(() => harness.root.unmount());
  });

  it("does not replace the last-active pointer while starting a fresh draft", async () => {
    installFetch();
    const harness = mountSession();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    act(() => harness.controller().setDiscussionStarted("saved-session", "Saved discussion"));
    await act(async () => {
      await harness.controller().startFreshDraft();
    });

    expect(window.localStorage.getItem("aqa.lastActiveDiscussion.v1")).toBe("saved-session");
    await act(async () => {
      await harness.controller().handleActiveSessionDeleted(false, ["saved-session"]);
    });
    expect(window.localStorage.getItem("aqa.lastActiveDiscussion.v1")).toBeNull();
    act(() => harness.root.unmount());
  });

  it("switches an editable draft as one session-type boundary", async () => {
    installFetch();
    const harness = mountSession();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    act(() => harness.controller().updateTargetLanguage("English"));
    act(() => harness.controller().selectSessionType("critique"));

    expect(harness.controller().sessionType).toBe("critique");
    expect(harness.controller().currentSessionInputValues).toEqual({
      main_input: "Default critique question",
      additional_instructions: "Default critique focus",
    });
    expect(harness.controller().agents.every((agent) => !agent.enabled)).toBe(true);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(harness.controller().agents.map((agent) => agent.prompt_id)).toEqual([
      "perspective-b",
      "perspective-c",
      null,
    ]);
    act(() => harness.root.unmount());
  });

  it("preserves keyed values when switching away from and back to a session type", () => {
    installFetch();
    const harness = mountSession();

    act(() => harness.controller().selectSessionType("critique"));
    act(() => harness.controller().updateSessionInputValue("main_input", "Edited critique"));
    act(() => harness.controller().selectSessionType("exploration"));

    expect(harness.controller().currentSessionInputValues).toEqual({ main_input: "" });

    act(() => harness.controller().selectSessionType("critique"));
    expect(harness.controller().currentSessionInputValues).toEqual({
      main_input: "Edited critique",
      additional_instructions: "Default critique focus",
    });
    act(() => harness.root.unmount());
  });

  it("keeps an opened history snapshot authoritative when a selector is invoked", async () => {
    installFetch();
    const harness = mountSession();

    await act(async () => {
      await harness.controller().openSavedSession("saved-session");
    });
    act(() => harness.controller().selectSessionType("critique"));

    expect(harness.controller().sessionType).toBe("exploration");
    expect(harness.controller().agents[0]?.name).toBe("Saved agent");
    expect(harness.controller().currentSessionInputValues.main_input).toBe("Saved question");
    act(() => harness.root.unmount());
  });
});
