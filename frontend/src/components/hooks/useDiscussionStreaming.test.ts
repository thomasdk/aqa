import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import type { StartDiscussionParams } from "../../api";
import type { DiscussionMessage, SSEEvent } from "../types";
import {
  toAgentDiscussionMessage,
  type DiscussionStreamingController,
  useDiscussionStreaming,
} from "./useDiscussionStreaming";
import { sendRoundNotification } from "../../roundNotifications";
import { resetGenerationSleepInhibitionForTests } from "../../generationSleepInhibition";

vi.mock("../../roundNotifications", () => ({
  sendRoundNotification: vi.fn().mockResolvedValue(true),
}));

const START_PARAMS: StartDiscussionParams = {
  material: "Material",
  agents: [],
  synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
  title: "Discussion",
  material_context: {
    material_type: "document",
    session_type: "exploration",
    target_language: "English",
    input_values: {},
  },
  sequential_mode: false,
};

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload),
  } as Response;
}

function streamResponse(closes: Array<() => void>): Response {
  let close: (() => void) | undefined;
  let closed = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      close = () => {
        if (closed) return;
        closed = true;
        controller.close();
      };
    },
  });
  closes.push(() => close?.());
  return { ok: true, status: 200, body } as Response;
}

function eventStreamResponse(...events: unknown[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")),
      );
      controller.close();
    },
  });
  return { ok: true, status: 200, body } as Response;
}

function acceptedOpenStream(closes: Array<() => void>): Response {
  const encoder = new TextEncoder();
  let close: (() => void) | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          'data: {"type":"discussion_started","file_id":"session-1","title":"Discussion"}\n\n',
        ),
      );
      close = () => controller.close();
    },
  });
  closes.push(() => close?.());
  return { ok: true, status: 200, body } as Response;
}

function discussionMessage(id: string, content: string): DiscussionMessage {
  return {
    id,
    role: "user",
    content,
    round_number: 1,
    note: "",
    include_in_agent_context: true,
  };
}

type StreamingHarness = { controller: () => DiscussionStreamingController; root: Root };

function mountStreaming(): StreamingHarness {
  let current: DiscussionStreamingController | null = null;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  function TestHarness() {
    current = useDiscussionStreaming({
      activeSessionFileId: null,
      addActivity: vi.fn(),
      onDiscussionStarted: vi.fn(),
      onLocalAINotRunning: vi.fn(),
      setAgents: vi.fn(),
      setError: vi.fn(),
      setSynthesis: vi.fn(),
      synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
      t: ((key: string) => key) as unknown as TFunction,
    });
    return null;
  }
  act(() => root.render(createElement(TestHarness)));
  return {
    controller: () => {
      if (!current) throw new Error("Streaming controller was not rendered");
      return current;
    },
    root,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.mocked(sendRoundNotification).mockClear();
  resetGenerationSleepInhibitionForTests();
  document.body.innerHTML = "";
});

describe("round duration knowledge", () => {
  it("measures Start and Stop, then clears the value for reopened or switched discussions", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(0));
    const closes: Array<() => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") return Promise.resolve(acceptedOpenStream(closes));
        if (input === "/api/discussions/cancel") {
          return Promise.resolve(jsonResponse({ status: "cancelling" }));
        }
        if (input === "/api/discussions/state") {
          return Promise.resolve(
            jsonResponse({
              messages: [],
              has_active_discussion: true,
              round_status: "interrupted",
            }),
          );
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    expect(harness.controller().roundElapsedSeconds).toBeNull();
    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(harness.controller().roundStartedAt).toBe(0);
    expect(harness.controller().roundElapsedSeconds).toBe(0);

    vi.setSystemTime(new Date(4_200));
    act(() => harness.controller().stop());
    expect(harness.controller().roundStartedAt).toBeNull();
    expect(harness.controller().roundElapsedSeconds).toBe(4);

    for (const [fileId, status] of [
      ["first", "completed"],
      ["first", "failed"],
      ["first", "interrupted"],
      ["second", "completed"],
    ] as const) {
      act(() =>
        harness.controller().hydrateSnapshot({
          activeSessionFileId: fileId,
          agents: [],
          hasDiscussion: true,
          messages: [discussionMessage(fileId, fileId)],
          roundStatus: status,
        }),
      );
      expect(harness.controller().roundStatus).toBe(status);
      expect(harness.controller().roundStartedAt).toBeNull();
      expect(harness.controller().roundElapsedSeconds).toBeNull();
    }

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    expect(harness.controller().roundElapsedSeconds).toBe(0);
    act(() => {
      harness.controller().invalidate();
      harness.root.unmount();
    });
    closes.forEach((close) => close());
  });
});

