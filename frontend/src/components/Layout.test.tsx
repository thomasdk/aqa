// Startup hydration tests exercise the real Layout wiring.

import { describe, expect, it, vi, afterEach, beforeEach, type MockInstance } from "vitest";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import Layout, {
  areRequiredSetupInputsValid,
  effectiveSequentialMode,
  isCurrentHostModelSelection,
  isSequentialModeAvailable,
  preserveExplicitHostModelSelections,
  renderNumberedMaterialLines,
  sessionInputErrorDescriptionId,
  contextEstimateBlocksStart,
  newDiscussionDisposition,
} from "./Layout";
import { setLocale } from "../i18n";
import { de, en } from "../locales";
import { releaseInfo } from "../releaseInfo";
import {
  initializeRoundNotifications,
  resetRoundNotificationsForTests,
  ROUND_NOTIFICATIONS_STORAGE_KEY,
} from "../roundNotifications";
import type {
  SessionSnapshot,
  SessionSummary,
  HostInfo,
  Perspective,
  SessionType,
  SessionInputDefinition,
  AgentConfig,
} from "./types";

const ACTIVE_VIEW_STORAGE_KEY = "aqa.activeView.v1";

describe("Layout AI source defaults", () => {
  it("associates a session-input error only with the field it identifies", () => {
    expect(sessionInputErrorDescriptionId("Required", "question", "question")).toBe(
      "setup-session-input-error",
    );
    expect(sessionInputErrorDescriptionId("Required", "question", "context")).toBeUndefined();
    expect(sessionInputErrorDescriptionId(null, "question", "question")).toBeUndefined();
  });

  it("matches a configured provider by stable label as well as URL and model", () => {
    const hosts = [
      {
        configuration_id: "A",
        label: "A",
        url: "https://shared/v1",
        model: "m",
        models: ["m"],
      },
      {
        configuration_id: "B",
        label: "B",
        url: "https://shared/v1",
        model: "m",
        models: ["m"],
      },
    ];
    expect(
      isCurrentHostModelSelection(
        {
          host_configuration_id: "A",
          host_label: "A",
          api_host: "https://shared/v1",
          llm_id: "m",
        },
        hosts,
      ),
    ).toBe(true);
    expect(
      isCurrentHostModelSelection(
        {
          host_configuration_id: "Deleted",
          host_label: "Deleted",
          api_host: "https://shared/v1",
          llm_id: "m",
        },
        hosts,
      ),
    ).toBe(false);
  });

  it("ships concise English and German deletion and Activity recovery explanations", () => {
    for (const locale of [de, en]) {
      expect(locale.network.deleteWarningSummary).toBeTruthy();
      expect(locale.activity.providerRecoveryGuidance).toBeTruthy();
    }
    expect(de.activity.providerRecoveryGuidance).toContain("Aktivität");
    expect(de.network.deleteWarningSummary).toContain("„Aktivität“ > „Optionen“");
    expect(de.network.deleteWarningSummary).toContain("bestehenden Diskussionen");
    expect(de.network.deleteWarningSummary).toContain("bisherige Verläufe und Anbieterangaben");
    expect(de.network.deleteWarningSummary).not.toMatch(/\b(?:binden|gebunden)\b/i);
  });

  it("fills unset and previous-default slots while preserving explicit host-model overrides", () => {
    const previousDefault = { api_host: "http://old", llm_id: "old-model" };
    const nextDefault = { api_host: "http://new", llm_id: "new-model" };
    const selections = [
      { api_host: "http://old", llm_id: "old-model", name: "default" },
      { api_host: null, llm_id: null, name: "unset" },
      { api_host: "http://custom", llm_id: "manual-model", name: "explicit" },
    ];

    expect(preserveExplicitHostModelSelections(selections, previousDefault, nextDefault)).toEqual([
      { api_host: "http://new", llm_id: "new-model", name: "default" },
      { api_host: "http://new", llm_id: "new-model", name: "unset" },
      { api_host: "http://custom", llm_id: "manual-model", name: "explicit" },
    ]);
    expect(
      preserveExplicitHostModelSelections(
        [{ api_host: "http://old", llm_id: "old-model", name: "explicit-old" }],
        previousDefault,
        nextDefault,
        new Set([0]),
      ),
    ).toEqual([{ api_host: "http://old", llm_id: "old-model", name: "explicit-old" }]);
  });
});

describe("context budget start guard", () => {
  const estimate = {
    known: true,
    estimated_input_tokens: 10,
    available_input_tokens: 10,
    context_window_tokens: 4106,
    reserved_output_tokens: 4096,
    overflow: false,
  } as const;

  it("allows equality and blocks only definite known overflow", () => {
    expect(contextEstimateBlocksStart(estimate)).toBe(false);
    expect(contextEstimateBlocksStart({ ...estimate, overflow: true })).toBe(true);
    expect(contextEstimateBlocksStart({ ...estimate, known: false, overflow: true })).toBe(false);
    expect(contextEstimateBlocksStart(null)).toBe(false);
  });
});

describe("Prepare validity and discussion mode contracts", () => {
  it("starts a new draft directly after autosave and confirms only real interruption or loss", () => {
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: false,
        isStreaming: false,
        isSavingTitle: false,
        titleSaveFailed: false,
        hasUnsavedTitle: false,
        hasUnsavedSetupDraft: false,
      }),
    ).toBe("start");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: false,
        isStreaming: true,
        isSavingTitle: false,
        titleSaveFailed: false,
        hasUnsavedTitle: false,
        hasUnsavedSetupDraft: false,
      }),
    ).toBe("confirm");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: false,
        isStreaming: false,
        isSavingTitle: false,
        titleSaveFailed: false,
        hasUnsavedTitle: true,
        hasUnsavedSetupDraft: false,
      }),
    ).toBe("confirm");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: true,
        isStreaming: false,
        isSavingTitle: true,
        titleSaveFailed: false,
        hasUnsavedTitle: true,
        hasUnsavedSetupDraft: true,
      }),
    ).toBe("wait-save");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: false,
        isStreaming: false,
        isSavingTitle: false,
        titleSaveFailed: false,
        hasUnsavedTitle: false,
        hasUnsavedSetupDraft: true,
      }),
    ).toBe("confirm");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: true,
        isStreaming: false,
        isSavingTitle: false,
        titleSaveFailed: false,
        hasUnsavedTitle: false,
        hasUnsavedSetupDraft: false,
      }),
    ).toBe("confirm");
    expect(
      newDiscussionDisposition({
        hasExistingDiscussion: true,
        isStreaming: false,
        isSavingTitle: false,
        titleSaveFailed: true,
        hasUnsavedTitle: true,
        hasUnsavedSetupDraft: false,
      }),
    ).toBe("block-save-failed");
  });

  it("requires trimmed target language and every required session input", () => {
    const requiredInputs: SessionInputDefinition[] = [
      {
        key: "question",
        label: "Question",
        prompt_heading: "QUESTION",
        required: true,
      },
      {
        key: "context",
        label: "Context",
        prompt_heading: "CONTEXT",
        required: true,
      },
    ];

    expect(
      areRequiredSetupInputsValid("Material", " English ", requiredInputs, {
        question: "A question",
        context: "A context",
      }),
    ).toBe(true);
    expect(
      areRequiredSetupInputsValid("Material", "   ", requiredInputs, {
        question: "A question",
        context: "A context",
      }),
    ).toBe(false);
    expect(
      areRequiredSetupInputsValid("Material", "English", requiredInputs, {
        question: "  ",
        context: "A context",
      }),
    ).toBe(false);
    expect(
      areRequiredSetupInputsValid("Material", "English", requiredInputs, {
        question: "A question",
        context: "\t",
      }),
    ).toBe(false);
    expect(
      areRequiredSetupInputsValid(" \n\t", "English", requiredInputs, {
        question: "A question",
        context: "A context",
      }),
    ).toBe(false);
  });

  it("provides an explicit replaceable-example cue in both locales", () => {
    expect(de.setup.materialExample).toContain("Beispielmaterial");
    expect(de.setup.materialExample).toContain("ersetzen");
    expect(en.setup.materialExample).toContain("example material");
    expect(en.setup.materialExample).toContain("Replace");
  });

  it("allows Sequential only with at least two active Perspectives", () => {
    expect(isSequentialModeAvailable(0)).toBe(false);
    expect(isSequentialModeAvailable(1)).toBe(false);
    expect(isSequentialModeAvailable(2)).toBe(true);
    expect(effectiveSequentialMode(true, 1)).toBe(false);
    expect(effectiveSequentialMode(true, 2)).toBe(true);
    expect(effectiveSequentialMode(false, 2)).toBe(false);
  });
});

afterEach(() => {
  window.sessionStorage.removeItem(ACTIVE_VIEW_STORAGE_KEY);
  delete window.__TAURI__;
});

interface QueuedResponse {
  ok: boolean;
  status: number;
  textValue: string;
  jsonValue: unknown;
  deferredKey?: string;
}

interface FetchCall {
  url: string;
  method: string;
  body: unknown;
}

class FetchRouter {
  private routes: Array<{
    method: string;
    matcher: (url: string) => boolean;
    responder: () => QueuedResponse;
  }> = [];
  calls: FetchCall[] = [];
  private inflight = new Map<
    string,
    Array<{
      resolve: (value: Response) => void;
      reject: (err: unknown) => void;
      response: QueuedResponse;
    }>
  >();

  // Register a route. The responder is called per request so it can
  // inspect any dynamic state (e.g. updated host catalogue) and decide
  // what to return.
  route(method: string, matcher: (url: string) => boolean, responder: () => QueuedResponse): void {
    this.routes.push({ method: method.toUpperCase(), matcher, responder });
  }

  // Convenience: a static JSON response for the *next* matching call.
  json(method: string, matcher: (url: string) => boolean, json: unknown, status = 200): void {
    this.route(method, matcher, () => ({
      ok: status >= 200 && status < 300,
      status,
      textValue: JSON.stringify(json),
      jsonValue: json,
    }));
  }

  // Convenience: an endpoint whose response can be resolved on demand
  // by the test (for "delay" / "hold" scenarios).
  deferred(
    method: string,
    matcher: (url: string) => boolean,
  ): {
    fulfill: (json: unknown, status?: number) => void;
  } {
    const key = `${method.toUpperCase()}::${this.routes.length}`;
    const response: QueuedResponse = {
      ok: true,
      status: 200,
      textValue: "",
      jsonValue: undefined,
      deferredKey: key,
    };
    this.inflight.set(key, []);
    this.route(method, matcher, () => response);
    return {
      fulfill: (json: unknown, status = 200) => {
        const entry = this.inflight.get(key)?.shift();
        if (!entry) return;
        entry.response.ok = status >= 200 && status < 300;
        entry.response.status = status;
        entry.response.textValue = JSON.stringify(json);
        entry.response.jsonValue = json;
        entry.resolve(makeResponse(entry.response));
      },
    };
  }

  install(): MockInstance {
    const router = this;
    const fn = vi.fn((input: unknown, init?: RequestInit) => {
      const url = typeof input === "string" ? input : String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      let body: unknown;
      if (typeof init?.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      }
      router.calls.push({ url, method, body });
      for (const route of router.routes) {
        if (route.method === method && route.matcher(url)) {
          const resp = route.responder();
          const deferredKey = resp.deferredKey;
          if (deferredKey !== undefined) {
            return new Promise<Response>((resolve, reject) => {
              const entries = router.inflight.get(deferredKey) ?? [];
              entries.push({ resolve, reject, response: resp });
              router.inflight.set(deferredKey, entries);
            });
          }
          return Promise.resolve(makeResponse(resp));
        }
      }
      if (method === "GET" && url === "/api/discussions/state") {
        return Promise.resolve(
          makeResponse({
            ok: true,
            status: 200,
            textValue: JSON.stringify({ messages: [], round_status: "completed" }),
            jsonValue: { messages: [], round_status: "completed" },
          }),
        );
      }
      if (method === "GET" && url === "/api/discussions/provider-provenance") {
        return Promise.resolve(
          makeResponse({ ok: true, status: 200, textValue: "[]", jsonValue: [] }),
        );
      }
      if (method === "POST" && url === "/api/discussions/context-estimate") {
        const estimate = {
          known: true,
          estimated_input_tokens: 100,
          available_input_tokens: 28_672,
          context_window_tokens: 32_768,
          reserved_output_tokens: 4_096,
          overflow: false,
        };
        return Promise.resolve(
          makeResponse({
            ok: true,
            status: 200,
            textValue: JSON.stringify(estimate),
            jsonValue: estimate,
          }),
        );
      }
      // Default: a benign 200 JSON body so unexpected routes don't
      // throw, but the assertion helpers can still flag the call.
      return Promise.resolve(
        makeResponse({ ok: true, status: 200, textValue: "{}", jsonValue: {} }),
      );
    });
    globalThis.fetch = fn as unknown as typeof fetch;
    return fn;
  }
}

function makeResponse(resp: QueuedResponse): Response {
  const encoded = new TextEncoder().encode(resp.textValue);
  let consumed = false;
  return {
    ok: resp.ok,
    status: resp.status,
    text: () => Promise.resolve(resp.textValue),
    json: () => Promise.resolve(resp.jsonValue),
    blob: () => Promise.resolve(new Blob([resp.textValue])),
    body: {
      getReader: () => ({
        read: async () => {
          if (consumed) return { done: true, value: undefined };
          consumed = true;
          return { done: false, value: encoded };
        },
      }),
    },
  } as unknown as Response;
}

const STANDARD_HOSTS: HostInfo[] = [
  {
    configuration_id: "Lokale KI",
    label: "Integrierte KI",
    url: "http://local",
    model: "local-model",
    models: ["local-model"],
    kind: "local_ai",
    has_api_key: false,
    is_favorite: false,
  },
  {
    configuration_id: "Cloud",
    label: "Cloud",
    url: "http://cloud",
    model: "cloud-model",
    models: ["cloud-model"],
    kind: "openai",
    has_api_key: true,
    is_favorite: true,
  },
];

const STANDARD_PERSPECTIVES: Perspective[] = [
  { id: "p1", label: "Rolle 1" },
  { id: "p2", label: "Rolle 2" },
  { id: "p3", label: "Rolle 3" },
];

