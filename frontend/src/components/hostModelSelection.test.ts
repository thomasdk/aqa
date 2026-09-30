import { describe, expect, it } from "vitest";
import {
  defaultHostAndPreferredModel as defaultHostAndPreferredModelImpl,
  isHostModelAvailable,
  normalizeHostModels,
  reconcileDraftAgentHostSelections as reconcileDraftAgentHostSelectionsImpl,
  resolveHostAndModelSelection as resolveHostAndModelSelectionImpl,
  selectHostAndPreferredModel as selectHostAndPreferredModelImpl,
  type AgentHostSelection,
  type HostSelectionHost,
} from "./hostModelSelection";
import type { HostInfo, LocalAIStatus } from "./types";

describe("managed model availability", () => {
  const localHost = { kind: "local_ai", models: ["gemma-4-E2B-it", "gemma-4-E4B-it"] } as HostInfo;
  const externalHost = { kind: "external", models: ["remote-model"] } as HostInfo;
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

  it("uses verified installation state for managed choices and preserves external choices", () => {
    expect(isHostModelAvailable(localHost, "gemma-4-E2B-it", status)).toBe(true);
    expect(isHostModelAvailable(localHost, "gemma-4-E4B-it", status)).toBe(false);
    expect(
      isHostModelAvailable(localHost, "gemma-4-E2B-it", { ...status, runtime_installed: false }),
    ).toBe(true);
    expect(isHostModelAvailable(localHost, "gemma-4-E2B-it", null)).toBe(false);
    expect(isHostModelAvailable(externalHost, "remote-model", null)).toBe(true);
  });
});

type TestHost = Omit<HostSelectionHost, "configuration_id"> & {
  configuration_id?: string;
};

const configuredHosts = (hosts: readonly TestHost[]): HostSelectionHost[] =>
  hosts.map((host) => ({ ...host, configuration_id: host.configuration_id ?? host.label }));

const withoutConfigurationId = (selection: AgentHostSelection): AgentHostSelection => {
  const { host_configuration_id: _configurationId, ...visibleSelection } = selection;
  return visibleSelection;
};

const resolveHostAndModelSelection = (
  currentHost: string | null,
  currentModel: string | null,
  hosts: readonly TestHost[],
) => {
  const identifiedHosts = configuredHosts(hosts);
  const configurationId = identifiedHosts.find(
    (host) => host.url === currentHost,
  )?.configuration_id;
  return withoutConfigurationId(
    resolveHostAndModelSelectionImpl(currentHost, currentModel, identifiedHosts, configurationId),
  );
};

const selectHostAndPreferredModel = (target: string | null, hosts: readonly TestHost[]) => {
  const identifiedHosts = configuredHosts(hosts);
  const configurationId = identifiedHosts.find(
    (host) => host.configuration_id === target || host.url === target,
  )?.configuration_id;
  return withoutConfigurationId(
    selectHostAndPreferredModelImpl(configurationId ?? null, identifiedHosts),
  );
};

const defaultHostAndPreferredModel = (hosts: readonly TestHost[]) =>
  withoutConfigurationId(defaultHostAndPreferredModelImpl(configuredHosts(hosts)));

function reconcileDraftAgentHostSelections<T extends AgentHostSelection>(
  agents: T[],
  previousHosts: readonly TestHost[],
  nextHosts: readonly TestHost[],
): T[] {
  const identifiedAgents = agents.map((agent) => ({
    ...agent,
    host_configuration_id: agent.host_configuration_id ?? agent.host_label ?? null,
  }));
  const result = reconcileDraftAgentHostSelectionsImpl(
    identifiedAgents,
    configuredHosts(previousHosts),
    configuredHosts(nextHosts),
  );
  if (result === identifiedAgents) return agents;
  return result.map(withoutConfigurationId) as T[];
}

