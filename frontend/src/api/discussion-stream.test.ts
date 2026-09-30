import { describe, expect, it } from "vitest";
import {
  DiscussionStreamIncompleteError,
  isSSEEvent,
  parseSSEStream,
  startDiscussionStream,
} from "./discussion-stream";

function stream(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("SSE event contract", () => {
  it("accepts each documented discriminator", () => {
    expect(isSSEEvent({ type: "discussion_started", file_id: "x", title: "A" })).toBe(true);
    expect(
      isSSEEvent({ type: "user_message", message_id: "m", content: "q", round_number: 1 }),
    ).toBe(true);
    expect(
      isSSEEvent({
        type: "agent_start",
        message_id: "m",
        agent_index: 0,
        perspective_number: 3,
        agent_name: "A",
        theory_label: "T",
        color: "#fff",
        client_id: "c",
      }),
    ).toBe(true);
    expect(isSSEEvent({ type: "synthesis_start", message_id: "s", round_number: 1 })).toBe(true);
    expect(isSSEEvent({ type: "synthesis_chunk", message_id: "s", text: "Summary" })).toBe(true);
    expect(
      isSSEEvent({
        type: "synthesis_complete",
        message_id: "s",
        round_number: 1,
        text: "- A complete point",
        error_code: "synthesis_no_usable_contributions",
      }),
    ).toBe(true);
    expect(
      isSSEEvent({
        type: "synthesis_error",
        message_id: "s",
        round_number: 1,
        message: "Unavailable",
      }),
    ).toBe(true);
    expect(
      isSSEEvent({
        type: "context_usage",
        message_id: "m",
        agent_index: 0,
        perspective_number: 3,
        available: true,
        input_tokens: 120,
        context_tokens: 65536,
        exact: false,
        omitted_round_numbers: [2, 3],
      }),
    ).toBe(true);
    expect(
      isSSEEvent({
        type: "chunk",
        message_id: "m",
        agent_index: 0,
        perspective_number: 3,
        text: "x",
      }),
    ).toBe(true);
    expect(
      isSSEEvent({
        type: "agent_complete",
        message_id: "m",
        agent_index: 0,
        perspective_number: 3,
        client_id: "a1",
        agent_name: "A",
        theory_label: "T",
        color: "#fff",
        text: "x",
        is_complete: true,
        error: null,
        error_code: "context_limit_exceeded",
        error_params: { input_tokens: 43_166, context_tokens: 32_768 },
        status: "failed",
        usage_available: true,
        prompt_tokens: 12,
        completion_tokens: 3,
        total_tokens: 15,
      }),
    ).toBe(true);
    expect(isSSEEvent({ type: "all_complete" })).toBe(true);
    expect(isSSEEvent({ type: "error", message: "failed" })).toBe(true);
    expect(
      isSSEEvent({
        type: "agent_complete",
        message_id: "m",
        agent_index: 0,
        perspective_number: 3,
        agent_name: "A",
        theory_label: "T",
        color: "#fff",
        text: "x",
        is_complete: true,
        error: null,
      }),
    ).toBe(false);
  });

  it("rejects unknown or incomplete events", () => {
    expect(isSSEEvent({ type: "future_event" })).toBe(false);
    expect(isSSEEvent({ type: "chunk", message_id: "m", agent_index: 0 })).toBe(false);
    expect(isSSEEvent({ type: "agent_start", message_id: "m", agent_index: 0 })).toBe(false);
    expect(isSSEEvent(null)).toBe(false);
  });

  it("keeps parsing after malformed and contract-invalid events", async () => {
    const body = stream(
      "data: {broken}\n\n",
      'data: {"type":"chunk","message_id":"m"}\n\n',
      'data: {"type":"all_complete"}\n\n',
    );

    const events = [];
    for await (const event of parseSSEStream(body)) events.push(event);

    expect(events).toEqual([{ type: "all_complete" }]);
  });

  it("handles CRLF and event boundaries split across chunks", async () => {
    const body = stream(
      'data: {"type":"discussion_started","file_id":"one",',
      '"title":"Title"}\r',
      '\n\r\ndata: {"type":"all_complete"}\r\n\r\n',
    );

    const events = [];
    for await (const event of parseSSEStream(body)) events.push(event);

    expect(events).toEqual([
      { type: "discussion_started", file_id: "one", title: "Title" },
      { type: "all_complete" },
    ]);
  });

  it("reports a clean EOF without a terminal event as an interrupted generation", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () =>
      new Response(
        stream('data: {"type":"discussion_started","file_id":"one","title":"Title"}\n\n'),
      );

    try {
      const events: unknown[] = [];
      await expect(async () => {
        for await (const event of startDiscussionStream(
          {
            material: "",
            agents: [],
            synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
            title: "",
            material_context: {
              material_type: "document",
              session_type: "exploration",
              target_language: "English",
              input_values: {},
            },
            sequential_mode: false,
          },
          {},
        )) {
          events.push(event);
        }
      }).rejects.toMatchObject({
        name: "DiscussionStreamIncompleteError",
        code: "discussion_generation_interrupted",
      } satisfies Partial<DiscussionStreamIncompleteError>);
      expect(events).toEqual([{ type: "discussion_started", file_id: "one", title: "Title" }]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