const STANDARD_SESSION_TYPES: SessionType[] = [
  {
    key: "exploration",
    label: "Offene Exploration",
    inputs: [
      {
        key: "research_question",
        label: "Fragestellung",
        prompt_heading: "Fragestellung",
        required: false,
      },
    ],
  },
  {
    key: "critique",
    label: "Interpretationsprüfung",
    inputs: [
      {
        key: "research_question",
        label: "Fragestellung",
        prompt_heading: "Fragestellung",
        required: false,
      },
    ],
  },
];

function makeSessionSummary(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    file_id: "session-open",
    title: "Offene Sitzung",
    created: "2026-07-14T10:00:00Z",
    updated: "2026-07-14T11:00:00Z",
    round_count: 2,
    session_type: "exploration",
    is_open: true,
    is_favorite: false,
    ...overrides,
  };
}

function makeRehydratedAgents(): AgentConfig[] {
  return [
    {
      name: "Agent 1",
      client_id: "agent-1",
      prompt_id: "p1",
      color: "#2563eb",
      temperature: null,
      llm_id: "local-model",
      api_host: "http://local",
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 1,
    },
    {
      name: "Agent 2",
      client_id: "agent-2",
      prompt_id: "p2",
      color: "#16a34a",
      temperature: null,
      llm_id: "local-model",
      api_host: "http://local",
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 2,
    },
    {
      name: "Agent 3",
      client_id: "agent-3",
      prompt_id: "p3",
      color: "#dc2626",
      temperature: null,
      llm_id: "local-model",
      api_host: "http://local",
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 3,
    },
  ];
}

function makeCompletedSnapshot(overrides: Partial<SessionSnapshot> = {}): SessionSnapshot {
  return {
    file_id: "session-open",
    title: "Rehydrierte Sitzung",
    material: "Material-A\nMaterial-B\nMaterial-C",
    initial_question: "Initiale Frage",
    material_context: {
      material_type: "interview",
      session_type: "exploration",
      target_language: "Deutsch",
      input_values: { research_question: "Persistente Interpretation der Sitzung" },
      input_definitions: [
        {
          key: "research_question",
          label: "Fragestellung",
          prompt_heading: "Fragestellung",
          required: true,
        },
      ],
      include_unchanged_research_material_context_in_prompt: false,
    },
    agents: makeRehydratedAgents(),
    synthesis: {
      enabled: true,
      api_host: "http://local",
      llm_id: "local-model",
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
      temperature: null,
    },
    sequential_mode: true,
    round_number: 2,
    has_active_discussion: true,
    round_provider_provenance: [],
    messages: [
      {
        id: "u1",
        role: "user",
        content: "Initiale Frage",
        round_number: 1,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: null,
      },
      {
        id: "m1",
        role: "agent",
        content: "Antwort 1",
        round_number: 1,
        agent_name: "Agent 1",
        theory_label: null,
        color: "#2563eb",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-1",
        perspective_number: 1,
      },
      {
        id: "m2",
        role: "agent",
        content: "Antwort 2",
        round_number: 1,
        agent_name: "Agent 2",
        theory_label: null,
        color: "#16a34a",
        agent_index: 1,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-2",
        perspective_number: 2,
      },
      {
        id: "m3",
        role: "agent",
        content: "Antwort 3",
        round_number: 1,
        agent_name: "Agent 3",
        theory_label: null,
        color: "#dc2626",
        agent_index: 2,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-3",
        perspective_number: 3,
      },
      {
        id: "u2",
        role: "user",
        content: "Folgefrage",
        round_number: 2,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: null,
      },
      {
        id: "m1b",
        role: "agent",
        content: "Antwort 1 Runde 2",
        round_number: 2,
        agent_name: "Agent 1",
        theory_label: null,
        color: "#2563eb",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-1",
        perspective_number: 1,
      },
      {
        id: "m2b",
        role: "agent",
        content: "Antwort 2 Runde 2",
        round_number: 2,
        agent_name: "Agent 2",
        theory_label: null,
        color: "#16a34a",
        agent_index: 1,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-2",
        perspective_number: 2,
      },
      {
        id: "m3b",
        role: "agent",
        content: "Antwort 3 Runde 2",
        round_number: 2,
        agent_name: "Agent 3",
        theory_label: null,
        color: "#dc2626",
        agent_index: 2,
        note: "",
        include_in_agent_context: true,
        include_note_in_agent_context: false,
        error: null,
        client_id: "agent-3",
        perspective_number: 3,
      },
    ],
    ...overrides,
  };
}

interface MountHandle {
  container: HTMLDivElement;
  root: Root;
  fetchMock: MockInstance;
}

function mountLayout(router: FetchRouter): MountHandle {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const fetchMock = router.install();
  act(() => root.render(createElement(Layout)));
  return { container, root, fetchMock };
}

