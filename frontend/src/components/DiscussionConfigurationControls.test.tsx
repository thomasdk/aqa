import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import i18n from "../i18n";
import {
  PerspectiveConfigurationControls,
  SynthesisConfigurationControls,
  hasValidProviderSelection,
} from "./DiscussionConfigurationControls";
import type { AgentConfig, HostInfo, LocalAIStatus, SynthesisConfig } from "./types";

const host: HostInfo = {
  configuration_id: "integrated",
  label: "Integrated AI",
  url: "http://127.0.0.1:8080",
  model: "gemma-4-E2B-it",
  models: ["gemma-4-E2B-it", "gemma-4-E4B-it"],
  kind: "local_ai",
  has_api_key: false,
  is_favorite: false,
};
const selection = {
  api_host: host.url,
  host_configuration_id: host.configuration_id,
  llm_id: "gemma-4-E4B-it",
};
const agent = {
  ...selection,
  client_id: "a1",
  name: "Agent",
  prompt_id: "p1",
  color: "#123456",
  temperature: null,
  api_key: null,
  max_tokens: null,
  enabled: true,
  perspective_number: 1,
} as AgentConfig;
const synthesis = {
  ...selection,
  enabled: true,
  temperature: null,
} as SynthesisConfig;
const status = {
  runtime_installed: true,
  models: [
    {
      model_id: "gemma-4-e2b",
      api_alias: "gemma-4-E2B-it",
      installed: true,
      integrity: "verified",
    },
    {
      model_id: "gemma-4-e4b",
      api_alias: "gemma-4-E4B-it",
      installed: false,
      integrity: "unknown",
    },
  ],
} as LocalAIStatus;

function render(statusValue: LocalAIStatus) {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(
    <>
      {createElement(PerspectiveConfigurationControls, {
        agent,
        index: 0,
        perspectives: [{ id: "p1", label: "Perspective" }],
        roles: [],
        hosts: [host],
        localStatus: statusValue,
        expanded: true,
        idPrefix: "test",
        onToggleExpanded: () => undefined,
        onChange: () => undefined,
      })}
      {createElement(SynthesisConfigurationControls, {
        synthesis,
        hosts: [host],
        localStatus: statusValue,
        expanded: true,
        idPrefix: "test",
        onToggleExpanded: () => undefined,
        onChange: () => undefined,
      })}
    </>,
  );
  return container;
}

afterEach(() => void i18n.changeLanguage("de"));

describe("managed model options", () => {
  it.each(["de", "en"])("disables unavailable choices in both selectors in %s", async (locale) => {
    await i18n.changeLanguage(locale);
    const container = render(status);
    const selects = container.querySelectorAll<HTMLSelectElement>('select[aria-invalid="true"]');
    expect(selects).toHaveLength(2);
    for (const select of selects) {
      expect(select.value).toBe("");
      expect(select.options[0].textContent).toBe(
        locale === "de" ? "Nicht verfügbar: Gemma 4 E4B" : "Unavailable: Gemma 4 E4B",
      );
      expect(
        select.querySelector<HTMLOptionElement>('option[value="gemma-4-E2B-it"]')?.disabled,
      ).toBe(false);
      expect(
        select.querySelector<HTMLOptionElement>('option[value="gemma-4-E4B-it"]')?.disabled,
      ).toBe(true);
    }
    expect(hasValidProviderSelection(selection, [host], status)).toBe(false);
    expect(container.textContent).toContain(
      locale === "de"
        ? "Das ausgewählte Modell ist nicht verfügbar. Wähle ein verfügbares Modell."
        : "The selected model is unavailable. Choose an available model.",
    );
    const installed = {
      ...status,
      models: status.models.map((model) =>
        model.api_alias === "gemma-4-E4B-it"
          ? { ...model, installed: true, integrity: "verified" as const }
          : model,
      ),
    };
    expect(render(installed).querySelectorAll('select[aria-invalid="true"]')).toHaveLength(0);
    expect(hasValidProviderSelection(selection, [host], installed)).toBe(true);
  });
});
