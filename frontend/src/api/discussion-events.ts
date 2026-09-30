import type { DiscussionStreamEventContract } from "./contracts";

/** Context measurement attached to the UI's active perspective message. */
export type ContextUsage = {
  message_id: string;
  agent_index: number;
  perspective_number?: number;
  available: boolean;
  input_tokens: number | null;
  context_tokens: number | null;
  exact: boolean;
  omitted_round_numbers: number[];
};

/**
 * Normalized event consumed by discussion UI state.
 *
 * The SSE decoder validates the generated transport DTO before returning this
 * discriminated UI model, so components do not depend on an unstructured JSON
 * payload.
 */
export type DiscussionStreamEvent =
  | { type: "discussion_started"; file_id: string; title: string }
  | { type: "user_message"; message_id: string; content: string; round_number: number }
  | ({ type: "context_usage" } & ContextUsage)
  | {
      type: "agent_start";
      message_id: string;
      agent_index: number;
      agent_name: string;
      theory_label: string;
      color: string;
      client_id: string;
      perspective_number: number;
    }
  | {
      type: "chunk";
      message_id: string;
      agent_index: number;
      perspective_number: number;
      text: string;
    }
  | {
      type: "agent_complete";
      message_id: string;
      agent_index: number;
      perspective_number: number;
      client_id: string;
      agent_name: string;
      theory_label: string;
      color: string;
      text: string;
      is_complete: boolean;
      status?: "in_progress" | "completed" | "interrupted" | "failed" | null;
      error: string | null;
      error_code?: string | null;
      error_params?: Record<string, unknown>;
      usage_available?: boolean | null;
      prompt_tokens?: number | null;
      completion_tokens?: number | null;
      total_tokens?: number | null;
    }
  | { type: "synthesis_start"; message_id: string; round_number: number }
  | { type: "synthesis_chunk"; message_id: string; text: string }
  | {
      type: "synthesis_complete";
      message_id: string;
      round_number: number;
      text: string;
      status?: "in_progress" | "completed" | "interrupted" | "failed" | null;
      error_code?: string | null;
      error_params?: Record<string, unknown>;
      usage_available?: boolean | null;
      prompt_tokens?: number | null;
      completion_tokens?: number | null;
      total_tokens?: number | null;
    }
  | {
      type: "synthesis_error";
      message_id: string;
      round_number: number;
      message: string;
      text?: string | null;
      status?: "in_progress" | "completed" | "interrupted" | "failed" | null;
      error_code?: string | null;
      error_params?: Record<string, unknown>;
    }
  | { type: "all_complete" }
  | {
      type: "error";
      message: string;
      error_code?: string | null;
      error_params?: Record<string, unknown>;
    };

/** Validate one generated stream DTO before mapping it into UI state. */
export function isDiscussionStreamEvent(value: unknown): value is DiscussionStreamEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as DiscussionStreamEventContract;
  const string = (key: keyof DiscussionStreamEventContract) => typeof event[key] === "string";
  const number = (key: keyof DiscussionStreamEventContract) => typeof event[key] === "number";
  const nullableString = (key: keyof DiscussionStreamEventContract) =>
    event[key] === null || typeof event[key] === "string";
  const optionalNullableString = (key: keyof DiscussionStreamEventContract) =>
    event[key] === undefined || nullableString(key);
  const optionalErrorParams = () =>
    event.error_params === undefined ||
    (typeof event.error_params === "object" &&
      event.error_params !== null &&
      !Array.isArray(event.error_params));
  const optionalStatus = () =>
    event.status === undefined ||
    event.status === null ||
    ["in_progress", "completed", "interrupted", "failed"].includes(event.status);

  switch (event.type) {
    case "discussion_started":
      return string("file_id") && string("title");
    case "user_message":
      return string("message_id") && string("content") && number("round_number");
    case "context_usage":
      return (
        string("message_id") &&
        number("agent_index") &&
        number("perspective_number") &&
        typeof event.available === "boolean" &&
        (event.input_tokens === null || number("input_tokens")) &&
        (event.context_tokens === null || number("context_tokens")) &&
        typeof event.exact === "boolean" &&
        Array.isArray(event.omitted_round_numbers) &&
        event.omitted_round_numbers.every((round) => typeof round === "number")
      );
    case "agent_start":
      return (
        string("message_id") &&
        number("agent_index") &&
        number("perspective_number") &&
        string("client_id") &&
        string("agent_name") &&
        string("theory_label") &&
        string("color")
      );
    case "chunk":
      return (
        string("message_id") &&
        number("agent_index") &&
        number("perspective_number") &&
        string("text")
      );
    case "agent_complete":
      return (
        string("message_id") &&
        number("agent_index") &&
        number("perspective_number") &&
        string("client_id") &&
        string("agent_name") &&
        string("theory_label") &&
        string("color") &&
        string("text") &&
        typeof event.is_complete === "boolean" &&
        nullableString("error") &&
        optionalNullableString("error_code") &&
        optionalErrorParams() &&
        optionalStatus() &&
        (event.usage_available === undefined ||
          event.usage_available === null ||
          typeof event.usage_available === "boolean")
      );
    case "synthesis_start":
      return string("message_id") && number("round_number");
    case "synthesis_chunk":
      return string("message_id") && string("text");
    case "synthesis_complete":
      return (
        string("message_id") &&
        number("round_number") &&
        string("text") &&
        optionalNullableString("error_code") &&
        optionalErrorParams() &&
        optionalStatus() &&
        (event.usage_available === undefined ||
          event.usage_available === null ||
          typeof event.usage_available === "boolean")
      );
    case "synthesis_error":
      return (
        string("message_id") &&
        number("round_number") &&
        string("message") &&
        optionalNullableString("error_code") &&
        optionalErrorParams() &&
        optionalStatus()
      );
    case "all_complete":
      return true;
    case "error":
      return string("message") && optionalNullableString("error_code") && optionalErrorParams();
    default:
      return false;
  }
}