describe("hostModelSelection", () => {
  it("uses stored selectable models in their stored order", () => {
    expect(
      normalizeHostModels({
        models: [" second ", "first", "second", ""],
      }),
    ).toEqual(["second", "first"]);
  });

  it("returns no selectable model for an empty host", () => {
    expect(normalizeHostModels({ model: " ", models: [] })).toEqual([]);
    expect(resolveHostAndModelSelection(null, "old-model", [])).toEqual({
      api_host: null,
      llm_id: null,
      host_label: null,
    });
  });

  it("initializes a new agent to the first real host and its preferred model", () => {
    expect(
      resolveHostAndModelSelection(null, null, [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o"] },
      ]),
    ).toEqual({ api_host: "http://ollama", llm_id: "llama3", host_label: "Ollama" });
  });

  it("preserves a selected model when it is valid for the new host", () => {
    expect(
      resolveHostAndModelSelection("https://openai", "shared", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o", "shared"] },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "shared", host_label: "OpenAI" });
  });

  it("clears a stale model on host change and selects the new host preferred model", () => {
    expect(
      resolveHostAndModelSelection("https://openai", "old-model", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o"] },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });

  it("clears the model when the replacement host has no selectable models", () => {
    expect(
      resolveHostAndModelSelection("http://removed", "old-model", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: [] },
      ]),
    ).toEqual({ api_host: "http://ollama", llm_id: null, host_label: "Ollama" });
  });

  it("initializes a fresh agent to the single favorite host and its preferred model", () => {
    expect(
      resolveHostAndModelSelection(null, null, [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        {
          label: "OpenAI",
          url: "https://openai",
          model: "gpt-4o",
          models: ["gpt-4o"],
          is_favorite: true,
        },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });

  it("falls back to the first host when no favorite is present during initialization", () => {
    expect(
      resolveHostAndModelSelection(null, null, [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o"] },
      ]),
    ).toEqual({ api_host: "http://ollama", llm_id: "llama3", host_label: "Ollama" });
  });

  it("ignores the favorite flag when the current host is valid", () => {
    expect(
      resolveHostAndModelSelection("http://ollama", "qwen", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        {
          label: "OpenAI",
          url: "https://openai",
          model: "gpt-4o",
          models: ["gpt-4o"],
          is_favorite: true,
        },
      ]),
    ).toEqual({ api_host: "http://ollama", llm_id: "qwen", host_label: "Ollama" });
  });

  it("selects the first favorite when multiple favorites are present", () => {
    expect(
      resolveHostAndModelSelection(null, null, [
        {
          label: "OpenAI",
          url: "https://openai",
          model: "gpt-4o",
          models: ["gpt-4o", "gpt-4o-mini"],
          is_favorite: true,
        },
        {
          label: "Ollama",
          url: "http://ollama",
          model: "llama3",
          models: ["llama3", "qwen"],
          is_favorite: true,
        },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });
});

describe("selectHostAndPreferredModel", () => {
  it("keeps managed and external hosts distinct when their display labels collide", () => {
    const collidingHosts: HostSelectionHost[] = [
      {
        configuration_id: "Lokale KI",
        label: "Integrierte KI",
        url: "http://managed",
        model: "gemma",
        models: ["gemma"],
      },
      {
        configuration_id: "Integrierte KI",
        label: "Integrierte KI",
        url: "https://external",
        model: "external-model",
        models: ["external-model"],
      },
    ];

    expect(selectHostAndPreferredModelImpl("Lokale KI", collidingHosts)).toMatchObject({
      host_configuration_id: "Lokale KI",
      host_label: "Integrierte KI",
      api_host: "http://managed",
      llm_id: "gemma",
    });
    expect(selectHostAndPreferredModelImpl("Integrierte KI", collidingHosts)).toMatchObject({
      host_configuration_id: "Integrierte KI",
      api_host: "https://external",
      llm_id: "external-model",
    });
  });

  it("selects the requested stable label when two hosts share a URL and model", () => {
    expect(
      selectHostAndPreferredModel("B", [
        { label: "A", url: "https://shared", model: "shared", models: ["shared"] },
        { label: "B", url: "https://shared", model: "shared", models: ["shared"] },
      ]),
    ).toEqual({ api_host: "https://shared", llm_id: "shared", host_label: "B" });
  });

  it("selects the target host's preferred model unconditionally", () => {
    expect(
      selectHostAndPreferredModel("https://openai", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o", "shared"] },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });

  it("resets a shared existing model to the target host's preferred model", () => {
    expect(
      selectHostAndPreferredModel("https://openai", [
        { label: "Ollama", url: "http://ollama", model: "shared", models: ["shared"] },
        { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o", "shared"] },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });

  it("returns nulls when the target host is unknown", () => {
    expect(
      selectHostAndPreferredModel("http://missing", [
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3"] },
      ]),
    ).toEqual({ api_host: null, llm_id: null, host_label: null });
  });
});

describe("defaultHostAndPreferredModel", () => {
  it("returns nulls for an empty catalogue", () => {
    expect(defaultHostAndPreferredModel([])).toEqual({
      api_host: null,
      llm_id: null,
      host_label: null,
    });
  });

  it("picks the first favourite host and its first stored model", () => {
    expect(
      defaultHostAndPreferredModel([
        { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
        {
          label: "OpenAI",
          url: "https://openai",
          model: "gpt-4o",
          models: ["gpt-4o"],
          is_favorite: true,
        },
      ]),
    ).toEqual({ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" });
  });
});

describe("reconcileDraftAgentHostSelections", () => {
  it("moves only agents following the old global default when the favourite changes", () => {
    const beforeHosts = [
      { label: "Ollama", url: "http://old", model: "old-default", models: ["old-default"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o", "shared"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      { label: "Ollama", url: "http://new", model: "new-default", models: ["new-default"] },
      { label: "OpenAI", url: "https://openai", model: "gpt-4o", models: ["gpt-4o", "shared"] },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "http://old", llm_id: "old-default", host_label: "Ollama" },
        { api_host: "http://explicit", llm_id: "manual-model", host_label: "Manual" },
      ],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([
      { api_host: "http://new", llm_id: "new-default", host_label: "Ollama" },
      { api_host: "http://explicit", llm_id: "manual-model", host_label: "Manual" },
    ]);
  });

  it("updates an agent on a favourite host's old first model when only that model changes", () => {
    const beforeHosts = [
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o", "shared"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-5",
        models: ["gpt-5", "shared"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [{ api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" }],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([{ api_host: "https://openai", llm_id: "gpt-5", host_label: "OpenAI" }]);
  });

  it("preserves a valid explicit selection when a different host becomes favourite", () => {
    const beforeHosts = [
      { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3"] },
      {
        label: "Ollama2",
        url: "http://ollama2",
        model: "gemma",
        models: ["gemma"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "http://ollama", llm_id: "llama3", host_label: "Ollama" },
        { api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" },
      ],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([
      { api_host: "http://ollama", llm_id: "llama3", host_label: "Ollama" },
      { api_host: "http://ollama2", llm_id: "gemma", host_label: "Ollama2" },
    ]);
  });

  it("follows a non-favourite host's new first model while leaving a valid non-first selection untouched", () => {
    const beforeHosts = [
      { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      { label: "Ollama", url: "http://ollama", model: "qwen", models: ["qwen", "llama3"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "http://ollama", llm_id: "llama3", host_label: "Ollama" },
        { api_host: "http://ollama", llm_id: "qwen", host_label: "Ollama" },
      ],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([
      { api_host: "http://ollama", llm_id: "qwen", host_label: "Ollama" },
      { api_host: "http://ollama", llm_id: "qwen", host_label: "Ollama" },
    ]);
  });

  it("applies the same per-host preferred-model rule to a managed Local AI host", () => {
    const beforeHosts = [
      {
        label: "Local AI",
        url: "local-ai://managed",
        model: "gemma-old",
        models: ["gemma-old", "gemma-extra"],
        kind: "local_ai",
      },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      {
        label: "Local AI",
        url: "local-ai://managed",
        model: "gemma-new",
        models: ["gemma-new", "gemma-extra"],
        kind: "local_ai",
      },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "local-ai://managed", llm_id: "gemma-old", host_label: "Local AI" },
        { api_host: "local-ai://managed", llm_id: "gemma-extra", host_label: "Local AI" },
      ],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([
      { api_host: "local-ai://managed", llm_id: "gemma-new", host_label: "Local AI" },
      { api_host: "local-ai://managed", llm_id: "gemma-extra", host_label: "Local AI" },
    ]);
  });

  it("repairs a deleted selected host and a removed model independently", () => {
    const beforeHosts = [
      { label: "Removed", url: "http://removed", model: "old-model", models: ["old-model"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o", "shared"],
        is_favorite: true,
      },
    ];
    const afterHosts = [
      { label: "Ollama", url: "http://ollama", model: "qwen", models: ["qwen", "llama3"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "http://removed", llm_id: "old-model", host_label: "Removed" },
        { api_host: "https://openai", llm_id: "shared", host_label: "OpenAI" },
      ],
      beforeHosts,
      afterHosts,
    );

    expect(next).toEqual([
      { api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" },
      { api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" },
    ]);
  });

  it("returns nulls for every agent when the new catalogue is empty", () => {
    const beforeHosts = [
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o"],
        is_favorite: true,
      },
    ];

    const next = reconcileDraftAgentHostSelections(
      [
        { api_host: "https://openai", llm_id: "gpt-4o", host_label: "OpenAI" },
        { api_host: "https/openai", llm_id: "shared", host_label: "Malformed" },
      ],
      beforeHosts,
      [],
    );

    expect(next).toEqual([
      { api_host: null, llm_id: null, host_label: null },
      { api_host: null, llm_id: null, host_label: null },
    ]);
  });

  it("returns the original array and agent references when the catalogue is unchanged", () => {
    const hosts = [
      { label: "Ollama", url: "http://ollama", model: "llama3", models: ["llama3", "qwen"] },
      {
        label: "OpenAI",
        url: "https://openai",
        model: "gpt-4o",
        models: ["gpt-4o", "shared"],
        is_favorite: true,
      },
    ];
    const agents = [
      { api_host: "http://ollama", llm_id: "llama3", extra: "draft-id-1" },
      { api_host: "https://openai", llm_id: "shared", extra: "draft-id-2" },
    ];

    const next = reconcileDraftAgentHostSelections(agents, hosts, hosts);

    expect(next).toBe(agents);
    expect(next[0]).toBe(agents[0]);
    expect(next[1]).toBe(agents[1]);
  });
});
