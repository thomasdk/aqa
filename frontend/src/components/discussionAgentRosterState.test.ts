import { describe, expect, it } from "vitest";
import { isAgentActive, moveAgent, setAgentEnabled } from "./discussionAgentRosterState";
import type { AgentConfig } from "./types";

function makeAgent(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    name: "Agent",
    client_id: "client-1",
    prompt_id: "prompt-1",
    color: "#000000",
    temperature: null,
    llm_id: "model-a",
    api_host: "https://example.com",
    api_key: "secret",
    max_tokens: 1024,
    enabled: true,
    perspective_number: 1,
    ...overrides,
  };
}

describe("isAgentActive", () => {
  it("returns true when the agent is enabled and has a non-blank prompt_id", () => {
    expect(isAgentActive(makeAgent({ enabled: true, prompt_id: "prompt-1" }))).toBe(true);
  });

  it("returns false when the agent is disabled even with a non-blank prompt_id", () => {
    expect(isAgentActive(makeAgent({ enabled: false, prompt_id: "prompt-1" }))).toBe(false);
  });

  it("returns false when the agent is enabled but prompt_id is null", () => {
    expect(isAgentActive(makeAgent({ enabled: true, prompt_id: null }))).toBe(false);
  });

  it("returns false when the agent is enabled but prompt_id is an empty string", () => {
    expect(isAgentActive(makeAgent({ enabled: true, prompt_id: "" }))).toBe(false);
  });

  it("returns false when the agent is enabled but prompt_id is whitespace only", () => {
    expect(isAgentActive(makeAgent({ enabled: true, prompt_id: "   " }))).toBe(false);
  });
});

describe("moveAgent", () => {
  const a = makeAgent({ client_id: "a", name: "A" });
  const b = makeAgent({ client_id: "b", name: "B" });
  const c = makeAgent({ client_id: "c", name: "C" });

  it("moves the agent at index up by one when delta is -1", () => {
    const result = moveAgent([a, b, c], 1, -1);
    expect(result.map((x) => x.client_id)).toEqual(["b", "a", "c"]);
  });

  it("moves the agent at index down by one when delta is 1", () => {
    const result = moveAgent([a, b, c], 1, 1);
    expect(result.map((x) => x.client_id)).toEqual(["a", "c", "b"]);
  });

  it("returns a new array instance when the move succeeds", () => {
    const original = [a, b, c];
    const result = moveAgent(original, 0, 1);
    expect(result).not.toBe(original);
  });

  it("returns the original array when the index is the first and delta is -1", () => {
    const original = [a, b, c];
    const result = moveAgent(original, 0, -1);
    expect(result).toBe(original);
  });

  it("returns the original array when the index is the last and delta is 1", () => {
    const original = [a, b, c];
    const result = moveAgent(original, 2, 1);
    expect(result).toBe(original);
  });

  it("returns the original array when the index is negative", () => {
    const original = [a, b, c];
    const result = moveAgent(original, -1, 1);
    expect(result).toBe(original);
  });

  it("returns the original array when the index is past the end", () => {
    const original = [a, b, c];
    const result = moveAgent(original, 5, -1);
    expect(result).toBe(original);
  });

  it("returns the original array when the agents list is empty", () => {
    const original: AgentConfig[] = [];
    expect(moveAgent(original, 0, 1)).toBe(original);
  });

  it("returns the original array when delta is zero (no movement)", () => {
    const original = [a, b, c];
    expect(moveAgent(original, 1, 0)).toBe(original);
  });
});

describe("setAgentEnabled", () => {
  it("flips enabled to true and preserves every other field on a matching agent", () => {
    const original = makeAgent({
      client_id: "a",
      name: "A",
      prompt_id: "prompt-x",
      color: "#abcdef",
      temperature: 0.7,
      llm_id: "model-z",
      api_host: "https://host",
      api_key: "secret-key",
      max_tokens: 256,
      enabled: false,
    });
    const result = setAgentEnabled([original], "a", true);

    expect(result).toHaveLength(1);
    expect(result[0].enabled).toBe(true);
    expect(result[0]).toEqual({ ...original, enabled: true });
  });

  it("flips enabled to false and preserves prompt_id and all other fields", () => {
    const original = makeAgent({
      client_id: "a",
      prompt_id: "prompt-y",
      enabled: true,
    });
    const result = setAgentEnabled([original], "a", false);

    expect(result).toHaveLength(1);
    expect(result[0].enabled).toBe(false);
    expect(result[0].prompt_id).toBe("prompt-y");
    expect(result[0].prompt_id).toBe(original.prompt_id);
  });

  it("does not mutate the input array or its agents", () => {
    const original = makeAgent({ client_id: "a", enabled: false });
    const snapshot = JSON.parse(JSON.stringify(original));
    const arraySnapshot = [...[original]];
    setAgentEnabled([original], "a", true);
    expect(original).toEqual(snapshot);
    expect([original]).toEqual(arraySnapshot);
  });

  it("preserves prompt_id as null when that is the stored value", () => {
    const original = makeAgent({ client_id: "a", prompt_id: null, enabled: false });
    const result = setAgentEnabled([original], "a", true);
    expect(result[0].prompt_id).toBeNull();
  });

  it("leaves non-matching agents untouched (including their own enabled flag)", () => {
    const a = makeAgent({ client_id: "a", enabled: true });
    const b = makeAgent({ client_id: "b", enabled: false });
    const result = setAgentEnabled([a, b], "a", false);
    expect(result[0]).toEqual({ ...a, enabled: false });
    expect(result[1]).toEqual(b);
  });

  it("returns a new array reference when a matching agent is updated", () => {
    const a = makeAgent({ client_id: "a", enabled: false });
    const b = makeAgent({ client_id: "b", enabled: false });
    const original = [a, b];
    const result = setAgentEnabled(original, "a", true);
    expect(result).not.toBe(original);
  });

  it("returns a new agent reference for the updated entry but the same reference for unchanged entries", () => {
    const a = makeAgent({ client_id: "a", enabled: false });
    const b = makeAgent({ client_id: "b", enabled: false });
    const result = setAgentEnabled([a, b], "a", true);
    expect(result[0]).not.toBe(a);
    expect(result[1]).toBe(b);
  });

  it("returns a new array with the original agent unchanged when no client_id matches", () => {
    const a = makeAgent({ client_id: "a", enabled: false });
    const b = makeAgent({ client_id: "b", enabled: true });
    const original = [a, b];
    const result = setAgentEnabled(original, "missing", true);
    // No update happened; spec says return a new array so React state updates
    // can detect it, but every element must be identity-preserved.
    expect(result).not.toBe(original);
    expect(result[0]).toBe(a);
    expect(result[1]).toBe(b);
  });
});