describe("generation sleep inhibition lifecycle", () => {
  it("acquires for an active stream and releases when its owner unmounts", async () => {
    const closes: Array<() => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(acceptedOpenStream(closes));
        }
        if (input === "/api/discussions/cancel") {
          return Promise.resolve(jsonResponse({ status: "cancelling" }));
        }
        if (input === "/api/discussions/state") {
          return Promise.resolve(
            jsonResponse({
              messages: [],
              has_active_discussion: true,
              round_status: "interrupted",
            }),
          );
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const harness = mountStreaming();

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await vi.waitFor(() =>
      expect(invoke).toHaveBeenCalledWith(
        "update_generation_sleep_inhibition",
        expect.objectContaining({ active: true, enabled: true }),
      ),
    );

    act(() => {
      harness.controller().invalidate();
      harness.root.unmount();
    });
    await vi.waitFor(() =>
      expect(invoke).toHaveBeenCalledWith(
        "update_generation_sleep_inhibition",
        expect.objectContaining({ active: false, enabled: true }),
      ),
    );
  });
});

describe("toAgentDiscussionMessage", () => {
  it("retains the completed perspective client identity", () => {
    const event: Extract<SSEEvent, { type: "agent_complete" }> = {
      type: "agent_complete",
      message_id: "message-1",
      agent_index: 0,
      perspective_number: 1,
      client_id: "conceptualization",
      agent_name: "Conceptualization",
      theory_label: "",
      color: "#2563eb",
      text: "Completed response",
      is_complete: true,
      error: null,
    };

    const message = toAgentDiscussionMessage(event, 1, undefined);

    expect(message.client_id).toBe("conceptualization");
    expect(message.perspective_number).toBe(1);
  });

  it("keeps raw provider errors out of the editable note surface", () => {
    const event: Extract<SSEEvent, { type: "agent_complete" }> = {
      type: "agent_complete",
      message_id: "message-error",
      agent_index: 0,
      perspective_number: 1,
      client_id: "conceptualization",
      agent_name: "Conceptualization",
      theory_label: "",
      color: "#2563eb",
      text: "",
      is_complete: true,
      error: "raw retry and HTTP connection detail",
      error_code: "agent_generation_failed",
    };

    const message = toAgentDiscussionMessage(event, 1, undefined);

    expect(message.note).toBe("");
    expect(message.error).toBe(event.error);
    expect(message.error_code).toBe("agent_generation_failed");
  });

  it("retains a provider failure as a non-complete message status", () => {
    const event: Extract<SSEEvent, { type: "agent_complete" }> = {
      type: "agent_complete",
      message_id: "message-partial",
      agent_index: 0,
      perspective_number: 1,
      client_id: "conceptualization",
      agent_name: "Conceptualization",
      theory_label: "",
      color: "#2563eb",
      text: "Visible response before disconnect",
      is_complete: false,
      status: "failed",
      error: "provider disconnected",
      error_code: "agent_generation_failed",
    };

    const message = toAgentDiscussionMessage(event, 1, undefined);

    expect(message.content).toContain("Visible response before disconnect");
    expect(message.status).toBe("failed");
  });
});