async function flushMicrotasks(times = 6): Promise<void> {
  await act(async () => {
    for (let i = 0; i < times; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  });
}

async function settleContextCheck(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await flushMicrotasks(3);
}

function unmountRoot(root: Root): void {
  act(() => {
    root.unmount();
  });
}

function click(element: HTMLElement | undefined | null): void {
  act(() => {
    element?.click();
  });
}

function setInputValue(input: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const prototype =
    input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
  act(() => {
    setter.call(select, value);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function registerStandardMetadata(
  router: FetchRouter,
  localStatus: Record<string, unknown> = {},
  options: {
    deferHosts?: boolean;
    hosts?: HostInfo[] | (() => HostInfo[]);
    sessionTypes?: SessionType[];
    defaultMaterial?: { material: string; material_type: string };
  } = {},
): { hostsCall?: ReturnType<FetchRouter["deferred"]> } {
  const currentLocalStatus = {
    state: "running",
    model_id: "gemma-4-e2b",
    model_name: "Gemma 4 E2B",
    preferred_model_id: "gemma-4-e2b",
    download_bytes: 0,
    download_total: 0,
    import_bytes: 0,
    import_total: 0,
    context_tokens: 32_768,
    mtp_enabled: false,
    mtp_draft_tokens: 4,
    host_ready: true,
    message: null,
    integrity: "verified",
    models: [
      { model_id: "gemma-4-e2b", api_alias: "local-model", installed: true, integrity: "verified" },
    ],
    runtime_installed: false,
    runtime_selection: {
      runtime_profile: null,
      accelerator_label: "CPU",
      engine_name: null,
      decision_basis: "safe CPU fallback",
      runtime_installed: false,
    },
    ...localStatus,
  };
  router.json("GET", (url) => url === "/api/discussions/perspectives", STANDARD_PERSPECTIVES);
  router.json(
    "GET",
    (url) => url === "/api/discussions/session-types",
    options.sessionTypes ?? STANDARD_SESSION_TYPES,
  );
  const hostsCall = options.deferHosts
    ? router.deferred("GET", (url) => url === "/api/hosts")
    : undefined;
  if (!options.deferHosts) {
    router.route(
      "GET",
      (url) => url === "/api/hosts",
      () => {
        const hosts = typeof options.hosts === "function" ? options.hosts() : options.hosts;
        return {
          ok: true,
          status: 200,
          textValue: JSON.stringify(hosts ?? STANDARD_HOSTS),
          jsonValue: hosts ?? STANDARD_HOSTS,
        };
      },
    );
  }
  router.json("GET", (url) => url === "/api/local-ai/status", currentLocalStatus);
  router.json("GET", (url) => url === "/api/quick-actions", {
    actions: [],
    can_restore_defaults: false,
  });
  router.json("GET", (url) => url === "/api/defaults/material", {
    material: options.defaultMaterial?.material ?? "Default-Material",
    material_type: options.defaultMaterial?.material_type ?? "document",
  });
  router.json("GET", (url) => url.startsWith("/api/discussions/defaults/agents"), [
    "p1",
    "p2",
    "p3",
  ]);
  router.json(
    "POST",
    (url) => url === "/api/material/with-line-numbers",
    // Echo back the input material so the test can assert against
    // the snapshot's material; line numbers don't matter for these
    // assertions. The route is a JSON helper, so we register a
    // dynamic responder for it below.
    { material: "" },
  );
  // Override with a dynamic responder that echoes the request body.
  router.route(
    "POST",
    (url) => url === "/api/material/with-line-numbers",
    () => {
      const lastCall = [...router.calls]
        .reverse()
        .find((c) => c.method === "POST" && c.url === "/api/material/with-line-numbers");
      const material = (lastCall?.body as { material?: string } | undefined)?.material ?? "";
      return {
        ok: true,
        status: 200,
        textValue: JSON.stringify({ material }),
        jsonValue: { material },
      };
    },
  );
  return { hostsCall };
}

async function waitForMaterialTokenEstimate(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  await flushMicrotasks(2);
}

function callsTo(
  router: FetchRouter,
  method: string,
  urlPredicate: (url: string) => boolean,
): FetchCall[] {
  return router.calls.filter(
    (call) => call.method === method.toUpperCase() && urlPredicate(call.url),
  );
}

describe("numbered material display", () => {
  it("keeps one fixed citation gutter across naturally wrapped physical lines and blank paragraphs", () => {
    const html = renderToStaticMarkup(
      createElement(
        "div",
        null,
        renderNumberedMaterialLines(
          "Z0001: First complete sentence. Second complete sentence.\n\nZ0002: Next paragraph.",
        ),
      ),
    );

    expect(html).toContain('class="material-numbered-line"');
    expect(html).toContain('class="material-line-number">Z0001</span>');
    expect(html.match(/material-paragraph-break/g) ?? []).toHaveLength(1);
    expect(html).toContain('class="material-paragraph-break"');
    expect(html).toContain('class="material-line-number">Z0002</span>');
  });

  it("preserves raw source line breaks before material has been numbered", () => {
    const html = renderToStaticMarkup(
      createElement("div", null, renderNumberedMaterialLines("First line\n\nSecond paragraph")),
    );

    expect(html).toContain('class="material-raw-text"');
    expect(html).toContain("First line\n\nSecond paragraph");
  });
});

describe("setup AI readiness notice", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("integrates the unavailable-AI notice into AI Access", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router, { state: "stopped", host_ready: false });
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    const notice = container.querySelector(".setup-ai-notice");
    expect(notice?.closest(".ai-readiness")).not.toBeNull();
    expect(notice?.classList.contains("notice-banner--warning")).toBe(true);
    expect(notice?.getAttribute("role")).toBe("alert");
    expect(notice?.querySelector(".material-symbol")?.textContent).toBe("warning");
    expect(notice?.textContent).toContain("Integrierte KI ist noch nicht vollständig konfiguriert");

    unmountRoot(root);
  });

  it("waits for the host catalogue before evaluating the notice on refresh", async () => {
    const router = new FetchRouter();
    const { hostsCall } = registerStandardMetadata(
      router,
      { state: "stopped", host_ready: false },
      { deferHosts: true },
    );
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(4);

    expect(container.querySelector(".setup-ai-notice")).toBeNull();

    hostsCall?.fulfill(STANDARD_HOSTS);
    await flushMicrotasks(8);

    expect(container.querySelector(".setup-ai-notice")?.textContent).toContain(
      "Integrierte KI ist noch nicht vollständig konfiguriert",
    );

    unmountRoot(root);
  });

  it("renders five uniquely ordered Preparation steps and labels the sample material", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    expect(
      Array.from(container.querySelectorAll(".prepare-step-number")).map((node) =>
        node.textContent?.trim(),
      ),
    ).toEqual(["1", "2", "3", "4", "5"]);
    expect(container.querySelectorAll(".prepare-step-number")).toHaveLength(5);
    expect(container.querySelector(".setup-material-example-note")?.textContent).toContain(
      "anfangs vorausgefüllte Text ist Beispielmaterial",
    );
    expect(container.querySelector(".setup-material-example-note")?.textContent).toContain(
      "eigenes Material ersetzen",
    );

    unmountRoot(root);
  });

  it("disables Sequential for one active Perspective and restores it for two", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    click(
      container.querySelector<HTMLButtonElement>(
        "button[aria-controls='setup-discussion-customization']",
      ),
    );
    const perspectiveSelectors = Array.from(
      container.querySelectorAll<HTMLSelectElement>('select[aria-label="Perspektive wählen"]'),
    );
    expect(perspectiveSelectors).toHaveLength(3);
    const initialModeInputs = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[name="discussion-mode"]'),
    );
    expect(initialModeInputs.map((input) => input.value)).toEqual(["sequential", "independent"]);
    expect(initialModeInputs[0].checked).toBe(true);

    for (const selector of perspectiveSelectors.slice(1)) {
      act(() => {
        selector.value = "";
        selector.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    await flushMicrotasks(4);

    const modeInputs = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[name="discussion-mode"]'),
    );
    const sequential = modeInputs.find((input) => input.value === "sequential");
    const independent = modeInputs.find((input) => input.value === "independent");
    expect(modeInputs.map((input) => input.value)).toEqual(["sequential", "independent"]);
    expect(independent?.closest("label")?.textContent).toContain("Unabhängige Antworten");
    expect(sequential?.disabled).toBe(true);
    expect(sequential?.checked).toBe(false);
    expect(sequential?.getAttribute("aria-describedby")).toBe("setup-sequential-help");
    expect(container.textContent).toContain(
      "Sequenzielle Antworten sind ab zwei aktiven Perspektiven verfügbar.",
    );

    act(() => {
      perspectiveSelectors[1].value = "p2";
      perspectiveSelectors[1].dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flushMicrotasks(4);

    expect(sequential?.disabled).toBe(false);
    expect(sequential?.checked).toBe(true);
    expect(independent?.checked).toBe(false);

    act(() => independent?.click());
    act(() => {
      perspectiveSelectors[1].value = "";
      perspectiveSelectors[1].dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flushMicrotasks(2);
    act(() => {
      perspectiveSelectors[1].value = "p2";
      perspectiveSelectors[1].dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flushMicrotasks(2);
    expect(independent?.checked).toBe(true);
    expect(sequential?.checked).toBe(false);

    unmountRoot(root);
  });

  it("marks missing required fields immediately and clears their state only for nonblank values", async () => {
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    const router = new FetchRouter();
    registerStandardMetadata(
      router,
      {},
      {
        sessionTypes: [
          {
            key: "exploration",
            label: "Offene Exploration",
            inputs: [
              {
                key: "research_question",
                label: "Fragestellung",
                prompt_heading: "FRAGESTELLUNG",
                required: true,
              },
            ],
          },
        ],
      },
    );
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const targetLanguage = container.querySelector<HTMLInputElement>("#setup-target-language")!;
    const materialInput = container.querySelector<HTMLTextAreaElement>("#setup-material-input")!;
    expect(materialInput.required).toBe(true);
    expect(materialInput.getAttribute("aria-required")).toBe("true");
    expect(materialInput.classList.contains("setup-required-missing")).toBe(false);
    expect(targetLanguage.classList.contains("setup-required-missing")).toBe(true);
    expect(targetLanguage.getAttribute("aria-invalid")).toBe("true");
    expect(targetLanguage.getAttribute("aria-required")).toBe("true");
    setInputValue(targetLanguage, "   ");
    expect(targetLanguage.classList.contains("setup-required-missing")).toBe(true);
    setInputValue(targetLanguage, "English");
    expect(targetLanguage.classList.contains("setup-required-missing")).toBe(false);
    expect(targetLanguage.getAttribute("aria-invalid")).toBe("false");
    const requiredInput = container.querySelector<HTMLTextAreaElement>(
      "#setup-input-research_question",
    );
    const startButton = container.querySelector<HTMLButtonElement>(".ds-button--primary");
    expect(requiredInput).not.toBeNull();
    expect(requiredInput?.classList.contains("setup-required-missing")).toBe(true);
    expect(requiredInput?.getAttribute("aria-invalid")).toBe("true");
    expect(startButton?.disabled).toBe(true);
    const startHint = container.querySelector("#setup-start-disabled-reason");
    expect(startHint?.getAttribute("role")).toBe("status");
    expect(startHint?.className).toBe("blocked-action-hint");
    expect(startHint?.querySelector(".material-symbol")?.textContent).toBe("help");
    expect(startHint?.textContent).toContain(
      "Fülle alle erforderlichen Felder aus, bevor du startest.",
    );
    expect(startButton?.getAttribute("aria-describedby")).toBe("setup-start-disabled-reason");
    expect(
      startButton!.compareDocumentPosition(startHint!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);

    setInputValue(requiredInput!, "  \n");
    expect(startButton?.disabled).toBe(true);
    expect(requiredInput?.classList.contains("setup-required-missing")).toBe(true);
    setInputValue(requiredInput!, "Eine Fragestellung");
    await settleContextCheck();
    expect(requiredInput?.classList.contains("setup-required-missing")).toBe(false);
    expect(requiredInput?.getAttribute("aria-invalid")).toBe("false");
    expect(startButton?.disabled).toBe(false);
    setInputValue(materialInput, " \n\t");
    expect(materialInput.classList.contains("setup-required-missing")).toBe(true);
    expect(materialInput.getAttribute("aria-invalid")).toBe("true");
    expect(materialInput.getAttribute("aria-describedby")).toBe("setup-material-guidance");
    expect(container.querySelector("#setup-material-error")).toBeNull();
    expect(startButton?.disabled).toBe(true);
    setInputValue(materialInput, "Eigenes Material");
    await settleContextCheck();
    expect(materialInput.classList.contains("setup-required-missing")).toBe(false);
    expect(startButton?.disabled).toBe(false);
    setInputValue(requiredInput!, "");
    expect(requiredInput?.classList.contains("setup-required-missing")).toBe(true);
    expect(requiredInput?.getAttribute("aria-invalid")).toBe("true");
    expect(startButton?.disabled).toBe(true);
    setInputValue(targetLanguage, "");
    expect(targetLanguage.classList.contains("setup-required-missing")).toBe(true);
    expect(targetLanguage.getAttribute("aria-invalid")).toBe("true");

    unmountRoot(root);
    window.localStorage.removeItem("aqa.targetLanguage.v1");
  });

  it("restores edited or blank Material from the fetched canonical default without changing adjacent setup", async () => {
    window.localStorage.setItem("aqa.targetLanguage.v1", "English");
    const router = new FetchRouter();
    registerStandardMetadata(
      router,
      {},
      {
        defaultMaterial: { material: "Canonical sample material", material_type: "document" },
      },
    );
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const material = container.querySelector<HTMLTextAreaElement>("#setup-material-input")!;
    const materialType = container.querySelector<HTMLSelectElement>("#setup-material-type")!;
    const targetLanguage = container.querySelector<HTMLInputElement>("#setup-target-language")!;
    expect(material.value).toBe("Canonical sample material");
    expect(materialType.value).toBe("document");
    expect(targetLanguage.value).toBe("English");
    expect(
      container.querySelector('button[aria-label="Material auf Standard zurücksetzen"]'),
    ).toBeNull();

    setInputValue(material, "Edited material");
    setSelectValue(materialType, "interview");
    const reset = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Material auf Standard zurücksetzen"]',
    );
    expect(reset).not.toBeNull();
    click(reset);
    expect(material.value).toBe("Canonical sample material");
    expect(materialType.value).toBe("document");
    expect(targetLanguage.value).toBe("English");
    expect(material.getAttribute("aria-invalid")).toBe("false");

    setInputValue(material, "  \n");
    expect(material.classList.contains("setup-required-missing")).toBe(true);
    click(
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="Material auf Standard zurücksetzen"]',
      ),
    );
    expect(material.value).toBe("Canonical sample material");
    expect(material.classList.contains("setup-required-missing")).toBe(false);
    expect(
      container.querySelector('button[aria-label="Material auf Standard zurücksetzen"]'),
    ).toBeNull();

    unmountRoot(root);
    window.localStorage.removeItem("aqa.targetLanguage.v1");
  });

  it("marks an initially blank canonical Material default invalid immediately", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(
      router,
      {},
      {
        defaultMaterial: { material: " \n\t", material_type: "document" },
      },
    );
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const material = container.querySelector<HTMLTextAreaElement>("#setup-material-input")!;
    expect(material.classList.contains("setup-required-missing")).toBe(true);
    expect(material.getAttribute("aria-invalid")).toBe("true");
    setInputValue(material, "Temporary material");
    const reset = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Material auf Standard zurücksetzen"]',
    );
    expect(reset).not.toBeNull();
    click(reset);
    expect(material.value).toBe(" \n\t");
    expect(material.getAttribute("aria-invalid")).toBe("true");
    unmountRoot(root);
  });

  it("uses each session's required rules and leaves populated defaults and optional fields unmarked", async () => {
    const router = new FetchRouter();
    const sharedInput = {
      key: "research_question",
      label: "Fragestellung",
      prompt_heading: "FRAGESTELLUNG",
    };
    registerStandardMetadata(
      router,
      {},
      {
        sessionTypes: [
          {
            key: "exploration",
            label: "Offene Exploration",
            inputs: [{ ...sharedInput, required: true, default_text: "Eine Ausgangsfrage" }],
          },
          {
            key: "critique",
            label: "Interpretationsprüfung",
            inputs: [{ ...sharedInput, required: false }],
          },
        ],
      },
    );
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const defaultInput = container.querySelector<HTMLTextAreaElement>(
      "#setup-input-research_question",
    )!;
    expect(defaultInput.value).toBe("Eine Ausgangsfrage");
    expect(defaultInput.classList.contains("setup-required-missing")).toBe(false);
    expect(defaultInput.getAttribute("aria-invalid")).toBe("false");
    setInputValue(defaultInput, "");
    expect(defaultInput.classList.contains("setup-required-missing")).toBe(true);

    const sessionButtons = container.querySelectorAll<HTMLLabelElement>(".session-type-card");
    click(sessionButtons[1]);
    click(
      container.querySelector<HTMLButtonElement>('button[aria-controls="setup-optional-inputs"]'),
    );
    const optionalInput = container.querySelector<HTMLTextAreaElement>(
      "#setup-input-research_question",
    )!;
    expect(optionalInput.value).toBe("");
    expect(optionalInput.classList.contains("setup-required-missing")).toBe(false);
    expect(optionalInput.getAttribute("aria-invalid")).toBe("false");
    expect(optionalInput.getAttribute("aria-required")).toBe("false");
    setInputValue(optionalInput, "   ");
    expect(optionalInput.classList.contains("setup-required-missing")).toBe(false);

    click(sessionButtons[0]);
    const restoredInput = container.querySelector<HTMLTextAreaElement>(
      "#setup-input-research_question",
    )!;
    expect(restoredInput.value).toBe("");
    expect(restoredInput.classList.contains("setup-required-missing")).toBe(true);
    expect(restoredInput.getAttribute("aria-invalid")).toBe("true");
    unmountRoot(root);
  });
});

describe("Layout startup rehydration", () => {
  let unhandledRejections: unknown[] = [];
  let rejectionHandler: ((event: PromiseRejectionEvent) => void) | undefined;
  let consoleErrorSpy: MockInstance | undefined;

  beforeEach(() => {
    // jsdom does not implement confirm() — Layout uses it for "Neue Diskussion".
    if (!window.confirm) {
      window.confirm = () => true;
    }
    window.localStorage.removeItem("aqa.aiSource.v1");
    window.localStorage.removeItem("aqa.lastActiveDiscussion.v1");
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    window.sessionStorage.removeItem(ACTIVE_VIEW_STORAGE_KEY);
    unhandledRejections = [];
    rejectionHandler = (event) => {
      unhandledRejections.push(event.reason);
      event.preventDefault();
    };
    window.addEventListener("unhandledrejection", rejectionHandler);
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(async () => {
    if (rejectionHandler) {
      window.removeEventListener("unhandledrejection", rejectionHandler);
    }
    consoleErrorSpy?.mockRestore();
    vi.restoreAllMocks();
    await setLocale("de");
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    window.localStorage.removeItem("aqa.lastActiveDiscussion.v1");
    window.sessionStorage.removeItem(ACTIVE_VIEW_STORAGE_KEY);
    // Clean up any DOM nodes the tests may have left behind.
    document.body.innerHTML = "";
  });

  it("keeps cold launch on Setup and links the saved-discussion notice to Continue", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const openSummary = makeSessionSummary({ is_open: false });
    router.json("GET", (url) => url === "/api/sessions", [openSummary]);
    const snapshot = makeCompletedSnapshot();
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);
    window.localStorage.setItem("aqa.lastActiveDiscussion.v1", openSummary.file_id);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    // 1. Startup validates the pointer but does not open or expose the session.
    const sessionListIdx = router.calls.findIndex(
      (c) => c.method === "GET" && c.url === "/api/sessions",
    );
    const openIdx = router.calls.findIndex(
      (c) => c.method === "POST" && c.url === "/api/sessions/session-open/open",
    );
    expect(sessionListIdx).toBeGreaterThanOrEqual(0);
    expect(openIdx).toBe(-1);
    expect(container.querySelector('button[aria-current="page"]')?.textContent).toContain(
      "Vorbereiten",
    );
    expect(container.querySelector(".resume-last-discussion")).not.toBeNull();
    expect(container.querySelector(".resume-last-discussion")?.textContent).not.toContain(
      "Rehydrierte Sitzung",
    );
    expect(container.querySelector(".discussion-shell")).toBeNull();

    // 2. The quiet notice routes to the session list without opening anything.
    const resumeButton = container.querySelector(
      ".resume-last-discussion button",
    ) as HTMLButtonElement;
    expect(resumeButton.textContent).toContain("Unter Fortsetzen öffnen");
    act(() => resumeButton.click());
    await flushMicrotasks(4);
    expect(
      callsTo(router, "POST", (url) => url === "/api/sessions/session-open/open"),
    ).toHaveLength(0);
    expect(container.querySelector('button[aria-current="page"]')?.textContent).toContain(
      "Fortsetzen",
    );

    unmountRoot(root);
  });

  it("confirms a clean autosaved session and starts a new draft exactly once", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const openSummary = makeSessionSummary({ is_open: false });
    router.json("GET", (url) => url === "/api/sessions", [openSummary]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.json("POST", (url) => url === "/api/discussions/reset", { status: "ok" });
    window.localStorage.setItem("aqa.lastActiveDiscussion.v1", openSummary.file_id);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    click(container.querySelector<HTMLButtonElement>(".resume-last-discussion button"));
    await flushMicrotasks(4);
    const open = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent === "Öffnen",
    );
    click(open);
    await flushMicrotasks(8);

    const newDiscussion = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.title === "Neue Diskussion",
    );
    expect(newDiscussion).toBeDefined();
    act(() => newDiscussion?.focus());
    click(newDiscussion);
    await flushMicrotasks(2);

    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog?.textContent).toContain("Neue Diskussion starten?");
    expect(dialog?.textContent).toContain(
      "Deine aktuelle Diskussion wird automatisch gespeichert und kann später fortgesetzt werden.",
    );
    expect(document.activeElement?.textContent).toBe("Abbrechen");
    expect(callsTo(router, "POST", (url) => url === "/api/discussions/reset")).toHaveLength(0);

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(newDiscussion);

    click(newDiscussion);
    await flushMicrotasks(2);
    const reopenedDialog = container.querySelector<HTMLElement>('[role="dialog"]');
    click(
      Array.from(reopenedDialog!.querySelectorAll("button")).find(
        (button) => button.textContent === "Abbrechen",
      ),
    );
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(newDiscussion);

    click(newDiscussion);
    const confirm = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((button) => button.textContent === "Neue Diskussion starten");
    expect(confirm).toBeDefined();
    click(confirm);
    click(confirm);
    await flushMicrotasks(8);

    expect(callsTo(router, "POST", (url) => url === "/api/discussions/reset")).toHaveLength(1);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('button[aria-current="page"]')?.textContent).toContain(
      "Vorbereiten",
    );
    expect(document.activeElement?.id).toBe("setup-page-title");

    click(container.querySelector<HTMLButtonElement>('[data-view="sessions"]'));
    await flushMicrotasks(4);
    expect(container.textContent).toContain(openSummary.title);
    unmountRoot(root);
  });

  it("keeps the New Discussion confirmation open when backend reset fails", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const openSummary = makeSessionSummary({ is_open: false });
    router.json("GET", (url) => url === "/api/sessions", [openSummary]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.json(
      "POST",
      (url) => url === "/api/discussions/reset",
      { detail: "reset refused" },
      500,
    );
    window.localStorage.setItem("aqa.lastActiveDiscussion.v1", openSummary.file_id);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    click(container.querySelector<HTMLButtonElement>(".resume-last-discussion button"));
    await flushMicrotasks(4);
    click(
      Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
        (button) => button.textContent === "Öffnen",
      ),
    );
    await flushMicrotasks(8);
    click(
      Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
        (button) => button.title === "Neue Diskussion",
      ),
    );
    click(
      Array.from(container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')).find(
        (button) => button.textContent === "Neue Diskussion starten",
      ),
    );
    await flushMicrotasks(6);

    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector('[role="alert"]')?.textContent).toBeTruthy();
    expect(container.querySelector(".discussion-shell")).not.toBeNull();
    expect(callsTo(router, "POST", (url) => url === "/api/discussions/reset")).toHaveLength(1);
    unmountRoot(root);
  });

  it("clears a malformed or deleted last-discussion pointer without opening it", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    window.localStorage.setItem("aqa.lastActiveDiscussion.v1", "../deleted");

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    expect(window.localStorage.getItem("aqa.lastActiveDiscussion.v1")).toBeNull();
    expect(container.querySelector(".resume-last-discussion")).toBeNull();
    expect(callsTo(router, "POST", (url) => url.endsWith("/open"))).toHaveLength(0);
    unmountRoot(root);
  });

  it("opens inline Activity recovery and saves a valid replacement automatically", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    const removedUrl = "https://removed.example/v1";
    const snapshot = makeCompletedSnapshot({
      agents: makeRehydratedAgents().map((agent) => ({
        ...agent,
        api_host: removedUrl,
        host_configuration_id: "Removed",
        host_label: "Removed",
        llm_id: "removed-model",
      })),
      synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
    });
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);
    router.json("GET", (url) => url === "/api/discussions/provider-provenance", [
      {
        round_number: 1,
        providers: [
          {
            kind: "perspective",
            client_id: "agent-1",
            host_configuration_id: "Removed",
            host_label: "Removed",
            api_host: removedUrl,
            model_id: "removed-model",
          },
        ],
      },
      {
        round_number: 3,
        providers: [
          {
            kind: "perspective",
            client_id: "agent-1",
            host_configuration_id: "Cloud",
            host_label: "Cloud",
            api_host: "http://cloud",
            model_id: "cloud-model",
          },
          {
            kind: "perspective",
            client_id: "agent-2",
            host_configuration_id: "Cloud",
            host_label: "Cloud",
            api_host: "http://cloud",
            model_id: "cloud-model",
          },
        ],
      },
    ]);
    router.route(
      "POST",
      (url) => url === "/api/discussions/continue",
      () => {
        return {
          ok: true,
          status: 200,
          textValue: 'data: {"type":"all_complete"}\n\n',
          jsonValue: {},
        };
      },
    );
    router.json("PUT", (url) => url === "/api/discussions/next-round-configuration", {
      agent_count: 2,
    });

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const followup = container.querySelector<HTMLTextAreaElement>(".followup-area textarea")!;
    setInputValue(followup, "Continue after deletion");
    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(4);
    expect(container.querySelector(".configuration-recovery-guidance")?.textContent).toContain(
      "Aktivität",
    );
    expect(document.activeElement).toBe(
      container.querySelector(".configuration-recovery-guidance"),
    );
    expect(callsTo(router, "POST", (url) => url === "/api/discussions/continue")).toHaveLength(0);
    const replacementHosts = Array.from(
      container.querySelectorAll<HTMLSelectElement>(
        ".activity-inline-config .agent-config-advanced .agent-config-field:first-of-type select",
      ),
    );
    expect(replacementHosts).toHaveLength(3);
    replacementHosts.forEach((select) => setSelectValue(select, "Cloud"));
    await flushMicrotasks(8);
    expect(
      callsTo(router, "PUT", (url) => url === "/api/discussions/next-round-configuration"),
    ).toHaveLength(1);
    expect(container.querySelector(".activity-round-configuration")).toBeNull();
    expect(container.querySelectorAll(".activity-inline-config")).toHaveLength(3);
    expect(followup.value).toBe("Continue after deletion");
    const configurationCall = callsTo(
      router,
      "PUT",
      (url) => url === "/api/discussions/next-round-configuration",
    );
    expect(configurationCall).toHaveLength(1);
    expect((configurationCall[0].body as { agents: AgentConfig[] }).agents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ host_configuration_id: "Cloud", llm_id: "cloud-model" }),
      ]),
    );

    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(8);

    const continuation = router.calls.find(
      (call) => call.method === "POST" && call.url === "/api/discussions/continue",
    );
    expect(continuation?.body).toMatchObject({
      user_input: "Continue after deletion",
      agents: expect.arrayContaining([
        expect.objectContaining({
          api_host: "http://cloud",
          host_configuration_id: "Cloud",
          host_label: "Cloud",
          llm_id: "cloud-model",
        }),
      ]),
    });
    expect(JSON.stringify(continuation?.body)).not.toContain(removedUrl);
    expect(callsTo(router, "PUT", (url) => url === "/api/discussions/synthesis")).toHaveLength(0);
    expect(container.querySelector(".provider-history")?.textContent).toContain("Agent 1");
    expect(container.querySelector(".provider-history")?.textContent).toContain("Agent 2");
    expect(container.querySelector(".provider-history")?.textContent).toContain("Cloud");
    unmountRoot(root);
  });

  it("starts stopped Integrated AI before continuing an Integrated discussion", async () => {
    const router = new FetchRouter();
    const installedStatus = {
      state: "installed",
      host_ready: false,
      model_id: "local-model",
      preferred_model_id: "local-model",
      integrity: "verified",
      runtime_installed: true,
      models: [
        {
          model_id: "local-model",
          api_alias: "local-model",
          installed: true,
          integrity: "verified",
        },
      ],
    };
    let startRequested = false;
    router.route(
      "GET",
      (url) => url === "/api/local-ai/status",
      () => {
        const payload = startRequested
          ? { ...installedStatus, state: "running", host_ready: true }
          : installedStatus;
        return {
          ok: true,
          status: 200,
          textValue: JSON.stringify(payload),
          jsonValue: payload,
        };
      },
    );
    registerStandardMetadata(router, installedStatus);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    const snapshot = makeCompletedSnapshot();
    snapshot.agents[0] = { ...snapshot.agents[0], llm_id: "stale-local-model" };
    snapshot.agents[1] = {
      ...snapshot.agents[1],
      api_host: "http://cloud",
      host_configuration_id: "Cloud",
      host_label: "Cloud",
      llm_id: "cloud-model",
    };
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);
    router.route(
      "POST",
      (url) => url === "/api/local-ai/start",
      () => {
        startRequested = true;
        const payload = {
          state: "starting",
          host_ready: false,
          model_id: "local-model",
          preferred_model_id: "local-model",
          integrity: "verified",
          runtime_installed: true,
          context_tokens: 32_768,
          mtp_enabled: false,
          models: [
            {
              model_id: "local-model",
              api_alias: "local-model",
              installed: true,
              integrity: "verified",
            },
          ],
        };
        return {
          ok: true,
          status: 200,
          textValue: JSON.stringify(payload),
          jsonValue: payload,
        };
      },
    );
    router.json("PUT", (url) => url === "/api/discussions/next-round-configuration", {
      agent_count: 2,
    });

    const { container, root } = mountLayout(router);
    await flushMicrotasks(12);
    setInputValue(
      container.querySelector<HTMLTextAreaElement>(".followup-area textarea")!,
      "Continue safely",
    );
    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(2);
    setSelectValue(
      container.querySelector<HTMLSelectElement>(
        "#activity-perspective-options-agent-1 .agent-config-field:first-of-type select",
      )!,
      "Lokale KI",
    );
    await flushMicrotasks(8);
    expect(
      callsTo(router, "PUT", (url) => url === "/api/discussions/next-round-configuration"),
    ).toHaveLength(1);
    expect(container.querySelector(".activity-round-configuration")).toBeNull();
    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(16);

    const startIndex = router.calls.findIndex(
      (call) => call.method === "POST" && call.url === "/api/local-ai/start",
    );
    const continueIndex = router.calls.findIndex(
      (call) => call.method === "POST" && call.url === "/api/discussions/continue",
    );
    const readyStatusIndex = router.calls.findIndex(
      (call, index) =>
        index > startIndex && call.method === "GET" && call.url === "/api/local-ai/status",
    );
    expect(startIndex).toBeGreaterThanOrEqual(0);
    expect(readyStatusIndex).toBeGreaterThan(startIndex);
    expect(continueIndex).toBeGreaterThan(readyStatusIndex);
    expect(
      router.calls.filter((call) => call.method === "POST" && call.url === "/api/local-ai/start"),
    ).toHaveLength(1);
    expect(
      router.calls.filter(
        (call) => call.method === "POST" && call.url === "/api/discussions/continue",
      ),
    ).toHaveLength(1);
    expect(router.calls[continueIndex]?.body).toMatchObject({
      user_input: "Continue safely",
      agents: expect.arrayContaining([
        expect.objectContaining({ api_host: "http://local", llm_id: "local-model" }),
        expect.objectContaining({ api_host: "http://cloud", llm_id: "cloud-model" }),
      ]),
    });

    unmountRoot(root);
  });

  it("waits for an already-starting Integrated AI service to become ready", async () => {
    const router = new FetchRouter();
    let statusRequest = 0;
    const startingStatus = {
      state: "starting",
      host_ready: false,
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      context_tokens: 32_768,
      mtp_enabled: false,
      models: [
        {
          model_id: "gemma-4-e2b",
          api_alias: "local-model",
          installed: true,
          integrity: "verified",
        },
      ],
    };
    router.route(
      "GET",
      (url) => url === "/api/local-ai/status",
      () => {
        const payload =
          statusRequest++ === 0
            ? startingStatus
            : { ...startingStatus, state: "running", host_ready: true };
        return {
          ok: true,
          status: 200,
          textValue: JSON.stringify(payload),
          jsonValue: payload,
        };
      },
    );
    registerStandardMetadata(router, startingStatus);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(12);
    setInputValue(
      container.querySelector<HTMLTextAreaElement>(".followup-area textarea")!,
      "Wait until ready",
    );
    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(16);

    const statusCalls = router.calls
      .map((call, index) => ({ ...call, index }))
      .filter((call) => call.method === "GET" && call.url === "/api/local-ai/status");
    const continueIndex = router.calls.findIndex(
      (call) => call.method === "POST" && call.url === "/api/discussions/continue",
    );
    expect(statusCalls).toHaveLength(2);
    expect(continueIndex).toBeGreaterThan(statusCalls[1].index);
    expect(
      router.calls.filter((call) => call.method === "POST" && call.url === "/api/local-ai/start"),
    ).toHaveLength(0);

    unmountRoot(root);
  });

  it("retains the follow-up while routing a failed Integrated AI preflight to recovery", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router, {
      state: "installed",
      host_ready: false,
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      models: [
        {
          model_id: "gemma-4-e2b",
          api_alias: "local-model",
          installed: true,
          integrity: "verified",
        },
      ],
    });
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.json(
      "POST",
      (url) => url === "/api/local-ai/start",
      { detail: "bounded diagnostic", error: { code: "startup_failed", params: {} } },
      503,
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(12);
    setInputValue(
      container.querySelector<HTMLTextAreaElement>(".followup-area textarea")!,
      "Keep this follow-up",
    );
    click(container.querySelector<HTMLButtonElement>(".followup-area .ds-button--primary"));
    await flushMicrotasks(8);

    expect(
      container.querySelector('button[data-view="local-ai"]')?.getAttribute("aria-current"),
    ).toBe("page");
    expect(
      router.calls.filter(
        (call) => call.method === "POST" && call.url === "/api/discussions/continue",
      ),
    ).toHaveLength(0);

    click(container.querySelector<HTMLButtonElement>('button[data-view="discussion"]'));
    await flushMicrotasks(2);
    expect(container.querySelector<HTMLTextAreaElement>(".followup-area textarea")?.value).toBe(
      "Keep this follow-up",
    );

    unmountRoot(root);
  });

  it("persists a manually selected segment across a browser-tab remount", async () => {
    const firstRouter = new FetchRouter();
    registerStandardMetadata(firstRouter);
    firstRouter.json("GET", (url) => url === "/api/sessions", []);

    const { container: firstContainer, root: firstRoot } = mountLayout(firstRouter);
    await flushMicrotasks(8);
    click(firstContainer.querySelector<HTMLButtonElement>('button[data-view="sessions"]'));
    await flushMicrotasks(2);
    expect(window.sessionStorage.getItem(ACTIVE_VIEW_STORAGE_KEY)).toBe("sessions");
    unmountRoot(firstRoot);

    const reloadedRouter = new FetchRouter();
    registerStandardMetadata(reloadedRouter);
    reloadedRouter.json("GET", (url) => url === "/api/sessions", []);
    const { container: reloadedContainer, root: reloadedRoot } = mountLayout(reloadedRouter);
    await flushMicrotasks(8);

    expect(
      reloadedContainer.querySelector('button[data-view="sessions"][aria-current="page"]'),
    ).not.toBeNull();
    unmountRoot(reloadedRoot);
  });

  it.each(["local-ai", "sessions", "system"] as const)(
    "hydrates an open session without leaving the restored %s segment",
    async (savedView) => {
      window.sessionStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, savedView);
      const router = new FetchRouter();
      registerStandardMetadata(router);
      router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
      router.json(
        "POST",
        (url) => url === "/api/sessions/session-open/open",
        makeCompletedSnapshot(),
      );

      const { container, root } = mountLayout(router);
      await flushMicrotasks(10);

      const activeView = container.querySelector('button[aria-current="page"]');
      expect(activeView?.getAttribute("data-view")).toBe(savedView);
      expect(callsTo(router, "POST", (url) => url.endsWith("/open"))).toHaveLength(1);
      expect(container.querySelector("section.discussion-shell")).toBeNull();

      click(container.querySelector<HTMLButtonElement>('button[data-view="discussion"]'));
      await flushMicrotasks(2);
      expect(container.querySelector(".discussion-title-text")?.textContent).toContain(
        "Rehydrierte Sitzung",
      );
      unmountRoot(root);
    },
  );

  it("restores a saved Discussion segment together with its open snapshot", async () => {
    window.sessionStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, "discussion");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    expect(
      container.querySelector('button[data-view="discussion"][aria-current="page"]'),
    ).not.toBeNull();
    expect(container.querySelector("section.discussion-shell")).not.toBeNull();
    expect(container.querySelector(".discussion-title-text")?.textContent).toContain(
      "Rehydrierte Sitzung",
    );
    unmountRoot(root);
  });

  it("restores the Independent Answers explanation with a saved independent discussion", async () => {
    window.sessionStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, "discussion");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot({ sequential_mode: false }),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const notice = container.querySelector('.discussion-mode-notice[role="note"]');
    expect(notice?.textContent).toContain("Unabhängige Antworten");
    expect(notice?.textContent).toContain("aktuellen Runde");
    unmountRoot(root);
  });

  it("falls back to the existing open-session recovery for an invalid saved segment", async () => {
    window.sessionStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, "not-a-workbench-view");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    expect(
      container.querySelector('button[data-view="discussion"][aria-current="page"]'),
    ).not.toBeNull();
    expect(callsTo(router, "POST", (url) => url.endsWith("/open"))).toHaveLength(1);
    unmountRoot(root);
  });

  it("keeps the browser target-language preference when an opened session has its own language", async () => {
    window.localStorage.setItem("aqa.targetLanguage.v1", "English");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot({
        material_context: {
          material_type: "interview",
          session_type: "exploration",
          target_language: "Deutsch",
          input_values: { research_question: "Persistente Interpretation der Sitzung" },
          input_definitions: [
            {
              key: "research_question",
              label: "Fragestellung",
              prompt_heading: "Fragestellung",
              required: true,
            },
          ],
          include_unchanged_research_material_context_in_prompt: false,
        },
      }),
    );

    const { root } = mountLayout(router);
    await flushMicrotasks(10);
    expect(window.localStorage.getItem("aqa.targetLanguage.v1")).toBe("English");
    unmountRoot(root);

    // This mount models a fresh browser session, not a reload of the
    // just-opened discussion. The selected segment is intentionally
    // tab-scoped, so clear it before checking the independent preference.
    window.sessionStorage.removeItem(ACTIVE_VIEW_STORAGE_KEY);
    const freshRouter = new FetchRouter();
    registerStandardMetadata(freshRouter);
    freshRouter.json("GET", (url) => url === "/api/sessions", []);
    const { container: freshContainer, root: freshRoot } = mountLayout(freshRouter);
    await flushMicrotasks(8);
    expect(freshContainer.querySelector<HTMLInputElement>("#setup-target-language")?.value).toBe(
      "English",
    );
    unmountRoot(freshRoot);
  });

  it("shows a localized error when saving a note for the discussion context fails", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    const snapshot = makeCompletedSnapshot();
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);
    router.json(
      "POST",
      (url) => url === "/api/discussions/messages/m1b/note",
      { detail: "note persistence failed" },
      500,
    );
    router.json("GET", (url) => url === "/api/discussions/state", {
      material: snapshot.material,
      initial_question: snapshot.initial_question,
      messages: snapshot.messages,
      round_number: snapshot.round_number,
      has_active_discussion: snapshot.has_active_discussion,
    });

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const targetMessage = Array.from(
      container.querySelectorAll(".discussion-message.message-agent"),
    ).find((message) => message.textContent?.includes("Antwort 1 Runde 2"));
    click(targetMessage?.querySelector(".note-add-btn") as HTMLButtonElement);
    const editor = container.querySelector(".note-editor textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(editor, "  Human qualification  ");
    act(() => editor.dispatchEvent(new Event("input", { bubbles: true })));
    const include = container.querySelector(".note-context-checkbox input") as HTMLInputElement;
    act(() => include.click());
    click(container.querySelector(".note-editor .ds-button--secondary") as HTMLButtonElement);
    await flushMicrotasks(8);

    expect(
      router.calls.find(
        (call) => call.method === "POST" && call.url === "/api/discussions/messages/m1b/note",
      )?.body,
    ).toEqual({ note: "Human qualification", include_note_in_agent_context: true });
    expect(container.querySelector(".error-banner")?.textContent).toContain(
      "Die Notiz konnte nicht gespeichert werden.",
    );

    unmountRoot(root);
  });

  it("shows the token estimate for recovered line-numbered material", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("POST", (url) => url === "/api/material/token-estimate", {
      approximate_tokens: 1234,
      tokenizer: "o200k_base",
    });
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot({ material: "Z0001: Erste Zeile\nZ0002: \nZ0003: Dritte" }),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    await waitForMaterialTokenEstimate();

    expect(container.querySelector(".material-panel-title")?.textContent).toContain("Material");
    const tokenEstimate = container.querySelector(".material-token-estimate")?.textContent ?? "";
    expect(tokenEstimate).toContain("~1.234 Tokens");
    expect(tokenEstimate).not.toContain("Zeichen");
    expect(container.querySelector(".material-line-number")?.textContent).toBe("Z0001");
    expect(container.querySelector(".material-line-text")?.textContent).toBe("Erste Zeile");
    expect(callsTo(router, "POST", (url) => url === "/api/material/token-estimate")).toContainEqual(
      {
        method: "POST",
        url: "/api/material/token-estimate",
        body: {
          material: "Z0001: Erste Zeile\nZ0002: \nZ0003: Dritte",
          material_type: "interview",
        },
      },
    );

    unmountRoot(root);
  });

  it("shows token-estimate-unavailable copy instead of a character count", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json(
      "POST",
      (url) => url === "/api/material/token-estimate",
      { detail: "unavailable" },
      503,
    );
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot({ material: "Z0001: Benutzertext\nOhne Präfix" }),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    await waitForMaterialTokenEstimate();

    const tokenEstimate = container.querySelector(".material-token-estimate")?.textContent ?? "";
    expect(tokenEstimate).toContain("Material-Token-Schätzung nicht verfügbar");
    expect(tokenEstimate).not.toContain("Zeichen");

    unmountRoot(root);
  });

  it("exports with the active English locale and English download basename", async () => {
    await setLocale("en");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.download).toMatch(/^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_AQA_rehydrierte-sitzung\.md$/);
      const url = new URL(this.href);
      expect(url.pathname).toBe("/api/discussions/export");
      expect(url.searchParams.get("locale")).toBe("en");
      expect(url.searchParams.get("download_filename")).toBe(this.download);
      expect(this.target).toBe("_blank");
      expect(document.body.contains(this)).toBe(true);
    });

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const exportButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.title === "Export as Markdown",
    );
    click(exportButton);
    await flushMicrotasks(4);

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(container.querySelector("a")).toBeNull();
    unmountRoot(root);
    await setLocale("de");
  });

  it("uses the native save command inside Tauri", async () => {
    await setLocale("en");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.route(
      "GET",
      (url) => url.startsWith("/api/discussions/export?"),
      () => ({
        ok: true,
        status: 200,
        textValue: "# Native Export",
        jsonValue: undefined,
      }),
    );
    const invoke = vi.fn().mockResolvedValue("renamed-discussion.md");
    window.__TAURI__ = { core: { invoke } };
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click");

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const exportButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.title === "Export as Markdown",
    );
    click(exportButton);
    await flushMicrotasks(6);

    expect(invoke).toHaveBeenCalledWith("save_markdown_export", {
      suggestedFilename: expect.stringMatching(
        /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_AQA_rehydrierte-sitzung\.md$/,
      ),
      contents: "# Native Export",
    });
    expect(clickSpy).not.toHaveBeenCalled();
    expect(container.querySelector(".error-banner")).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Saved “renamed-discussion.md”",
    );
    const dismissNotice = container.querySelector<HTMLButtonElement>(
      '.export-notice button[aria-label="Close Notice"]',
    );
    click(dismissNotice);
    expect(container.querySelector(".export-notice")).toBeNull();
    unmountRoot(root);
    await setLocale("de");
  });

  it("treats cancelling the native save dialog as a successful no-op", async () => {
    await setLocale("en");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.route(
      "GET",
      (url) => url.startsWith("/api/discussions/export?"),
      () => ({
        ok: true,
        status: 200,
        textValue: "# Cancelled Export",
        jsonValue: undefined,
      }),
    );
    window.__TAURI__ = { core: { invoke: vi.fn().mockResolvedValue(null) } };

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const exportButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.title === "Export as Markdown",
    );
    click(exportButton);
    await flushMicrotasks(6);

    expect(container.querySelector(".error-banner")).toBeNull();
    expect(container.querySelector(".export-notice")).toBeNull();
    unmountRoot(root);
    await setLocale("de");
  });

  it("shows an error when the native Markdown write fails", async () => {
    await setLocale("en");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );
    router.route(
      "GET",
      (url) => url.startsWith("/api/discussions/export?"),
      () => ({
        ok: true,
        status: 200,
        textValue: "# Failed Export",
        jsonValue: undefined,
      }),
    );
    window.__TAURI__ = {
      core: { invoke: vi.fn().mockRejectedValue(new Error("write failed")) },
    };

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    const exportButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.title === "Export as Markdown",
    );
    click(exportButton);
    await flushMicrotasks(6);

    expect(container.querySelector(".error-banner")?.textContent).toContain("Export failed.");
    unmountRoot(root);
    await setLocale("de");
  });

  it("leaves Setup selected and does not POST open when no session is open", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [
      makeSessionSummary({ file_id: "closed-1", is_open: false }),
    ]);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    // No open request issued.
    const openCalls = callsTo(router, "POST", (url) => url.endsWith("/open"));
    expect(openCalls).toHaveLength(0);

    // Setup view remains the active tab.
    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).toContain("Vorbereiten");
    // The Setup view's material textarea is present.
    expect(container.querySelector(".setup-material-input")).not.toBeNull();
    // No discussion shell rendered.
    expect(container.querySelector("section.discussion-shell")).toBeNull();

    unmountRoot(root);
  });

  it("surfaces the German recovery error and keeps Setup selected when the open endpoint fails", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    // Only a bounded `detail` value may reach the banner.
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      { detail: "Snapshot korrupt" },
      500,
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    // Setup is still the active tab — no partial Discussion view.
    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).toContain("Vorbereiten");
    expect(container.querySelector("section.discussion-shell")).toBeNull();

    // The localized error banner hides the untrusted response detail.
    const banner = container.querySelector(".error-banner");
    expect(banner).not.toBeNull();
    expect(banner?.textContent).toContain("Sitzung konnte nicht geöffnet werden");
    expect(banner?.textContent).not.toContain("Snapshot korrupt");

    unmountRoot(root);
  });

  it("does not overwrite a hydrated snapshot with late default material, collection-context, interpretation or agent defaults", async () => {
    // Goal: the four "default" responses that the metadata effect
    // awaits must finish *after* the snapshot has been applied.  We
    // therefore mount with a stub that delays the defaults
    // indefinitely, resolve the open-session path first (so the
    // snapshot is live), and then release the defaults with values
    // that would overwrite the snapshot if Layout were not guarding
    // against it.  The hydrated snapshot must survive — its
    // material, material type, session type, collection context,
    // procedure instruction, interpretation and roster ``prompt_id``
    // / ``enabled`` flags must not change.
    const router = new FetchRouter();

    // Synchronous non-default metadata so the initial mount effect
    // can settle.  Only the four "default" responses stay deferred.
    router.json("GET", (url) => url === "/api/discussions/perspectives", STANDARD_PERSPECTIVES);
    router.json("GET", (url) => url === "/api/discussions/session-types", STANDARD_SESSION_TYPES);
    router.json("GET", (url) => url === "/api/hosts", STANDARD_HOSTS);
    const defaultMaterial = router.deferred("GET", (url) => url === "/api/defaults/material");
    const defaultCollectionContext = router.deferred(
      "GET",
      (url) => url === "/api/defaults/collection-context",
    );
    const defaultInterpretation = router.deferred("GET", (url) =>
      url.startsWith("/api/discussions/defaults/interpretation"),
    );
    const defaultAgents = router.deferred("GET", (url) =>
      url.startsWith("/api/discussions/defaults/agents"),
    );
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    const snapshot = makeCompletedSnapshot();
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);

    const { container, root } = mountLayout(router);
    // The metadata effect is still awaiting the four deferred
    // defaults, but the startup effect is independent.  The
    // snapshot hydrates and the discussion view is live.
    await flushMicrotasks(10);

    expect(container.querySelector("section.discussion-shell")).not.toBeNull();
    const titleAfterSnapshot = container.querySelector(".discussion-title-text")?.textContent;
    expect(titleAfterSnapshot).toContain("Rehydrierte Sitzung");

    // Now release the late defaults with values that would overwrite
    // the snapshot if Layout were not guarding against it.
    defaultMaterial.fulfill({
      material: "LATE-MATERIAL-SHOULD-NOT-WIN",
      material_type: "fieldnotes",
    });
    defaultCollectionContext.fulfill({ template: "LATE-CONTEXT-SHOULD-NOT-WIN" });
    defaultInterpretation.fulfill({
      text: "LATE-INTERPRETATION-SHOULD-NOT-WIN",
      hint: "",
      description: "late",
      interpretation_required: false,
    });
    defaultAgents.fulfill(["late-role-a", "late-role-b", "late-role-c"]);

    // Let the late responses land and React flush.
    await flushMicrotasks(10);

    // 1. The snapshot's material survives: it is rendered in the
    //    material panel, not the late default.
    const renderedMaterial = container.querySelector("#material-pane-content")?.textContent ?? "";
    expect(renderedMaterial).toContain("Material-A");
    expect(renderedMaterial).not.toContain("LATE-MATERIAL-SHOULD-NOT-WIN");

    // 2. The snapshot's title survives.
    expect(container.querySelector(".discussion-title-text")?.textContent).toContain(
      "Rehydrierte Sitzung",
    );

    // 3. Round-2 messages are still rendered.
    expect(container.textContent).toContain("Antwort 1 Runde 2");

    unmountRoot(root);
  });

  it("keeps snapshot input values independent from later session-type metadata", async () => {
    // Server returns a snapshot whose interpretation differs from the
    // current default.  After all defaults settle, switching back to
    // Setup must show the *snapshot* interpretation as the Setup text,
    // not the late default interpretation.
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const snapshot = makeCompletedSnapshot({
      material_context: {
        ...makeCompletedSnapshot().material_context!,
        input_values: { research_question: "PERSISTIERTE-INTERPRETATION" },
        input_definitions: [
          {
            key: "research_question",
            label: "Fragestellung",
            prompt_heading: "Fragestellung",
            required: false,
          },
        ],
      },
    });
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    // Switch back to Setup by clicking the Setup tab.
    const setupTab = Array.from(container.querySelectorAll(".view-tab")).find((node) =>
      node.textContent?.includes("Vorbereiten"),
    ) as HTMLButtonElement | undefined;
    expect(setupTab).toBeDefined();
    click(setupTab);
    await flushMicrotasks(6);

    expect(
      container
        .querySelector<HTMLButtonElement>("button[aria-controls='setup-optional-inputs']")
        ?.getAttribute("aria-expanded"),
    ).toBe("true");

    // The interpretation textarea holds the snapshot's text, not the
    // active default.
    const interpTextarea = container.querySelector(
      "#setup-input-research_question",
    ) as HTMLTextAreaElement | null;
    expect(interpTextarea).not.toBeNull();
    expect(interpTextarea?.value).toBe("PERSISTIERTE-INTERPRETATION");
    expect(interpTextarea?.value).not.toBe("Exploriere das Material offen.");

    unmountRoot(root);
  });

  it("does not duplicate the startup open request when Layout re-renders before openSession resolves", async () => {
    // The startup effect must rely on ``startupRestoreAttemptedRef`` so
    // a render that lands between listSessions and openSession does
    // not re-fire the open request.  We hold the open response mid-
    // flight and trigger an extra render through the Setup material
    // textarea (a benign setState that does NOT call selectView and
    // therefore does NOT increment ``restoreEpochRef``).
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const listCall = router.deferred("GET", (url) => url === "/api/sessions");
    const openCall = router.deferred("POST", (url) => url === "/api/sessions/session-open/open");

    const { container, root } = mountLayout(router);
    // Resolve the list response — this is the moment that triggers
    // the open request — but hold the open response so the
    // startup effect stays mid-flight.
    listCall.fulfill([makeSessionSummary()]);
    await flushMicrotasks(4);

    // While the open call is still pending, force an unrelated render.
    // The activity disclosure changes only local display state; unlike tab
    // navigation it must not invalidate the advisory startup restore.
    const activityToggle = container.querySelector(
      ".activity-log-toggle",
    ) as HTMLButtonElement | null;
    expect(activityToggle).not.toBeNull();
    click(activityToggle);
    await flushMicrotasks(2);

    // Now resolve the open request.
    openCall.fulfill(makeCompletedSnapshot());
    await flushMicrotasks(10);

    const openCalls = callsTo(router, "POST", (url) => url.endsWith("/open"));
    expect(openCalls).toHaveLength(1);

    // Final state: discussion is selected because the snapshot was
    // applied successfully.
    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).toContain("Diskutieren");

    unmountRoot(root);
  });

  it("does not update state or log an unhandled rejection when unmounted before list/open resolves", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const listCall = router.deferred("GET", (url) => url === "/api/sessions");

    const { root } = mountLayout(router);
    // Unmount before resolving the list — this is the realistic
    // "user closes the tab before the page settles" race.
    unmountRoot(root);

    // Now resolve the deferred list response.  Layout's effect should
    // observe ``cancelled === true`` and bail.
    listCall.fulfill([makeSessionSummary()]);
    await flushMicrotasks(8);

    // No unhandled rejection must have been logged for this test
    // (other tests' rejections are filtered by the beforeEach setup).
    expect(unhandledRejections).toHaveLength(0);
  });

  it("renders the rehydrated completed snapshot with terminal activity (no wartet rows)", async () => {
    // The ActivityPanel embedded in the rehydrated discussion must
    // reflect the persisted truth: 3/3 Agenten, "fertig" badge, and
    // never the screenshot bug's "wartet" rows.
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json(
      "POST",
      (url) => url === "/api/sessions/session-open/open",
      makeCompletedSnapshot(),
    );

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    // The completed snapshot has no synthesis message, so its terminal
    // progress is the three perspectives that actually ran.
    const text = container.textContent ?? "";
    expect(text).toContain("3/3 Perspektiven");
    expect(text).toContain("fertig");
    expect(container.querySelectorAll(".agent-status-row.is-queued")).toHaveLength(0);

    unmountRoot(root);
  });

  it("keeps the final perspective input context after rehydrating a trailing synthesis", async () => {
    const snapshot = makeCompletedSnapshot();
    snapshot.messages = [
      ...snapshot.messages.map((message) =>
        message.id === "m3b"
          ? {
              ...message,
              usage_available: true,
              prompt_tokens: 1200,
              completion_tokens: 300,
              total_tokens: 1500,
            }
          : message,
      ),
      {
        id: "synthesis-2",
        role: "synthesis",
        content: "Kurze Synthese",
        round_number: 2,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: false,
        include_note_in_agent_context: false,
        error: null,
        client_id: null,
        usage_available: true,
        prompt_tokens: 20,
        completion_tokens: 10,
        total_tokens: 30,
      },
    ];
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", [makeSessionSummary()]);
    router.json("POST", (url) => url === "/api/sessions/session-open/open", snapshot);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const text = container.textContent ?? "";
    expect(text).toContain("Kontextgröße: 1.200 Tokens");
    expect(text).not.toContain("30 Tokens");

    unmountRoot(root);
  });

  it("does not hydrate when the user navigates to a different tab before the startup open request resolves", async () => {
    // Manual navigation increments restoreEpochRef.  When the open
    // request finally resolves, the mayApply() guard returns false
    // and applySessionSnapshot is not called.
    const router = new FetchRouter();
    registerStandardMetadata(router);
    const listCall = router.deferred("GET", (url) => url === "/api/sessions");
    const openCall = router.deferred("POST", (url) => url === "/api/sessions/session-open/open");

    const { container, root } = mountLayout(router);
    listCall.fulfill([makeSessionSummary()]);
    await flushMicrotasks(4);

    // User navigates to the network tab while the open request is in
    // flight.  This must cancel the startup restore.
    const configurationMenu = container.querySelector(
      "[data-configure-menu]",
    ) as HTMLElement | null;
    expect(configurationMenu).not.toBeNull();
    act(() => configurationMenu?.click());
    const networkTab = Array.from(container.querySelectorAll("button")).find((node) =>
      node.textContent?.includes("Externe KI"),
    ) as HTMLButtonElement | undefined;
    click(networkTab);
    await flushMicrotasks(2);

    // Now resolve the open request — Layout must NOT switch to
    // discussion or apply the snapshot.
    openCall.fulfill(makeCompletedSnapshot());
    await flushMicrotasks(10);

    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).toContain("Externe KI");
    // The discussion shell is not rendered.
    expect(container.querySelector("section.discussion-shell")).toBeNull();

    unmountRoot(root);
  });

  it("keeps discussion customization collapsed until requested and derives names from perspectives", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const galleryChoices = Array.from(
      container.querySelectorAll<HTMLLabelElement>(".session-type-card"),
    );
    expect(galleryChoices).toHaveLength(STANDARD_SESSION_TYPES.length);
    expect(
      galleryChoices.map(
        (choice) => choice.querySelector<HTMLInputElement>('input[type="radio"]')?.checked,
      ),
    ).toEqual([true, false]);
    expect(galleryChoices.map((choice) => choice.textContent?.replace("check", ""))).toEqual(
      expect.arrayContaining(["Offene Exploration", "Interpretationsprüfung"]),
    );
    expect(container.querySelectorAll('select[aria-label="Perspektive wählen"]')).toHaveLength(0);

    const customizeButton = container.querySelector<HTMLButtonElement>(
      "button[aria-controls='setup-discussion-customization']",
    );
    expect(customizeButton?.getAttribute("aria-expanded")).toBe("false");
    expect(container.textContent).toContain("Rolle 1 · Rolle 2 · Rolle 3");
    click(customizeButton);

    const selectors = Array.from(
      container.querySelectorAll<HTMLSelectElement>('select[aria-label="Perspektive wählen"]'),
    );
    expect(selectors).toHaveLength(3);
    expect(selectors.map((select) => select.value)).toEqual(["p1", "p2", "p3"]);
    expect(container.querySelector(".agent-name-input")).toBeNull();

    const optionsButtons = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[title="Optionen"]'),
    );
    expect(optionsButtons).toHaveLength(3);
    expect(optionsButtons[0].getAttribute("aria-expanded")).toBe("false");

    click(optionsButtons[0]);
    expect(optionsButtons[0].getAttribute("aria-expanded")).toBe("true");
    expect(
      container.querySelector('[role="region"][aria-label="Optionen für Perspektive 1"]'),
    ).not.toBeNull();

    act(() => {
      selectors[0].value = "p2";
      selectors[0].dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flushMicrotasks(2);

    expect(selectors[0].value).toBe("p2");
    expect(
      Array.from(container.querySelectorAll<HTMLSelectElement>("select")).find(
        (select) =>
          select.closest(".agent-config-row") !== null &&
          Array.from(select.options).some((option) => option.value === "Cloud"),
      ),
    ).toBeDefined();
    expect(
      container.querySelector('[role="region"][aria-label="Optionen für Perspektive 1"]')
        ?.textContent,
    ).not.toContain("Aktiv");
    const prepareOptions = container.querySelector(
      '[role="region"][aria-label="Optionen für Perspektive 1"]',
    )!;
    expect(
      Array.from(prepareOptions.querySelectorAll<HTMLElement>(".agent-config-field > span")).map(
        (label) => label.textContent,
      ),
    ).toEqual(["Host", "Modell"]);
    const modelSelect = prepareOptions.querySelectorAll("select")[1];
    const temperatureToggle =
      prepareOptions.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(
      modelSelect.compareDocumentPosition(temperatureToggle) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    act(() => {
      optionsButtons[0].dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(optionsButtons[0].getAttribute("aria-expanded")).toBe("false");
    expect(selectors[0].value).toBe("p2");

    act(() => {
      Array.from(
        container.querySelectorAll<HTMLSelectElement>('select[aria-label="Perspektive wählen"]'),
      ).forEach((select) => {
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
    await flushMicrotasks(2);

    expect(
      container.querySelector<HTMLButtonElement>('.ds-button--primary[type="button"]')?.disabled,
    ).toBe(true);

    unmountRoot(root);
  });

  it("associates Material Type and uses one native session-type radio group", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const materialType = container.querySelector<HTMLSelectElement>("#setup-material-type")!;
    expect(
      container.querySelector<HTMLLabelElement>('label[for="setup-material-type"]')?.textContent,
    ).toBe("Materialart");
    expect(materialType.labels?.[0]?.textContent).toBe("Materialart");

    const sessionInputs = container.querySelectorAll<HTMLInputElement>(
      '.session-type-card input[type="radio"][name="session-type"]',
    );
    expect(Array.from(sessionInputs).map((input) => input.checked)).toEqual([true, false]);
    sessionInputs[0].focus();
    expect(document.activeElement).toBe(sessionInputs[0]);
    act(() => sessionInputs[1].click());
    await flushMicrotasks(4);
    expect(sessionInputs[1].checked).toBe(true);

    unmountRoot(root);
  });

  it("keeps optional session context collapsed and changes defaults through the session gallery", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const optionalToggle = container.querySelector<HTMLButtonElement>(
      "button[aria-controls='setup-optional-inputs']",
    );
    expect(optionalToggle?.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("#setup-input-research_question")).toBeNull();

    click(optionalToggle);
    expect(optionalToggle?.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector("#setup-input-research_question")).not.toBeNull();

    const sessionCards = container.querySelectorAll<HTMLLabelElement>(".session-type-card");
    click(sessionCards[1]);
    await flushMicrotasks(4);

    expect(
      router.calls.some(
        (call) =>
          call.method === "GET" &&
          call.url === "/api/discussions/defaults/agents?session_type=critique",
      ),
    ).toBe(true);

    unmountRoot(root);
  });

  it("places Research Material Context in Step 2 behind its own right-aligned Options control", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router, undefined, {
      sessionTypes: [
        {
          key: "exploration",
          label: "Offene Exploration",
          inputs: [
            {
              key: "research_material_context",
              label: "Research Material Context",
              default_text: "**Research topic**\n\n…",
              prompt_heading: "RESEARCH MATERIAL CONTEXT",
              required: false,
            },
            {
              key: "main_input",
              label: "Exploration Task",
              prompt_heading: "USER INPUT",
              required: true,
            },
            {
              key: "additional_instructions",
              label: "Additional Instructions",
              prompt_heading: "ADDITIONAL USER INSTRUCTIONS",
              required: false,
            },
          ],
        },
      ],
    });
    router.json("GET", (url) => url === "/api/sessions", []);

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);

    const materialContextToggle = container.querySelector<HTMLButtonElement>(
      "button[aria-controls='setup-research-material-context']",
    );
    expect(materialContextToggle?.getAttribute("aria-expanded")).toBe("false");
    expect(materialContextToggle?.closest(".prepare-step")?.querySelector("h2")?.textContent).toBe(
      "Materialsegment hinzufügen",
    );
    expect(container.querySelector("#setup-input-research_material_context")).toBeNull();

    click(materialContextToggle);
    expect(materialContextToggle?.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector("#setup-input-research_material_context")).not.toBeNull();

    const taskOptionsToggle = container.querySelector<HTMLButtonElement>(
      "button[aria-controls='setup-optional-inputs']",
    );
    expect(taskOptionsToggle?.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("#setup-input-additional_instructions")).toBeNull();

    unmountRoot(root);
  });
});

