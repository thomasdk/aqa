import { beforeEach, describe, expect, it } from "vitest";
import {
  AI_SOURCE_STORAGE_KEY,
  defaultSelectionForAISource,
  hasUsableExternalAI,
  readPreferredAISource,
  persistPreferredAISource,
  usesIntegratedAI,
} from "./aiSourceSelection";
import type { AgentConfig, SynthesisConfig } from "./types";

const hosts = [
  {
    configuration_id: "Lokale KI",
    label: "Integrierte KI",
    url: "http://127.0.0.1:8080",
    model: "gemma",
    models: ["gemma"],
    kind: "local_ai",
    has_api_key: false,
  },
  {
    configuration_id: "OpenAI",
    label: "OpenAI",
    url: "https://api.openai.example/v1",
    model: "gpt-4.1",
    models: ["gpt-4.1"],
    has_api_key: true,
    is_favorite: true,
  },
];

const integratedAgent: AgentConfig = {
  name: "Integrated perspective",
  client_id: "integrated",
  prompt_id: "conceptualization",
  color: "#52d6d0",
  temperature: null,
  llm_id: "gemma",
  api_host: "http://127.0.0.1:8080",
  host_configuration_id: "Lokale KI",
  host_label: "Integrierte KI",
  api_key: null,
  max_tokens: null,
  enabled: true,
  perspective_number: 1,
};

const externalAgent: AgentConfig = {
  ...integratedAgent,
  client_id: "external",
  api_host: "https://api.openai.example/v1",
  host_configuration_id: "OpenAI",
  host_label: "OpenAI",
};

const integratedSynthesis: SynthesisConfig = {
  enabled: true,
  api_host: "http://127.0.0.1:8080",
  llm_id: "gemma",
  host_configuration_id: "Lokale KI",
  host_label: "Integrierte KI",
  temperature: null,
};

describe("AI source selection", () => {
  beforeEach(() => window.localStorage.clear());

  it("defaults invalid and absent persisted values to Integrated AI", () => {
    expect(readPreferredAISource()).toBe("integrated");
    window.localStorage.setItem(AI_SOURCE_STORAGE_KEY, "unknown");
    expect(readPreferredAISource()).toBe("integrated");
  });

  it("persists the last selected source", () => {
    persistPreferredAISource("external");
    expect(readPreferredAISource()).toBe("external");
  });

  it("resolves the managed host or the configured external favourite", () => {
    expect(defaultSelectionForAISource("integrated", hosts)).toEqual({
      api_host: "http://127.0.0.1:8080",
      llm_id: "gemma",
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
    });
    expect(defaultSelectionForAISource("external", hosts)).toEqual({
      api_host: "https://api.openai.example/v1",
      llm_id: "gpt-4.1",
      host_configuration_id: "OpenAI",
      host_label: "OpenAI",
    });
  });

  it("does not substitute Integrated AI when External AI has no host", () => {
    expect(defaultSelectionForAISource("external", hosts.slice(0, 1))).toEqual({
      api_host: null,
      llm_id: null,
      host_configuration_id: null,
      host_label: null,
    });
  });

  it("counts only an external host with a URL and model as usable", () => {
    expect(hasUsableExternalAI(hosts)).toBe(true);
    expect(hasUsableExternalAI([{ ...hosts[1], url: "", models: [] }, hosts[0]])).toBe(false);
  });

  it("detects executable Integrated AI work from actual host assignments", () => {
    expect(usesIntegratedAI([integratedAgent], undefined, hosts)).toBe(true);
    expect(usesIntegratedAI([externalAgent], undefined, hosts)).toBe(false);
    expect(usesIntegratedAI([{ ...integratedAgent, enabled: false }], undefined, hosts)).toBe(
      false,
    );
    expect(usesIntegratedAI([externalAgent], integratedSynthesis, hosts)).toBe(true);
    expect(
      usesIntegratedAI([externalAgent], { ...integratedSynthesis, enabled: false }, hosts),
    ).toBe(false);
  });
});