describe("interruption recovery race guards", () => {
  it("ignores a delayed cancel refresh after a newer hydrated snapshot", async () => {
    const cancelResponse = deferred<Response>();
    const stateResponse = deferred<Response>();
    const closes: Array<() => void> = [];
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/discussions/start") return Promise.resolve(streamResponse(closes));
      if (input === "/api/discussions/cancel") return cancelResponse.promise;
      if (input === "/api/discussions/state") return stateResponse.promise;
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const harness = mountStreaming();

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => harness.controller().stop());
    cancelResponse.resolve(jsonResponse({ status: "cancelling" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.some(([input]) => input === "/api/discussions/state")).toBe(true);
    act(() =>
      harness.controller().hydrateSnapshot({
        activeSessionFileId: "new-session",
        agents: [],
        hasDiscussion: true,
        messages: [discussionMessage("snapshot", "New snapshot")],
        roundStatus: "completed",
      }),
    );
    stateResponse.resolve(
      jsonResponse({
        messages: [discussionMessage("stale", "Stale cancel response")],
        has_active_discussion: true,
        round_status: "interrupted",
      }),
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(harness.controller().messages.map((message) => message.content)).toEqual([
      "New snapshot",
    ]);
    expect(harness.controller().roundStatus).toBe("completed");
    harness.controller().invalidate();
    closes.forEach((close) => close());
    act(() => harness.root.unmount());
  });

  it("ignores a delayed cancel refresh after a newer run starts", async () => {
    const cancelResponse = deferred<Response>();
    const stateResponse = deferred<Response>();
    const closes: Array<() => void> = [];
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/discussions/start") return Promise.resolve(streamResponse(closes));
      if (input === "/api/discussions/cancel") return cancelResponse.promise;
      if (input === "/api/discussions/state") return stateResponse.promise;
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const harness = mountStreaming();

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => harness.controller().stop());
    cancelResponse.resolve(jsonResponse({ status: "cancelling" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.some(([input]) => input === "/api/discussions/state")).toBe(true);

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await act(async () => {
      await Promise.resolve();
    });
    stateResponse.resolve(
      jsonResponse({
        messages: [discussionMessage("stale", "Stale cancel response")],
        has_active_discussion: true,
        round_status: "interrupted",
      }),
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(harness.controller().messages).toEqual([]);
    expect(harness.controller().roundStatus).toBe("in_progress");
    harness.controller().invalidate();
    closes.forEach((close) => close());
    act(() => harness.root.unmount());
  });

  it("ignores an incomplete-stream refresh after a newer hydrated snapshot", async () => {
    const cancelResponse = deferred<Response>();
    const stateResponse = deferred<Response>();
    const closes: Array<() => void> = [];
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/discussions/start") return Promise.resolve(streamResponse(closes));
      if (input === "/api/discussions/cancel") return cancelResponse.promise;
      if (input === "/api/discussions/state") return stateResponse.promise;
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const harness = mountStreaming();

    act(() => {
      void harness.controller().start(START_PARAMS);
    });
    await act(async () => {
      await Promise.resolve();
    });
    closes[0]?.();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    cancelResponse.resolve(jsonResponse({ status: "cancelling" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.some(([input]) => input === "/api/discussions/state")).toBe(true);
    act(() =>
      harness.controller().hydrateSnapshot({
        activeSessionFileId: "new-session",
        agents: [],
        hasDiscussion: true,
        messages: [discussionMessage("snapshot", "New snapshot")],
        roundStatus: "completed",
      }),
    );
    stateResponse.resolve(
      jsonResponse({
        messages: [discussionMessage("stale", "Stale incomplete response")],
        has_active_discussion: true,
        round_status: "interrupted",
      }),
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(harness.controller().messages.map((message) => message.content)).toEqual([
      "New snapshot",
    ]);
    expect(harness.controller().roundStatus).toBe("completed");
    harness.controller().invalidate();
    closes.forEach((close) => close());
    act(() => harness.root.unmount());
  });
});

describe("round completion notifications", () => {
  it("deduplicates mixed terminal events within a run and notifies again for the next run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(
            eventStreamResponse(
              { type: "discussion_started", file_id: "session-1", title: "Discussion" },
              { type: "error", message: "Generation failed", error_code: "internal_error" },
              { type: "all_complete" },
            ),
          );
        }
        if (input === "/api/discussions/state") {
          return Promise.resolve(
            jsonResponse({ messages: [], has_active_discussion: true, round_status: "failed" }),
          );
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });
    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });

    expect(sendRoundNotification).toHaveBeenCalledTimes(2);
    expect(sendRoundNotification).toHaveBeenNthCalledWith(1, {
      title: "AQA",
      body: "system.notificationFailed",
    });
    expect(sendRoundNotification).toHaveBeenNthCalledWith(2, {
      title: "AQA",
      body: "system.notificationFailed",
    });
    act(() => harness.root.unmount());
  });

  it("notifies exactly once with the server-confirmed completed outcome", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(
            eventStreamResponse(
              { type: "discussion_started", file_id: "session-1", title: "Discussion" },
              { type: "all_complete" },
              { type: "all_complete" },
            ),
          );
        }
        if (input === "/api/discussions/state") {
          return Promise.resolve(
            jsonResponse({ messages: [], has_active_discussion: true, round_status: "completed" }),
          );
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });

    expect(sendRoundNotification).toHaveBeenCalledTimes(1);
    expect(sendRoundNotification).toHaveBeenCalledWith({
      title: "AQA",
      body: "system.notificationCompleted",
    });
    act(() => harness.root.unmount());
  });

  it("falls back to the accepted stream outcome when state refresh fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(
            eventStreamResponse(
              { type: "discussion_started", file_id: "session-1", title: "Discussion" },
              { type: "all_complete" },
            ),
          );
        }
        if (input === "/api/discussions/state") {
          return Promise.reject(new Error("State refresh failed"));
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });

    expect(sendRoundNotification).toHaveBeenCalledWith({
      title: "AQA",
      body: "system.notificationCompleted",
    });
    act(() => harness.root.unmount());
  });

  it("notifies for a terminal stream failure but not for a rejected request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        eventStreamResponse(
          { type: "discussion_started", file_id: "session-1", title: "Discussion" },
          { type: "error", message: "Generation failed", error_code: "internal_error" },
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ messages: [], has_active_discussion: true, round_status: "failed" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const harness = mountStreaming();

    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });
    expect(sendRoundNotification).toHaveBeenCalledWith({
      title: "AQA",
      body: "system.notificationFailed",
    });

    vi.mocked(sendRoundNotification).mockClear();
    fetchMock.mockRejectedValueOnce(new Error("Request rejected"));
    await act(async () => {
      await harness.controller().start(START_PARAMS);
    });
    expect(sendRoundNotification).not.toHaveBeenCalled();
    act(() => harness.root.unmount());
  });

  it("notifies when an accepted stream is interrupted unexpectedly", async () => {
    vi.spyOn(console, "debug").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(
            eventStreamResponse({
              type: "discussion_started",
              file_id: "session-1",
              title: "Discussion",
            }),
          );
        }
        if (input === "/api/discussions/cancel") {
          return Promise.resolve(jsonResponse({ status: "cancelling" }));
        }
        if (input === "/api/discussions/state") {
          return Promise.reject(new Error("State refresh failed"));
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    await act(async () => {
      await harness.controller().start(START_PARAMS);
      await Promise.resolve();
    });

    expect(sendRoundNotification).toHaveBeenCalledWith({
      title: "AQA",
      body: "system.notificationInterrupted",
    });
    act(() => harness.root.unmount());
  });

  it("notifies after an accepted round is explicitly cancelled", async () => {
    vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const closes: Array<() => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input === "/api/discussions/start") {
          return Promise.resolve(acceptedOpenStream(closes));
        }
        if (input === "/api/discussions/cancel") {
          return Promise.resolve(jsonResponse({ status: "cancelling" }));
        }
        if (input === "/api/discussions/state") {
          return Promise.reject(new Error("State refresh failed"));
        }
        throw new Error(`Unexpected request: ${input}`);
      }),
    );
    const harness = mountStreaming();

    act(() => void harness.controller().start(START_PARAMS));
    await act(async () => await Promise.resolve());
    act(() => harness.controller().stop());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(sendRoundNotification).toHaveBeenCalledWith({
      title: "AQA",
      body: "system.notificationInterrupted",
    });
    closes.forEach((close) => close());
    act(() => harness.root.unmount());
  });
});