describe("Configured session input hints", () => {
  it("shows each configured hint beside its input and keeps it associated in both locales", async () => {
    const sessionTypes: SessionType[] = [
      {
        ...STANDARD_SESSION_TYPES[0],
        inputs: [
          {
            key: "research_material_context",
            label: "Research Material Context",
            hint: "Material source sentinel",
            default_text: "",
            prompt_heading: "RESEARCH MATERIAL CONTEXT",
            required: false,
          },
          {
            key: "main_input",
            label: "Main input",
            hint: "Task guidance sentinel",
            default_text: "",
            prompt_heading: "USER INPUT",
            required: true,
          },
          {
            key: "additional_instructions",
            label: "Additional instructions",
            hint: "Approach guidance sentinel",
            default_text: "",
            prompt_heading: "ADDITIONAL USER INSTRUCTIONS",
            required: false,
          },
        ],
      },
    ];

    for (const locale of ["en", "de"] as const) {
      await setLocale(locale);
      const router = new FetchRouter();
      registerStandardMetadata(router, undefined, { sessionTypes });
      router.json("GET", (url) => url === "/api/sessions", []);

      const { container, root } = mountLayout(router);
      await flushMicrotasks(10);

      const taskInput = container.querySelector<HTMLTextAreaElement>("#setup-input-main_input");
      const taskHint = container.querySelector<HTMLElement>("#setup-input-main_input-hint");
      expect(taskHint?.textContent).toBe("Task guidance sentinel");
      expect(taskInput?.getAttribute("placeholder")).toBeNull();
      expect(taskInput?.getAttribute("aria-describedby")?.split(/\s+/)).toContain(taskHint?.id);

      setInputValue(taskInput!, "Edited task sentinel");
      expect(taskHint?.textContent).toBe("Task guidance sentinel");

      // Optional context fields remain available through their existing controls.
      click(
        container.querySelector<HTMLButtonElement>(
          "button[aria-controls='setup-research-material-context']",
        ),
      );
      const materialHint = container.querySelector<HTMLElement>(
        "#setup-input-research_material_context-hint",
      );
      const materialInput = container.querySelector<HTMLTextAreaElement>(
        "#setup-input-research_material_context",
      );
      expect(materialHint?.textContent).toBe("Material source sentinel");
      expect(materialInput?.getAttribute("aria-describedby")?.split(/\s+/)).toContain(
        materialHint?.id,
      );

      click(
        container.querySelector<HTMLButtonElement>("button[aria-controls='setup-optional-inputs']"),
      );
      const instructionsHint = container.querySelector<HTMLElement>(
        "#setup-input-additional_instructions-hint",
      );
      const instructionsInput = container.querySelector<HTMLTextAreaElement>(
        "#setup-input-additional_instructions",
      );
      expect(instructionsHint?.textContent).toBe("Approach guidance sentinel");
      expect(instructionsInput?.getAttribute("aria-describedby")?.split(/\s+/)).toContain(
        instructionsHint?.id,
      );

      unmountRoot(root);
    }
  });
});

