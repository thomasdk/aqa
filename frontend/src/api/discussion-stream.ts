import type { AgentConfig, MaterialContext, SynthesisConfig } from "../components/types";
import { fetchStream } from "./client";
import { type DiscussionStreamEvent, isDiscussionStreamEvent } from "./discussion-events";

export type { ContextUsage, DiscussionStreamEvent as SSEEvent } from "./discussion-events";

export type StartDiscussionParams = {
  material: string;
  agents: AgentConfig[];
  synthesis: SynthesisConfig;
  title: string;
  material_context: MaterialContext;
  sequential_mode: boolean;
};

export type ContinueDiscussionParams = {
  user_input: string;
  agents: AgentConfig[];
  focus_segment: string | null;
  sequential_mode: boolean;
  provider_rebind?: { configuration_id: string; model_id: string } | null;
};

export type DiscussionStreamOptions = {
  signal?: AbortSignal;
};

export const isSSEEvent = isDiscussionStreamEvent;

/** The server ended an SSE response without a terminal discussion event. */
export class DiscussionStreamIncompleteError extends Error {
  readonly code = "discussion_generation_interrupted";

  constructor() {
    super("Discussion stream ended before a terminal event.");
    this.name = "DiscussionStreamIncompleteError";
  }
}

export async function* parseSSEStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<DiscussionStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const parseEvent = function* (rawEvent: string): Generator<DiscussionStreamEvent> {
    const dataLines: string[] = [];
    for (const line of rawEvent.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (dataLines.length === 0) return;
    try {
      const candidate: unknown = JSON.parse(dataLines.join("\n"));
      if (isDiscussionStreamEvent(candidate)) yield candidate;
    } catch {
      // A malformed event must not discard later valid stream events.
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const trailingCR = buffer.endsWith("\r");
    if (trailingCR) buffer = buffer.slice(0, -1);
    buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (trailingCR) buffer += "\r";

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const rawEvent of events) yield* parseEvent(rawEvent);
  }

  buffer += decoder.decode();
  if (buffer) {
    yield* parseEvent(buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n"));
  }
}

async function* discussionStream(
  path: string,
  payload: StartDiscussionParams | ContinueDiscussionParams,
  options: DiscussionStreamOptions,
): AsyncGenerator<DiscussionStreamEvent> {
  const body = await fetchStream(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  let reachedTerminalEvent = false;
  for await (const event of parseSSEStream(body)) {
    if (event.type === "all_complete" || event.type === "error") reachedTerminalEvent = true;
    yield event;
  }
  if (!reachedTerminalEvent) throw new DiscussionStreamIncompleteError();
}

export function startDiscussionStream(
  params: StartDiscussionParams,
  options: DiscussionStreamOptions = {},
): AsyncGenerator<DiscussionStreamEvent> {
  return discussionStream("/api/discussions/start", params, options);
}

export function continueDiscussionStream(
  params: ContinueDiscussionParams,
  options: DiscussionStreamOptions = {},
): AsyncGenerator<DiscussionStreamEvent> {
  return discussionStream("/api/discussions/continue", params, options);
}