describe("Application activity", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("polls Activity while collapsed, ignores read-poll noise, and clears the visible feed", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("GET", (url) => url === "/api/application/activity?after=0&limit=200", {
      events: [
        {
          sequence: 1,
          timestamp: "2026-08-05T12:00:00+00:00",
          level: "info",
          code: "request_completed",
          params: { method: "GET", route: "/api/hosts", status: 200 },
        },
        {
          sequence: 2,
          timestamp: "2026-08-05T12:00:01+00:00",
          level: "info",
          code: "server_started",
          params: {},
        },
        {
          sequence: 3,
          timestamp: "2026-08-05T12:00:02+00:00",
          level: "info",
          code: "request_completed",
          params: { method: "POST", route: "/api/material/token-estimate", status: 200 },
        },
        {
          sequence: 4,
          timestamp: "2026-08-05T12:00:03+00:00",
          level: "info",
          code: "request_completed",
          params: { method: "POST", route: "/api/material/token-estimate", status: 200 },
        },
        {
          sequence: 5,
          timestamp: "2026-08-05T12:00:04+00:00",
          level: "error",
          code: "unexpected_failure",
          params: { method: "POST", route: "/api/discussions/start", status: 500 },
        },
      ],
      next_cursor: 5,
      truncated: false,
    });

    const { container, root } = mountLayout(router);
    await flushMicrotasks(10);
    expect(
      callsTo(router, "GET", (url) => url.startsWith("/api/application/activity")),
    ).not.toHaveLength(0);
    expect(container.textContent).toContain("Aktivität (3)");
    expect(container.textContent).not.toContain("/api/hosts");
    click(container.querySelector<HTMLButtonElement>("button.activity-log-toggle"));
    await flushMicrotasks(6);
    expect(container.textContent).toContain("SERVER");
    expect(container.textContent).toContain("Server gestartet.");
    expect(container.textContent).toContain("POST /api/material/token-estimate → Status 200");
    const stableTime = container.querySelector<HTMLTimeElement>(
      'time[datetime="2026-08-05T12:00:04+00:00"]',
    );
    expect(stableTime?.textContent).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    const errorEntry = stableTime?.closest(".activity-log-error");
    expect(errorEntry?.textContent).toContain("SERVER · FEHLER");
    expect(errorEntry?.textContent).toContain("POST /api/discussions/start");
    expect(
      container.textContent?.match(/POST \/api\/material\/token-estimate → Status 200/g),
    ).toHaveLength(1);
    const clearButton = container.querySelector<HTMLButtonElement>("button.activity-log-clear-btn");
    expect(clearButton?.textContent).toBe("Leeren");
    expect(clearButton?.getAttribute("aria-label")).toBe("Leeren");
    click(clearButton);
    expect(container.textContent).toContain("Keine Ereignisse. Eine Diskussion starten.");
    unmountRoot(root);
  });
});

describe("System language settings", () => {
  afterEach(async () => {
    window.localStorage.removeItem("aqa.uiLocale.v1");
    window.localStorage.removeItem(ROUND_NOTIFICATIONS_STORAGE_KEY);
    resetRoundNotificationsForTests();
    vi.unstubAllGlobals();
    await setLocale("de");
    document.body.innerHTML = "";
  });

  it("renders the persistent interface-language selector above prompt configuration", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    expect(container.querySelector('[data-view="quickstart"]')).toBeNull();
    expect(container.querySelector('[title="AQA beenden"]')).toBeNull();

    click(container.querySelector<HTMLButtonElement>("[data-configure-menu]"));
    click(container.querySelector<HTMLButtonElement>('[data-view="system"]'));
    await flushMicrotasks(4);

    const sections = Array.from(container.querySelectorAll(":scope .system-page > section"));
    expect(sections[0]?.className).toBe("system-language");
    expect(container.querySelector(":scope .system-page > .pcm-manager")).not.toBeNull();

    const selector = container.querySelector<HTMLSelectElement>(
      '.system-language select[aria-label="Sprache"]',
    );
    expect(selector?.value).toBe("de");
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
    act(() => {
      valueSetter.call(selector, "en");
      selector?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flushMicrotasks(4);

    expect(window.localStorage.getItem("aqa.uiLocale.v1")).toBe("en");
    expect(container.textContent).not.toContain("Data and Transfer");
    unmountRoot(root);
  });

  it("reuses release metadata in System and handles repeated native About menu events", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    click(container.querySelector<HTMLButtonElement>("[data-configure-menu]"));
    click(container.querySelector<HTMLButtonElement>('[data-view="system"]'));
    await flushMicrotasks(4);

    const releaseSection = container.querySelector<HTMLElement>(".system-release-information")!;
    expect(releaseSection.textContent).toContain("Release-Informationen");
    expect(releaseSection.textContent).toContain(releaseInfo.version);
    expect(releaseSection.textContent).toContain("Vorabversion");
    expect(releaseSection.textContent).toContain("Noch nicht festgelegt");
    expect(releaseSection.textContent).toContain("GitHub-Repository");
    expect(releaseSection.textContent).not.toContain("Thomas Krause");

    const systemAboutButton = releaseSection.querySelector<HTMLButtonElement>("button")!;
    expect(systemAboutButton.textContent).toBe("Über AQA");
    systemAboutButton.focus();
    click(systemAboutButton);
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("Thomas Krause");
    const systemCloseButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((button) => button.textContent === "Schließen")!;
    click(systemCloseButton);
    expect(document.activeElement).toBe(systemAboutButton);

    const focusReturn = container.querySelector<HTMLSelectElement>(
      '.system-language select[aria-label="Sprache"]',
    )!;
    focusReturn.focus();
    act(() => window.dispatchEvent(new Event("aqa:open-about")));
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("Thomas Krause");
    act(() => window.dispatchEvent(new Event("aqa:open-about")));
    expect(container.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    const closeButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
    ).find((button) => button.textContent === "Schließen")!;
    click(closeButton);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(focusReturn);

    act(() => window.dispatchEvent(new Event("aqa:open-about")));
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    unmountRoot(root);
  });

  it("renders the default-on round notification preference and persists opt-out", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("PUT", (url) => url === "/api/application/preferences", {
      ui_locale: "de",
      ai_source: "integrated",
      local_ai_context_tokens: 32_768,
      local_ai_mtp_enabled: false,
      notifications_enabled: false,
      last_active_discussion_id: null,
    });
    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    click(container.querySelector<HTMLButtonElement>("[data-configure-menu]"));
    click(container.querySelector<HTMLButtonElement>('[data-view="system"]'));
    await flushMicrotasks(4);

    const toggle = container.querySelector<HTMLInputElement>("#system-round-notifications")!;
    expect(toggle.checked).toBe(true);
    expect(container.textContent).toContain("Benachrichtigungen bei Rundenende");
    act(() => toggle.click());
    await flushMicrotasks(4);

    expect(toggle.checked).toBe(false);
    expect(window.localStorage.getItem(ROUND_NOTIFICATIONS_STORAGE_KEY)).toBe("false");
    const updates = callsTo(router, "PUT", (url) => url === "/api/application/preferences");
    expect(updates.map((update) => update.body)).toContainEqual({ notifications_enabled: false });
    unmountRoot(root);
  });

  it("renders the default-on generation sleep preference in System and persists opt-out", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("PUT", (url) => url === "/api/application/preferences", {
      ui_locale: "de",
      ai_source: "integrated",
      local_ai_context_tokens: 32_768,
      local_ai_mtp_enabled: false,
      notifications_enabled: true,
      prevent_sleep_while_generating: false,
      last_active_discussion_id: null,
    });
    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    click(container.querySelector<HTMLButtonElement>("[data-configure-menu]"));
    click(container.querySelector<HTMLButtonElement>('[data-view="system"]'));
    await flushMicrotasks(4);

    const toggle = container.querySelector<HTMLInputElement>(
      "#system-prevent-sleep-while-generating",
    )!;
    expect(toggle.checked).toBe(true);
    expect(container.textContent).toContain("Ruhezustand während der Generierung verhindern");
    act(() => toggle.click());
    await flushMicrotasks(4);

    expect(toggle.checked).toBe(false);
    const updates = callsTo(router, "PUT", (url) => url === "/api/application/preferences");
    expect(updates.map((update) => update.body)).toContainEqual({
      prevent_sleep_while_generating: false,
    });
    unmountRoot(root);
  });

  it("shows the permission action before the first round and requests only when activated", async () => {
    class FakeNotification {
      static permission: NotificationPermission = "default";
      static requestPermission = vi.fn(async () => {
        FakeNotification.permission = "granted";
        return "granted" as NotificationPermission;
      });
    }
    vi.stubGlobal("Notification", FakeNotification);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    await initializeRoundNotifications();

    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    await flushMicrotasks(8);

    click(container.querySelector<HTMLButtonElement>("[data-configure-menu]"));
    click(container.querySelector<HTMLButtonElement>('[data-view="system"]'));
    await flushMicrotasks(4);

    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
    const allow = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent === "Benachrichtigungen erlauben",
    );
    expect(allow).toBeDefined();
    click(allow);
    await flushMicrotasks(4);
    expect(FakeNotification.requestPermission).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Benachrichtigungen sind erlaubt.");
    unmountRoot(root);
  });
});

describe("Layout AI source selection", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.removeItem("aqa.aiSource.v1");
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    document.body.innerHTML = "";
  });

  it("uses one persistent general material notice for both AI sources", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    try {
      await flushMicrotasks(10);
      const materialInput = container.querySelector<HTMLTextAreaElement>("#setup-material-input")!;
      const guidance = container.querySelector("#setup-material-guidance");
      expect(guidance?.getAttribute("role")).toBe("note");
      expect(guidance?.classList.contains("notice-banner--info")).toBe(true);
      expect(guidance?.textContent).toContain("Längeres Material braucht länger zur Verarbeitung");
      expect(guidance?.textContent).not.toContain("Die sichere Größe hängt");
      expect(materialInput.getAttribute("aria-describedby")).toBe("setup-material-guidance");

      const externalChoice = container.querySelectorAll<HTMLInputElement>(
        '.ai-readiness-source-chooser input[type="radio"][name="ai-source"]',
      )[1];
      click(externalChoice);

      expect(container.querySelector("#setup-material-guidance")).not.toBeNull();
      expect(guidance?.textContent).toContain("Längeres Material braucht länger zur Verarbeitung");
      expect(materialInput.getAttribute("aria-describedby")).toBe("setup-material-guidance");
    } finally {
      unmountRoot(root);
    }
  });

  it("blocks oversized input and restores Start after editing", async () => {
    window.localStorage.setItem("aqa.targetLanguage.v1", "Deutsch");
    const router = new FetchRouter();
    let overflow = true;
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.route(
      "POST",
      (url) => url === "/api/discussions/context-estimate",
      () => {
        const estimate = {
          known: true,
          estimated_input_tokens: overflow ? 30_000 : 500,
          available_input_tokens: 28_672,
          context_window_tokens: 32_768,
          reserved_output_tokens: 4_096,
          overflow,
        };
        return { ok: true, status: 200, textValue: JSON.stringify(estimate), jsonValue: estimate };
      },
    );
    const { container, root } = mountLayout(router);
    try {
      await flushMicrotasks(10);
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 300));
      });
      await flushMicrotasks(4);

      const guidance = container.querySelector("#setup-material-guidance");
      expect(guidance?.classList.contains("notice-banner--error")).toBe(true);
      expect(guidance?.getAttribute("role")).toBe("note");
      expect(guidance?.textContent).toContain(
        "Die Eingabe ist zu lang. Kürze das Material oder den Auftrag.",
      );
      expect(guidance?.textContent).not.toContain("mehrere Minuten");
      const startHint = container.querySelector("#setup-start-disabled-reason");
      expect(startHint?.textContent).toBe(
        "helpDie Eingabe ist zu lang. Kürze das Material oder den Auftrag.",
      );
      expect(startHint?.className).toBe("blocked-action-hint");
      expect(startHint?.getAttribute("role")).toBe("status");
      const start = container.querySelector<HTMLButtonElement>(".prepare-start-action .ds-button");
      expect(start?.disabled).toBe(true);

      overflow = false;
      setInputValue(container.querySelector<HTMLTextAreaElement>("#setup-material-input")!, "Kurz");
      await settleContextCheck();
      expect(container.querySelector("#setup-material-guidance")?.classList).toContain(
        "notice-banner--info",
      );
      expect(container.querySelector("#setup-start-disabled-reason")).toBeNull();
      expect(start?.disabled).toBe(false);

      const externalChoice = container.querySelectorAll<HTMLInputElement>(
        '.ai-readiness-source-chooser input[type="radio"][name="ai-source"]',
      )[1];
      click(externalChoice);
      expect(guidance?.textContent).not.toContain("Kontextgröße");
    } finally {
      unmountRoot(root);
    }
  });

  it("does not block Start while the offline estimate is unavailable", async () => {
    window.localStorage.setItem("aqa.targetLanguage.v1", "Deutsch");
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("POST", (url) => url === "/api/discussions/context-estimate", {
      known: false,
      estimated_input_tokens: null,
      available_input_tokens: 4096,
      context_window_tokens: 8192,
      reserved_output_tokens: 4096,
      overflow: false,
    });
    const { container, root } = mountLayout(router);
    try {
      await flushMicrotasks(10);
      const start = container.querySelector<HTMLButtonElement>(".prepare-start-action .ds-button");
      const hint = container.querySelector("#setup-start-disabled-reason");
      expect(start?.disabled).toBe(false);
      expect(hint).toBeNull();
      await settleContextCheck();
      expect(start?.disabled).toBe(false);
    } finally {
      unmountRoot(root);
    }
  });

  it("applies and remembers the external preferred host for every perspective", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    const { container, root } = mountLayout(router);
    try {
      await flushMicrotasks(10);
      const choices = container.querySelectorAll<HTMLInputElement>(
        '.ai-readiness-source-chooser input[type="radio"][name="ai-source"]',
      );
      expect(choices).toHaveLength(2);
      const externalChoice = choices[1];
      expect(externalChoice).toBeDefined();
      click(externalChoice);
      await flushMicrotasks(2);
      expect(
        container.querySelectorAll(
          '.ai-readiness-source-chooser input[type="radio"][name="ai-source"]',
        ),
      ).toHaveLength(2);

      expect(window.localStorage.getItem("aqa.aiSource.v1")).toBe("external");
      click(
        container.querySelector<HTMLButtonElement>(
          "button[aria-controls='setup-discussion-customization']",
        ),
      );
      Array.from(
        container.querySelectorAll<HTMLButtonElement>(
          ".agent-config-row .agent-config-options-toggle",
        ),
      ).forEach((button) => click(button));
      const selectedHosts = Array.from(
        container.querySelectorAll<HTMLSelectElement>(".agent-config-row select"),
      ).filter(
        (select) =>
          select.value === "Cloud" &&
          Array.from(select.options).some((option) => option.value === "Lokale KI"),
      );
      expect(selectedHosts).toHaveLength(3);

      const firstHost = selectedHosts[0];
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      act(() => {
        setter.call(firstHost, "Lokale KI");
        firstHost.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(firstHost.value).toBe("Lokale KI");
    } finally {
      unmountRoot(root);
    }
  });
});

describe("Layout discussion preflight 409 recovery", () => {
  let unhandledRejections: unknown[] = [];
  let rejectionHandler: ((event: PromiseRejectionEvent) => void) | undefined;
  let consoleErrorSpy: MockInstance | undefined;
  let roots: Root[] = [];

  beforeEach(() => {
    if (!window.confirm) {
      window.confirm = () => true;
    }
    unhandledRejections = [];
    rejectionHandler = (event) => {
      unhandledRejections.push(event.reason);
      event.preventDefault();
    };
    window.addEventListener("unhandledrejection", rejectionHandler);
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    roots = [];
  });

  afterEach(() => {
    if (rejectionHandler) {
      window.removeEventListener("unhandledrejection", rejectionHandler);
    }
    consoleErrorSpy?.mockRestore();
    vi.restoreAllMocks();
    for (const root of roots) {
      unmountRoot(root);
    }
    window.localStorage.removeItem("aqa.targetLanguage.v1");
    document.body.innerHTML = "";
  });

  function trackRoot(handle: MountHandle): MountHandle {
    roots.push(handle.root);
    return handle;
  }

  it("disables Start without a target language and remembers the trimmed value on start", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("POST", (url) => url === "/api/discussions/start", { detail: "validation" }, 400);
    const { container } = trackRoot(mountLayout(router));
    await flushMicrotasks(12);

    const targetLanguage = container.querySelector<HTMLInputElement>("#setup-target-language");
    const startButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (node) => node.textContent?.includes("Diskussion starten"),
    );
    expect(targetLanguage?.required).toBe(true);
    expect(startButton?.disabled).toBe(true);
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Fülle alle erforderlichen Felder aus, bevor du startest.",
    );
    expect(callsTo(router, "POST", (url) => url === "/api/discussions/start")).toHaveLength(0);

    setInputValue(targetLanguage!, "  English  ");
    await settleContextCheck();
    expect(startButton?.disabled).toBe(false);
    click(startButton);
    await flushMicrotasks(6);

    expect(window.localStorage.getItem("aqa.targetLanguage.v1")).toBe("English");
    expect(
      callsTo(router, "POST", (url) => url === "/api/discussions/start")[0]?.body,
    ).toMatchObject({ material_context: { target_language: "English" } });
  });

  it("starts a verified downloaded Integrated AI from Prepare before starting the discussion", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router, {
      state: "installed",
      host_ready: false,
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      models: [
        {
          model_id: "gemma-4-e2b",
          api_alias: "local-model",
          installed: true,
          integrity: "verified",
        },
      ],
    });
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("POST", (url) => url === "/api/local-ai/start", {
      state: "running",
      model_name: "Gemma 4 E2B",
      host_ready: true,
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      download_bytes: 0,
      download_total: 0,
      import_bytes: 0,
      import_total: 0,
      context_tokens: 32_768,
      mtp_enabled: false,
      mtp_draft_tokens: 4,
      message: null,
      integrity: "verified",
      models: [
        {
          model_id: "gemma-4-e2b",
          api_alias: "local-model",
          installed: true,
          integrity: "verified",
        },
      ],
      runtime_installed: true,
      runtime_selection: {
        runtime_profile: null,
        accelerator_label: "CPU",
        engine_name: null,
        decision_basis: "safe CPU fallback",
        runtime_installed: true,
      },
    });

    const { container } = trackRoot(mountLayout(router));
    await flushMicrotasks(12);

    expect(container.querySelector(".setup-ai-notice")).toBeNull();
    const startButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (node) => node.textContent?.includes("Diskussion starten"),
    );
    setInputValue(container.querySelector<HTMLInputElement>("#setup-target-language")!, "Deutsch");
    await settleContextCheck();
    expect(startButton?.disabled).toBe(false);

    click(startButton);
    await flushMicrotasks(12);

    expect(callsTo(router, "POST", (url) => url === "/api/local-ai/start")).toHaveLength(1);
    expect(callsTo(router, "POST", (url) => url === "/api/discussions/start")).toHaveLength(1);
    expect(callsTo(router, "POST", (url) => url === "/api/local-ai/start")[0]?.body).toMatchObject({
      model_id: "gemma-4-e2b",
      mtp_enabled: false,
    });
    expect(
      callsTo(router, "POST", (url) => url === "/api/local-ai/start")[0]?.body,
    ).not.toHaveProperty("mtp_draft_tokens");
  });

  it("refreshes a running Integrated AI host before submitting its dynamic endpoint", async () => {
    const router = new FetchRouter();
    let hostsRequest = 0;
    const staleHosts = STANDARD_HOSTS.map((host) => ({ ...host }));
    const currentHosts = STANDARD_HOSTS.map((host) =>
      host.kind === "local_ai"
        ? { ...host, url: "http://127.0.0.1:58848", model: "gemma-4-e2b", models: ["gemma-4-e2b"] }
        : { ...host },
    );
    registerStandardMetadata(
      router,
      {
        state: "running",
        host_ready: true,
        model_id: "gemma-4-e2b",
        preferred_model_id: "gemma-4-e2b",
      },
      { hosts: () => (hostsRequest++ === 0 ? staleHosts : currentHosts) },
    );
    router.json("GET", (url) => url === "/api/sessions", []);
    router.json("POST", (url) => url === "/api/discussions/start", { session_id: "started" });

    const { container } = trackRoot(mountLayout(router));
    await flushMicrotasks(12);
    setInputValue(
      container.querySelector<HTMLTextAreaElement>("#setup-material-input")!,
      "Short material",
    );
    setInputValue(container.querySelector<HTMLInputElement>("#setup-target-language")!, "English");
    await settleContextCheck();
    const startButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (node) => node.textContent?.includes("Diskussion starten"),
    )!;

    click(startButton);
    await flushMicrotasks(16);

    expect(callsTo(router, "POST", (url) => url === "/api/local-ai/start")).toHaveLength(0);
    expect(callsTo(router, "GET", (url) => url === "/api/hosts")).toHaveLength(2);
    const startCall = callsTo(router, "POST", (url) => url === "/api/discussions/start")[0];
    expect(startCall?.body).toMatchObject({
      agents: expect.arrayContaining([
        expect.objectContaining({
          api_host: "http://127.0.0.1:58848",
          host_configuration_id: "Lokale KI",
          llm_id: "gemma-4-e2b",
        }),
      ]),
      synthesis: expect.objectContaining({
        api_host: "http://127.0.0.1:58848",
        host_configuration_id: "Lokale KI",
        llm_id: "gemma-4-e2b",
      }),
    });
  });

  it("routes the stable local_ai_not_running code to the Local AI tab", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    // No open session — startup restore leaves the Setup tab active
    // and the Configure menu may also be present. The Setup view
    // is what we click the "Diskussion starten" button in.
    router.json("GET", (url) => url === "/api/sessions", []);

    // The SSE start endpoint must reject with the *exact* 409 + detail
    // combination that the backend uses for "managed model installed
    // itself wraps the failure in an ApiError, so the router is fed
    // the original 409 response and the test asserts the resulting
    // user-visible behavior end-to-end.
    const PREFLIGHT_DETAIL = "Diagnostic wording that must not control navigation.";
    router.route(
      "POST",
      (url) => url === "/api/discussions/start",
      () => ({
        ok: false,
        status: 409,
        textValue: JSON.stringify({
          detail: PREFLIGHT_DETAIL,
          error: { code: "local_ai_not_running", params: {} },
        }),
        jsonValue: {
          detail: PREFLIGHT_DETAIL,
          error: { code: "local_ai_not_running", params: {} },
        },
      }),
    );

    const { container } = trackRoot(mountLayout(router));
    // Let the metadata effect, startup restore, and the default
    // agents fetch all settle so the Setup view's "Diskussion
    // starten" button is enabled.
    await flushMicrotasks(12);

    const startButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (node) => node.textContent?.includes("Diskussion starten"),
    );
    expect(startButton).toBeDefined();

    setInputValue(container.querySelector<HTMLInputElement>("#setup-target-language")!, "Deutsch");
    await settleContextCheck();
    expect(startButton?.disabled).toBe(false);

    click(startButton);
    // The click synchronously flips the view to "discussion" and
    // calls handleStart, which fetches /api/discussions/start and
    // hits our 409. Several microtasks later the catch branch
    // observes the ApiError and reroutes to local-ai.
    await flushMicrotasks(12);

    // 1. Streaming has ended, so no running button is shown.
    //    and the discussion shell is no longer the active view.
    const allText = container.textContent ?? "";
    expect(allText).not.toContain("Läuft...");

    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).toContain("Integrierte KI");

    // The localized recovery message remains visible after navigation.
    expect(allText).toContain(
      "Integrierte KI läuft noch nicht. Das bevorzugte Modell unter „Integrierte KI“ starten und anschließend die Diskussion erneut beginnen.",
    );
  });

  it("does not force navigation to the Local AI tab for an unrelated 409 detail", async () => {
    const router = new FetchRouter();
    registerStandardMetadata(router);
    router.json("GET", (url) => url === "/api/sessions", []);

    // An unrelated 409 — e.g. a validation preflight on a different
    // generic catch branch keeps the user on the discussion view
    // and surfaces the original `API error 409: <detail>` message.
    const UNRELATED_DETAIL = "Some other validation failed.";
    router.route(
      "POST",
      (url) => url === "/api/discussions/start",
      () => ({
        ok: false,
        status: 409,
        textValue: JSON.stringify({ detail: UNRELATED_DETAIL }),
        jsonValue: { detail: UNRELATED_DETAIL },
      }),
    );

    const { container } = trackRoot(mountLayout(router));
    await flushMicrotasks(12);

    const startButton = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (node) => node.textContent?.includes("Diskussion starten"),
    );
    expect(startButton).toBeDefined();

    setInputValue(container.querySelector<HTMLInputElement>("#setup-target-language")!, "Deutsch");
    await settleContextCheck();
    expect(startButton?.disabled).toBe(false);

    click(startButton);
    await flushMicrotasks(12);

    const activeTab = container.querySelector('button[aria-current="page"]');
    expect(activeTab?.textContent).not.toContain("Integrierte KI");

    // 2. The recovery copy must not appear in the UI.
    const allText = container.textContent ?? "";
    expect(allText).not.toContain(
      "Integrierte KI läuft noch nicht. Das bevorzugte Modell unter „Integrierte KI“ starten und anschließend die Diskussion erneut beginnen.",
    );
  });
});
