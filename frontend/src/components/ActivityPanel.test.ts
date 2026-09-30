import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, createElement, Fragment, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import type { AgentConfig, DiscussionMessage, HostInfo, Perspective, Role } from "./types";
import ActivityPanel, {
  EXTERNAL_AI_LONG_WAIT_NOTICE_SECONDS,
  getAgentActivityStatus,
  getCompletedRoundProgress,
  getContextWindowPresentation,
  getProgressPresentation,
  type AgentLifecycle,
} from "./ActivityPanel";
import i18n from "../i18n";

const agents: AgentConfig[] = [
  {
    name: "Agent 1",
    client_id: "a1",
    prompt_id: "p1",
    color: "#1",
    temperature: 0.7,
    llm_id: null,
    api_host: null,
    api_key: null,
    max_tokens: null,
    enabled: true,
    perspective_number: 1,
  },
  {
    name: "Agent 2",
    client_id: "a2",
    prompt_id: "p2",
    color: "#2",
    temperature: 0.7,
    llm_id: null,
    api_host: null,
    api_key: null,
    max_tokens: null,
    enabled: true,
    perspective_number: 2,
  },
  {
    name: "Agent 3",
    client_id: "a3",
    prompt_id: "p3",
    color: "#3",
    temperature: 0.7,
    llm_id: null,
    api_host: null,
    api_key: null,
    max_tokens: null,
    enabled: true,
    perspective_number: 3,
  },
];

const currentTime = () => Date.now();

function TimerFixture() {
  const [isDiscussionVisible, setIsDiscussionVisible] = useState(true);
  const [isSynthesisStreaming, setIsSynthesisStreaming] = useState(false);
  const [round, setRound] = useState<{
    isStreaming: boolean;
    startedAt: number | null;
    elapsedSeconds: number | null;
    completed: boolean;
    status: "completed" | "failed" | "interrupted";
    sessionName: string;
  }>({
    isStreaming: true,
    startedAt: 0,
    elapsedSeconds: 0,
    completed: false,
    status: "completed",
    sessionName: "First discussion",
  });
  const finishRound = () => {
    setIsSynthesisStreaming(false);
    setRound((previous) => ({
      ...previous,
      isStreaming: false,
      startedAt: null,
      elapsedSeconds: Math.floor((Date.now() - (previous.startedAt ?? Date.now())) / 1000),
      completed: true,
      status: "completed",
    }));
  };
  const endRound = (status: "failed" | "interrupted") => {
    setIsSynthesisStreaming(false);
    setRound((previous) => ({
      ...previous,
      isStreaming: false,
      startedAt: null,
      elapsedSeconds: Math.floor((Date.now() - (previous.startedAt ?? Date.now())) / 1000),
      completed: true,
      status,
    }));
  };
  const startNewRound = () =>
    setRound((previous) => ({
      ...previous,
      isStreaming: true,
      startedAt: currentTime(),
      elapsedSeconds: 0,
      completed: false,
    }));
  const reopen = (
    status: "completed" | "failed" | "interrupted",
    sessionName = round.sessionName,
  ) =>
    setRound({
      isStreaming: false,
      startedAt: null,
      elapsedSeconds: null,
      completed: true,
      status,
      sessionName,
    });

  const completedMessages: DiscussionMessage[] = round.completed
    ? [
        {
          id: "completed-agent",
          role: "agent",
          content: round.sessionName,
          round_number: 1,
          agent_name: agents[0].name,
          theory_label: null,
          color: agents[0].color,
          agent_index: 0,
          perspective_number: 1,
          client_id: agents[0].client_id,
          note: "",
          include_in_agent_context: true,
        },
      ]
    : [];

  return createElement(
    Fragment,
    null,
    createElement(
      "button",
      { type: "button", onClick: () => setIsDiscussionVisible(false) },
      "Other workbench tab",
    ),
    createElement(
      "button",
      { type: "button", onClick: () => setIsDiscussionVisible(true) },
      "Discussion tab",
    ),
    createElement(
      "button",
      {
        type: "button",
        onClick: startNewRound,
      },
      "Start new round",
    ),
    createElement("button", { type: "button", onClick: finishRound }, "Complete round"),
    createElement(
      "button",
      { type: "button", onClick: () => endRound("interrupted") },
      "Stop round",
    ),
    createElement("button", { type: "button", onClick: () => endRound("failed") }, "Fail round"),
    createElement(
      "button",
      { type: "button", onClick: () => reopen("completed") },
      "Reopen completed",
    ),
    createElement("button", { type: "button", onClick: () => reopen("failed") }, "Reopen failed"),
    createElement(
      "button",
      { type: "button", onClick: () => reopen("interrupted") },
      "Reopen interrupted",
    ),
    createElement(
      "button",
      { type: "button", onClick: () => reopen("completed", "Other discussion") },
      "Switch discussion",
    ),
    createElement(
      "button",
      { type: "button", onClick: () => setIsSynthesisStreaming(true) },
      "Start synthesis",
    ),
    isDiscussionVisible
      ? createElement(ActivityPanel, {
          isStreaming: round.isStreaming,
          currentAgents: [agents[0]],
          agentLifecycle: { a1: round.isStreaming ? "streaming" : "complete" },
          messages: completedMessages,
          roundStartedAt: round.startedAt,
          roundElapsedSeconds: round.elapsedSeconds,
          roundStatus: round.status,
          synthesis: { enabled: true, api_host: null, llm_id: null, temperature: null },
          streamingSynthesis: isSynthesisStreaming ? { error: null } : null,
        })
      : null,
  );
}

function mountTimerFixture(): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(createElement(TimerFixture)));
  return { container, root };
}

describe("ActivityPanel provider history", () => {
  it("places frozen round configuration below the setup rows in a compact table", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [agents[0]],
        agentLifecycle: {},
        messages: [],
        roundProviderProvenance: [
          {
            round_number: 1,
            providers: [
              {
                kind: "perspective" as const,
                client_id: "a1",
                host_configuration_id: "host-a",
                host_label: "Host A",
                api_host: "https://host-a.example/v1",
                model_id: "model-a",
                perspective_number: 1,
                prompt_id: "historical-role",
                prompt_label: "Historical Role",
                temperature: 0.7,
              },
              {
                kind: "synthesis" as const,
                client_id: null,
                host_configuration_id: "host-b",
                host_label: "Host B",
                api_host: "https://host-b.example/v1",
                model_id: "model-b",
                perspective_number: null,
                prompt_id: "discussion.synthesis",
                prompt_label: "Synthesis",
                temperature: null,
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain('class="provider-history"');
    expect(html).toContain("<table>");
    expect(html).toContain("Perspektive / Synthese");
    expect(html).toContain("Historical Role");
    expect(html).toContain("Synthese");
    expect(html).toContain("Host A");
    expect(html).toContain("model-b");
    expect(html).not.toContain("https://host-a.example/v1");
    expect(html.indexOf('class="agent-status-list"')).toBeLessThan(
      html.indexOf('class="provider-history"'),
    );
  });
});

describe("ActivityPanel round timer lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(0));
  });

  afterEach(() => {
    document.body.replaceChildren();
    vi.useRealTimers();
  });

  it("keeps the active round duration across a Discussion unmount, resets for a new round, and stops after terminal states", () => {
    const { container, root } = mountTimerFixture();
    const timerText = () => container.querySelector(".activity-timer")?.textContent;
    const clickButton = (label: string) =>
      act(() =>
        Array.from(container.querySelectorAll("button"))
          .find((button) => button.textContent === label)
          ?.click(),
      );

    act(() => vi.advanceTimersByTime(8_000));
    expect(timerText()).toContain("0:08");

    clickButton("Other workbench tab");
    expect(container.querySelector(".activity-panel")).toBeNull();
    act(() => vi.advanceTimersByTime(5_000));
    clickButton("Discussion tab");
    expect(timerText()).toContain("0:13");

    clickButton("Start synthesis");
    expect(container.querySelector('[data-synthesis-state="writing"]')).not.toBeNull();
    act(() => vi.advanceTimersByTime(1_000));
    expect(timerText()).toContain("0:14");

    clickButton("Complete round");
    expect(timerText()).toContain("0:14");
    expect(vi.getTimerCount()).toBe(0);

    clickButton("Start new round");
    expect(timerText()).toContain("0:00");
    act(() => vi.advanceTimersByTime(2_000));
    expect(timerText()).toContain("0:02");

    clickButton("Stop round");
    expect(timerText()).toContain("0:02");
    expect(vi.getTimerCount()).toBe(0);

    act(() => root.unmount());
  });

  it("hides unknown durations after reopening every terminal outcome and switching discussions", () => {
    const { container, root } = mountTimerFixture();
    const timer = () => container.querySelector(".activity-timer");
    const clickButton = (label: string) =>
      act(() =>
        Array.from(container.querySelectorAll("button"))
          .find((button) => button.textContent === label)
          ?.click(),
      );

    act(() => vi.advanceTimersByTime(3_000));
    clickButton("Complete round");
    expect(timer()?.textContent).toContain("0:03");

    for (const [button, status] of [
      ["Reopen completed", "abgeschlossen"],
      ["Reopen failed", "fehlgeschlagen"],
      ["Reopen interrupted", "unterbrochen"],
    ]) {
      clickButton(button);
      expect(container.querySelector(".activity-round")?.textContent).toContain(status);
      expect(timer()).toBeNull();
    }

    clickButton("Switch discussion");
    expect(timer()).toBeNull();

    clickButton("Start new round");
    expect(timer()?.textContent).toContain("0:00");
    clickButton("Complete round");
    expect(timer()?.textContent).toContain("0:00");
    act(() => vi.advanceTimersByTime(1_000));
    expect(timer()?.textContent).toContain("0:00");

    act(() => root.unmount());
  });

  it("freezes measured failures and Stop at their elapsed values", () => {
    const { container, root } = mountTimerFixture();
    const timerText = () => container.querySelector(".activity-timer")?.textContent;
    const clickButton = (label: string) =>
      act(() =>
        Array.from(container.querySelectorAll("button"))
          .find((button) => button.textContent === label)
          ?.click(),
      );

    act(() => vi.advanceTimersByTime(4_000));
    clickButton("Fail round");
    expect(container.querySelector(".activity-round")?.textContent).toContain("fehlgeschlagen");
    expect(timerText()).toContain("0:04");
    act(() => vi.advanceTimersByTime(2_000));
    expect(timerText()).toContain("0:04");

    clickButton("Start new round");
    act(() => vi.advanceTimersByTime(5_000));
    clickButton("Stop round");
    expect(container.querySelector(".activity-round")?.textContent).toContain("unterbrochen");
    expect(timerText()).toContain("0:05");
    act(() => vi.advanceTimersByTime(2_000));
    expect(timerText()).toContain("0:05");

    act(() => root.unmount());
  });

  it("shows one non-terminal External AI long-wait status while Stop remains available", () => {
    const onStop = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const render = (isStreaming: boolean, usesIntegratedAI = false) =>
      act(() =>
        root.render(
          createElement(ActivityPanel, {
            isStreaming,
            usesIntegratedAI,
            currentAgents: [agents[0]],
            agentLifecycle: { a1: isStreaming ? "streaming" : "complete" },
            messages: [],
            roundStartedAt: isStreaming ? 0 : null,
            roundElapsedSeconds: isStreaming ? 0 : EXTERNAL_AI_LONG_WAIT_NOTICE_SECONDS,
            onStop,
          }),
        ),
      );

    render(true);
    act(() => vi.advanceTimersByTime((EXTERNAL_AI_LONG_WAIT_NOTICE_SECONDS - 1) * 1_000));
    expect(container.querySelector('[role="status"]')).toBeNull();

    act(() => vi.advanceTimersByTime(1_000));
    const notice = container.querySelector('[role="status"]');
    expect(notice?.textContent).toContain("Das Modell braucht länger für die Antwort.");
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(1);

    act(() => vi.advanceTimersByTime(5 * 60 * 1_000));
    expect(container.querySelector('[role="status"]')).toBe(notice);
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(1);

    const stop = container.querySelector<HTMLButtonElement>(".activity-stop-btn");
    expect(stop?.disabled).toBe(false);
    act(() => stop?.click());
    expect(onStop).toHaveBeenCalledOnce();

    render(false);
    expect(container.querySelector('[role="status"]')).toBeNull();

    render(true, true);
    expect(container.textContent).not.toContain("Das Modell braucht länger für die Antwort.");
    expect(container.textContent).toContain("Integrated AI");
    act(() => root.unmount());
  });
});

describe("ActivityPanel next-round configuration", () => {
  const hosts: HostInfo[] = [
    {
      configuration_id: "host-a",
      label: "Host A",
      url: "http://host-a",
      model: "model-a",
      models: ["model-a"],
      kind: "openai",
      has_api_key: false,
      is_favorite: false,
    },
    {
      configuration_id: "host-b",
      label: "Host B",
      url: "http://host-b",
      model: "model-b",
      models: ["model-b"],
      kind: "openai",
      has_api_key: false,
      is_favorite: false,
    },
  ];
  const perspectives: Perspective[] = [
    { id: "p1", label: "Perspective 1" },
    { id: "p2", label: "Perspective 2" },
    { id: "p3", label: "Perspective 3" },
  ];
  const roles: Role[] = perspectives.map((perspective) => ({
    id: perspective.id,
    label: perspective.label,
    description: `${perspective.label} description`,
    editable: true,
    is_shipped: false,
    origin: "custom",
    role: "Role instructions",
    task: "Task instructions",
    output_format: "Output instructions",
  }));
  const completedMessage: DiscussionMessage = {
    id: "completed",
    role: "agent",
    content: "Done",
    round_number: 1,
    agent_name: "Agent 1",
    theory_label: null,
    color: "#111",
    agent_index: 0,
    perspective_number: 1,
    client_id: "a1",
    note: "",
    include_in_agent_context: true,
  };

  function mountConfiguration(onApply: (next: AgentConfig[]) => Promise<boolean>) {
    const staleAgents = agents.slice(0, 2).map((agent, index) => ({
      ...agent,
      temperature: index === 0 ? null : agent.temperature,
      host_configuration_id: "deleted-host",
      api_host: "http://deleted",
      llm_id: "deleted-model",
    }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const render = (isStreaming = false) =>
      act(() =>
        root.render(
          createElement(ActivityPanel, {
            isStreaming,
            currentAgents: staleAgents,
            agentLifecycle: {},
            messages: [completedMessage],
            synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
            perspectives,
            roles,
            hosts,
            configurationOpenRequest: 1,
            onApplyNextRoundConfiguration: (next) => onApply(next),
          }),
        ),
      );
    render();
    return { container, root, render };
  }

  it("focuses invalid inline rows, then saves distinct replacements automatically", async () => {
    const apply = vi.fn<(next: AgentConfig[]) => Promise<boolean>>(async () => true);
    const { container, root } = mountConfiguration(apply);
    expect(document.activeElement).toBe(
      container.querySelector(".configuration-recovery-guidance"),
    );
    expect(container.querySelector(".configuration-recovery-guidance")?.textContent).toContain(
      "Aktivität",
    );
    expect(container.querySelectorAll('.agent-config-advanced[aria-invalid="true"]')).toHaveLength(
      0,
    );
    expect(container.querySelectorAll(".agent-config-row.is-invalid")).toHaveLength(2);
    expect(
      container.querySelectorAll('.agent-config-row select[aria-invalid="true"]'),
    ).not.toHaveLength(0);
    expect(container.querySelectorAll(".agent-config-advanced")).toHaveLength(2);
    expect(container.querySelector(".agent-status-list")).not.toBeNull();

    const hostSelects = () =>
      Array.from(
        container.querySelectorAll<HTMLSelectElement>(
          ".activity-inline-config .agent-config-advanced .agent-config-field:first-of-type select",
        ),
      );
    expect(hostSelects()).toHaveLength(2);
    act(() => {
      const roleSelect = container.querySelector<HTMLSelectElement>(
        "#activity-perspective-slot-a1",
      )!;
      roleSelect.value = "p3";
      roleSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    act(() => {
      container
        .querySelector<HTMLInputElement>('#activity-perspective-options-a1 input[type="checkbox"]')!
        .click();
    });
    act(() => {
      hostSelects()[0].value = "host-a";
      hostSelects()[0].dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      hostSelects()[1].value = "host-b";
      hostSelects()[1].dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });

    expect(apply).toHaveBeenCalledTimes(1);
    const appliedAgents = apply.mock.calls[0][0];
    expect(appliedAgents[0]).toMatchObject({
      prompt_id: "p3",
      temperature: 1,
      host_configuration_id: "host-a",
      llm_id: "model-a",
    });
    expect(appliedAgents[1]).toMatchObject({ host_configuration_id: "host-b", llm_id: "model-b" });
    expect(container.querySelectorAll(".activity-inline-config")).toHaveLength(2);
    expect(container.querySelector(".activity-round-configuration")).toBeNull();
    const firstOptions = container.querySelector("#activity-perspective-options-a1")!;
    const fieldLabels = Array.from(
      firstOptions.querySelectorAll<HTMLElement>(".agent-config-field > span"),
    ).map((label) => label.textContent);
    expect(fieldLabels).toEqual(["Host", "Modell"]);
    const modelSelect = firstOptions.querySelectorAll("select")[1];
    const temperatureToggle =
      firstOptions.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(
      modelSelect.compareDocumentPosition(temperatureToggle) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await act(async () => {
      container
        .querySelector<HTMLInputElement>(
          '.agent-status-row[data-client-id="a1"] .agent-status-active-toggle input',
        )!
        .click();
      await Promise.resolve();
    });
    expect(apply).toHaveBeenCalledTimes(2);
    expect(apply.mock.calls[1][0][0].enabled).toBe(false);
    act(() => root.unmount());
  });

  it("lets every row toggle its own options without duplicate Apply or Cancel controls", () => {
    const apply = vi.fn<(next: AgentConfig[]) => Promise<boolean>>(async () => true);
    const { container, root } = mountConfiguration(apply);
    const buttons = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".agent-status-options-btn"),
    );
    expect(buttons).toHaveLength(3);
    expect(buttons.slice(0, 2).map((button) => button.getAttribute("aria-expanded"))).toEqual([
      "true",
      "true",
    ]);
    expect(buttons[2].getAttribute("aria-expanded")).toBe("false");
    expect(
      buttons[2].compareDocumentPosition(
        container.querySelector(".synthesis-status-toggle") as Node,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    act(() => buttons[0].click());
    expect(buttons[0].getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("#activity-perspective-options-a1")).toBeNull();
    expect(container.querySelector("#activity-perspective-options-a2")).not.toBeNull();

    act(() => buttons[0].click());
    expect(buttons[0].getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector("#activity-perspective-options-a1")).not.toBeNull();

    act(() => buttons[2].click());
    expect(buttons[2].getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector("#activity-synthesis-options")).not.toBeNull();
    expect(container.querySelector(".activity-round-configuration")).toBeNull();
    expect(container.textContent).not.toContain("Optionen bearbeiten");
    expect(container.textContent).not.toContain("Anwenden");
    expect(container.textContent).not.toContain("Abbrechen");
    expect(apply).not.toHaveBeenCalled();
    act(() => root.unmount());
  });

  it("closes every open options region when generation starts", () => {
    const apply = vi.fn<(next: AgentConfig[]) => Promise<boolean>>(async () => true);
    const { container, root, render } = mountConfiguration(apply);
    const synthesisButton = container.querySelectorAll<HTMLButtonElement>(
      ".agent-status-options-btn",
    )[2];
    act(() => synthesisButton.click());
    expect(container.querySelectorAll(".activity-inline-config")).toHaveLength(3);

    render(true);

    expect(container.querySelectorAll(".activity-inline-config")).toHaveLength(0);
    expect(
      Array.from(container.querySelectorAll<HTMLButtonElement>(".agent-status-options-btn")).every(
        (button) => button.getAttribute("aria-expanded") === "false",
      ),
    ).toBe(true);
    act(() => root.unmount());
  });
});

describe("getAgentActivityStatus", () => {
  it("keeps not-yet-started agents waiting instead of marking them done", () => {
    const lifecycle: AgentLifecycle = {
      a1: "streaming",
      a2: "waiting",
      a3: "waiting",
    };

    const result = getAgentActivityStatus(agents, lifecycle, [], true, 0);

    expect(result.statuses.map((status) => status.state)).toEqual([
      "streaming",
      "waiting",
      "waiting",
    ]);
    expect(result.completedCount).toBe(0);
  });

  it("counts only successful agents in live progress", () => {
    const lifecycle: AgentLifecycle = {
      a1: "complete",
      a2: "error",
      a3: "waiting",
    };

    const result = getAgentActivityStatus(agents, lifecycle, [], true, 0);

    expect(result.statuses.map((status) => status.state)).toEqual(["complete", "error", "waiting"]);
    expect(result.completedCount).toBe(1);
  });
});

describe("getCompletedRoundProgress", () => {
  it("uses terminal messages rather than the editable current roster", () => {
    const result = getCompletedRoundProgress(
      [
        {
          id: "a1",
          role: "agent",
          content: "Alpha",
          round_number: 1,
          agent_name: "Agent 1",
          theory_label: null,
          color: "#1",
          agent_index: 0,
          perspective_number: 1,
          client_id: "a1",
          note: "",
          include_in_agent_context: true,
        },
        {
          id: "a2-error",
          role: "agent",
          content: "",
          round_number: 1,
          agent_name: "Agent 2",
          theory_label: null,
          color: "#2",
          agent_index: 1,
          perspective_number: 2,
          client_id: "a2",
          note: "",
          include_in_agent_context: true,
          error: "Unavailable",
        },
        {
          id: "s1",
          role: "synthesis",
          content: "Summary",
          round_number: 1,
          agent_name: null,
          theory_label: null,
          color: null,
          agent_index: null,
          perspective_number: null,
          client_id: null,
          note: "",
          include_in_agent_context: false,
        },
      ],
      1,
    );

    expect(result).toEqual({ terminalAgentCount: 2, hasTerminalSynthesis: true });
  });
});

describe("getProgressPresentation", () => {
  it("keeps the actual zero-of-total progress while streaming", () => {
    const presentation = getProgressPresentation({
      isStreaming: true,
      completedCount: 0,
      totalAgents: 3,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(0);
    expect(presentation.ariaValueMax).toBe(3);
    expect(presentation.ariaValueText).toBe("0 von 3 Perspektiven fertig");
    expect(presentation.percent).toBe(0);
  });

  it("keeps actual partial progress while the remaining agents stream", () => {
    const presentation = getProgressPresentation({
      isStreaming: true,
      completedCount: 1,
      totalAgents: 3,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(1);
    expect(presentation.ariaValueMax).toBe(3);
    expect(presentation.ariaValueText).toBe("1 von 3 Perspektiven fertig");
    expect(presentation.percent).toBeCloseTo(100 / 3, 5);
  });

  it("remains determinate when streaming with zero configured agents", () => {
    const presentation = getProgressPresentation({
      isStreaming: true,
      completedCount: 0,
      totalAgents: 0,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(0);
    expect(presentation.ariaValueMax).toBe(0);
    expect(presentation.ariaValueText).toBe("Keine Perspektiven konfiguriert");
    expect(presentation.percent).toBe(0);
  });

  it("exposes a numeric value when idle and partially complete", () => {
    const presentation = getProgressPresentation({
      isStreaming: false,
      completedCount: 1,
      totalAgents: 3,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(1);
    expect(presentation.ariaValueMax).toBe(3);
    expect(presentation.ariaValueText).toBe("1 von 3 Perspektiven fertig");
    expect(presentation.percent).toBeCloseTo(100 / 3, 5);
  });

  it("reports the full progress when idle and all agents completed", () => {
    const presentation = getProgressPresentation({
      isStreaming: false,
      completedCount: 3,
      totalAgents: 3,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(3);
    expect(presentation.ariaValueMax).toBe(3);
    expect(presentation.ariaValueText).toBe("3 von 3 Perspektiven fertig");
    expect(presentation.percent).toBe(100);
  });

  it("stays determinate with zero count when idle and no agents are configured", () => {
    const presentation = getProgressPresentation({
      isStreaming: false,
      completedCount: 0,
      totalAgents: 0,
    });

    expect(presentation.mode).toBe("determinate");
    expect(presentation.ariaValueNow).toBe(0);
    expect(presentation.ariaValueMax).toBe(0);
    expect(presentation.percent).toBe(0);
  });
});

describe("getContextWindowPresentation", () => {
  it.each([
    [0, 65_536, { percentage: 0, radialPercentage: 0, pressure: "info" }],
    [45_875, 65_536, { percentage: 70, radialPercentage: 70, pressure: "warning" }],
    [58_982, 65_536, { percentage: 90, radialPercentage: 90, pressure: "danger" }],
    [98_304, 65_536, { percentage: 150, radialPercentage: 100, pressure: "danger" }],
  ])("maps %i used of %i available tokens", (used, available, expected) => {
    expect(getContextWindowPresentation(used, available)).toEqual(expected);
  });

  it.each([null, 0, -1])("returns no pressure signal for an invalid window (%s)", (window) => {
    expect(getContextWindowPresentation(120, window)).toBeNull();
  });
});

describe("ActivityPanel render (integrated compact roster)", () => {
  const twoAgents: AgentConfig[] = [
    {
      name: "Alpha",
      client_id: "alpha",
      prompt_id: "p1",
      color: "#111",
      temperature: null,
      llm_id: null,
      api_host: null,
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 1,
    },
    {
      name: "Beta",
      client_id: "beta",
      prompt_id: "p2",
      color: "#222",
      temperature: null,
      llm_id: null,
      api_host: null,
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 2,
    },
  ];

  it("renders a single integrated agent-status-list while idle with no roster section or bullet list", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: twoAgents,
        agentLifecycle: {},
        messages: [],
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toMatch(/<div[^>]*class="[^"]*agent-status-list[^"]*"/);
    expect(html).not.toMatch(/class="[^"]*agent-roster/);
    expect(html).not.toMatch(/<ul[^>]*class="[^"]*agent-roster/);
    expect(html).not.toMatch(/<li[^>]*class="[^"]*agent-roster/);
    expect(html).not.toMatch(/class="[^"]*agent-roster-header/);
    expect(html).toContain("Alpha");
    expect(html).toContain("Beta");
    expect(html.match(/<input[^>]*type="checkbox"[^>]*>/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    expect(html).toContain('aria-label="Alpha nach oben"');
    expect(html).toContain('aria-label="Alpha nach unten"');
    expect(html).toContain("disabled=");
  });

  it("keeps the inactive agent visible in the integrated list but excludes it from progress", () => {
    const roster: AgentConfig[] = [
      { ...twoAgents[0], enabled: true },
      { ...twoAgents[1], enabled: false },
    ];
    const completedMessages: DiscussionMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "Frage",
        round_number: 1,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: true,
        client_id: null,
      },
      {
        id: "a1",
        role: "agent",
        content: "Antwort Alpha",
        round_number: 1,
        agent_name: "Alpha",
        theory_label: "Systemtheorie",
        color: "#111",
        agent_index: 0,
        perspective_number: 1,
        note: "",
        include_in_agent_context: true,
        client_id: "alpha",
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: roster,
        agentLifecycle: {},
        messages: completedMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("Alpha");
    expect(html).toContain("Beta");
    expect(html).toMatch(/class="[^"]*agent-status-row[^"]*is-inactive[^"]*"/);
    expect(html).not.toMatch(/<li[^>]*class="[^"]*agent-roster/);
    expect(html).toContain("1/1 Perspektiven");
    expect(html).not.toContain("1/2 Perspektiven");
  });

  it("labels an empty inactive slot as None instead of repeating its slot name", async () => {
    await i18n.changeLanguage("en");
    try {
      const emptySlot: AgentConfig = {
        ...twoAgents[1],
        name: "Perspective 2",
        prompt_id: null,
        enabled: false,
      };
      const html = renderToStaticMarkup(
        createElement(ActivityPanel, {
          isStreaming: false,
          currentAgents: [twoAgents[0], emptySlot],
          agentLifecycle: {},
          messages: [],
          onMoveAgent: () => undefined,
          onToggleAgent: () => undefined,
        }),
      );

      expect(html).toContain('<span class="agent-status-perspective-name">None</span>');
      expect(html.match(/Perspective 2/g)).toHaveLength(1);
    } finally {
      await i18n.changeLanguage("de");
    }
  });

  it("disables all move and toggle controls while a generation is streaming", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: twoAgents,
        agentLifecycle: { alpha: "streaming", beta: "waiting" },
        messages: [],
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    const reMoveUp = /<button[^>]*title="Nach oben"[^>]*>/g;
    const reMoveDown = /<button[^>]*title="Nach unten"[^>]*>/g;
    const reCheckbox = /<input[^>]*type="checkbox"[^>]*>/g;
    for (const match of html.match(reMoveUp) ?? []) {
      expect(match).toContain("disabled");
    }
    for (const match of html.match(reMoveDown) ?? []) {
      expect(match).toContain("disabled");
    }
    for (const match of html.match(reCheckbox) ?? []) {
      expect(match).toContain("disabled");
    }
  });

  it("only renders the active agents in the streaming progress / lifecycle list", () => {
    const roster: AgentConfig[] = [
      twoAgents[0],
      twoAgents[1],
      {
        name: "Gamma",
        client_id: "gamma",
        prompt_id: "p3",
        color: "#333",
        temperature: null,
        llm_id: null,
        api_host: null,
        api_key: null,
        max_tokens: null,
        enabled: false,
        perspective_number: 3,
      },
    ];

    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: roster,
        agentLifecycle: { alpha: "complete", beta: "complete" },
        messages: [],
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("2/2 Perspektiven");
    expect(html).toContain("Alpha");
    expect(html).toContain("Beta");
    expect(html).toContain("Gamma");
    expect(html).toMatch(
      /class="[^"]*agent-status-row[^"]*is-inactive[^"]*"[^>]*data-client-id="gamma"/,
    );
    expect(html).not.toMatch(/<li[^>]*class="[^"]*agent-roster/);
  });

  it("keeps the integrated list visible with inline controls during a streaming round", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: twoAgents,
        agentLifecycle: { alpha: "streaming", beta: "waiting" },
        messages: [],
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toMatch(/<div[^>]*class="[^"]*agent-status-list[^"]*"/);
    expect(html).toMatch(
      /class="[^"]*agent-status-row[^"]*is-writing[^"]*"[^>]*data-client-id="alpha"/,
    );
    expect(html).toContain("schreibt");
    expect(html).toContain("wartet");
    expect(html).not.toMatch(/<li[^>]*class="[^"]*agent-roster/);
  });
});

describe("ActivityPanel idle (persisted terminal metadata)", () => {
  const threeActiveAgents: AgentConfig[] = [
    {
      name: "Alpha",
      client_id: "alpha",
      prompt_id: "p1",
      color: "#111",
      temperature: null,
      llm_id: null,
      api_host: null,
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 1,
    },
    {
      name: "Beta",
      client_id: "beta",
      prompt_id: "p2",
      color: "#222",
      temperature: null,
      llm_id: null,
      api_host: null,
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 2,
    },
    {
      name: "Gamma",
      client_id: "gamma",
      prompt_id: "p3",
      color: "#333",
      temperature: null,
      llm_id: null,
      api_host: null,
      api_key: null,
      max_tokens: null,
      enabled: true,
      perspective_number: 3,
    },
  ];

  const completedMessages: DiscussionMessage[] = [
    {
      id: "u1",
      role: "user",
      content: "Frage",
      round_number: 1,
      agent_name: null,
      theory_label: null,
      color: null,
      agent_index: null,
      note: "",
      include_in_agent_context: true,
    },
    {
      id: "a1",
      role: "agent",
      content: "Antwort Alpha",
      round_number: 1,
      agent_name: "Alpha",
      theory_label: "Systemtheorie",
      color: "#111",
      agent_index: 0,
      perspective_number: 1,
      note: "",
      include_in_agent_context: true,
      client_id: "alpha",
    },
    {
      id: "a2",
      role: "agent",
      content: "Antwort Beta",
      round_number: 1,
      agent_name: "Beta",
      theory_label: "Systemtheorie",
      color: "#222",
      agent_index: 1,
      perspective_number: 2,
      note: "",
      include_in_agent_context: true,
      client_id: "beta",
    },
    {
      id: "a3",
      role: "agent",
      content: "Antwort Gamma",
      round_number: 1,
      agent_name: "Gamma",
      theory_label: "Systemtheorie",
      color: "#333",
      agent_index: 2,
      perspective_number: 3,
      note: "",
      include_in_agent_context: true,
      client_id: "gamma",
    },
  ];

  it("renders a completed snapshot as 3/3 with no wartet rows", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: threeActiveAgents,
        agentLifecycle: {},
        messages: completedMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("3/3 Perspektiven");
    expect(html).toContain("fertig");
    expect(html).not.toContain("wartet");
  });

  it("renders a persisted error as Fehler and excludes it from the count", () => {
    const erroredMessages: DiscussionMessage[] = [
      completedMessages[0],
      completedMessages[1],
      {
        id: "a2-err",
        role: "agent",
        content: "[Fehler: 503]",
        round_number: 1,
        agent_name: "Beta",
        theory_label: "Systemtheorie",
        color: "#222",
        agent_index: 1,
        perspective_number: 2,
        note: "",
        include_in_agent_context: true,
        client_id: "beta",
        error: "Anbieter-Fehler: 503",
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: threeActiveAgents,
        agentLifecycle: {},
        messages: erroredMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("2/2 Perspektiven");
    expect(html).toContain("Fehler");
    expect(html).not.toContain("wartet");
  });

  it("renders idle bereit for an active agent that has not answered the latest round", () => {
    const partialMessages: DiscussionMessage[] = [completedMessages[0], completedMessages[1]];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: threeActiveAgents,
        agentLifecycle: {},
        messages: partialMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("1/1 Perspektiven");
    expect(html).toContain("fertig");
    expect(html).toContain("bereit");
    expect(html).not.toContain("wartet");
  });

  it("keeps streaming wartet for not-yet-started agents while a round is running", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: threeActiveAgents,
        agentLifecycle: {
          alpha: "streaming",
          beta: "waiting",
        },
        messages: [],
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("schreibt");
    const wartetMatches = html.match(/wartet/g) ?? [];
    expect(wartetMatches.length).toBeGreaterThanOrEqual(2);
  });

  it("does not use earlier-round agent output to mark an agent complete in the latest round", () => {
    const twoRoundMessages: DiscussionMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "Frage Runde 1",
        round_number: 1,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: true,
      },
      {
        id: "a1-r1",
        role: "agent",
        content: "Alpha R1",
        round_number: 1,
        agent_name: "Alpha",
        theory_label: "Systemtheorie",
        color: "#111",
        agent_index: 0,
        perspective_number: 1,
        note: "",
        include_in_agent_context: true,
        client_id: "alpha",
      },
      {
        id: "a2-r1",
        role: "agent",
        content: "Beta R1",
        round_number: 1,
        agent_name: "Beta",
        theory_label: "Systemtheorie",
        color: "#222",
        agent_index: 1,
        perspective_number: 2,
        note: "",
        include_in_agent_context: true,
        client_id: "beta",
      },
      {
        id: "a3-r1",
        role: "agent",
        content: "Gamma R1",
        round_number: 1,
        agent_name: "Gamma",
        theory_label: "Systemtheorie",
        color: "#333",
        agent_index: 2,
        perspective_number: 3,
        note: "",
        include_in_agent_context: true,
        client_id: "gamma",
      },
      {
        id: "u2",
        role: "user",
        content: "Frage Runde 2",
        round_number: 2,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: true,
      },
      {
        id: "a1-r2",
        role: "agent",
        content: "Alpha R2",
        round_number: 2,
        agent_name: "Alpha",
        theory_label: "Systemtheorie",
        color: "#111",
        agent_index: 0,
        perspective_number: 1,
        note: "",
        include_in_agent_context: true,
        client_id: "alpha",
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: threeActiveAgents,
        agentLifecycle: {},
        messages: twoRoundMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toContain("1/1 Perspektiven");
    expect(html).toContain("Runde 2 abgeschlossen");
    expect(html).toContain("bereit");
    expect(html).not.toContain("wartet");
  });

  it("excludes disabled roster rows from the active progress denominator and keeps them inactive", () => {
    const rosterWithDisabled: AgentConfig[] = [
      threeActiveAgents[0],
      threeActiveAgents[1],
      { ...threeActiveAgents[2], enabled: false },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: rosterWithDisabled,
        agentLifecycle: {},
        messages: completedMessages,
        onMoveAgent: () => undefined,
        onToggleAgent: () => undefined,
      }),
    );

    expect(html).toMatch(
      /class="[^"]*agent-status-row[^"]*is-inactive[^"]*"[^>]*data-client-id="gamma"/,
    );
    expect(html).toContain("3/3 Perspektiven");
    expect(html).not.toContain("2/2 Perspektiven");
  });
});

describe("ActivityPanel provider usage", () => {
  it("shows the live perspective preflight estimate before provider usage arrives", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: [agents[0]],
        agentLifecycle: { a1: "streaming" },
        messages: [],
        latestContextUsage: {
          message_id: "a1",
          agent_index: 0,
          available: true,
          input_tokens: 120,
          context_tokens: 65536,
          exact: false,
          omitted_round_numbers: [2, 3],
        },
      }),
    );

    expect(html).toContain("Kontextgröße: ~120 / 65.536 Tokens (~0%)");
    expect(html).toContain("context-usage-radial is-info");
    expect(html).toContain('stroke-dasharray="0 100"');
    expect(html).not.toContain("Ausgelassene Runden");
  });

  it("uses the currently streaming perspective instead of an older completed one", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "first",
        role: "agent",
        content: "Erste Antwort",
        round_number: 1,
        agent_name: "Agent 1",
        theory_label: "Theorie",
        color: "#1",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        usage_available: true,
        prompt_tokens: 99,
        completion_tokens: 4,
        total_tokens: 103,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: agents,
        agentLifecycle: { a1: "complete", a2: "streaming" },
        messages,
        latestContextUsage: {
          message_id: "second",
          agent_index: 1,
          available: true,
          input_tokens: 120,
          context_tokens: 65536,
          exact: false,
          omitted_round_numbers: [],
        },
      }),
    );

    expect(html).toContain("Kontextgröße: ~120 / 65.536 Tokens (~0%)");
    expect(html).toContain("context-usage-radial");
    expect(html).not.toContain("103 Tokens");
    expect(html).not.toContain("Gesamt:");
  });

  it("prefers completed provider prompt tokens over total usage and preflight estimates", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "a1",
        role: "agent",
        content: "Antwort",
        round_number: 1,
        agent_name: "Agent 1",
        theory_label: "Theorie",
        color: "#1",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        usage_available: true,
        prompt_tokens: 120,
        completion_tokens: 4,
        total_tokens: 124,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [agents[0]],
        agentLifecycle: {},
        messages,
        latestContextUsage: {
          message_id: "a1",
          agent_index: 0,
          available: true,
          input_tokens: 118,
          context_tokens: 65536,
          exact: false,
          omitted_round_numbers: [],
        },
      }),
    );

    expect(html).toContain("Kontextgröße: 120 Tokens");
    expect(html).not.toContain("124 Tokens");
    expect(html).not.toContain("~120 Tokens");
    expect(html).not.toContain("ca. 120 Tokens");
    expect(html).not.toContain("Kontextfenster");
    expect(html).not.toContain("Ausgabe:");
  });

  it("uses the persisted preflight estimate after reload when provider usage is unavailable", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "a1",
        role: "agent",
        content: "Antwort",
        round_number: 1,
        agent_name: "Agent 1",
        theory_label: "Systemtheorie",
        color: "#1",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        usage_available: false,
        context_usage_available: true,
        input_context_tokens: 118,
        context_tokens_exact: false,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [agents[0]],
        agentLifecycle: {},
        messages,
      }),
    );

    expect(html).toContain("Kontextgröße: ~118 Tokens");
    expect(html).not.toContain("context-usage-radial");
    expect(html).not.toContain(">memory</span>");
  });

  it("does not let a smaller synthesis total replace the final perspective context", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "third-perspective",
        role: "agent",
        content: "Dritte Antwort",
        round_number: 1,
        agent_name: "Agent 3",
        theory_label: "Theorie",
        color: "#3",
        agent_index: 2,
        note: "",
        include_in_agent_context: true,
        usage_available: true,
        prompt_tokens: 1200,
        completion_tokens: 300,
        total_tokens: 1500,
      },
      {
        id: "synthesis",
        role: "synthesis",
        content: "Kurze Synthese",
        round_number: 1,
        agent_name: null,
        theory_label: null,
        color: null,
        agent_index: null,
        note: "",
        include_in_agent_context: false,
        usage_available: true,
        prompt_tokens: 20,
        completion_tokens: 10,
        total_tokens: 30,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        messages,
      }),
    );

    expect(html).toContain("Kontextgröße: 1.200 Tokens");
    expect(html).not.toContain("30 Tokens");
  });

  it("does not mix a stale live preflight event into a completed final perspective", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "final-perspective",
        role: "agent",
        content: "Finale Antwort",
        round_number: 1,
        agent_name: "Agent 3",
        theory_label: "Theorie",
        color: "#3",
        agent_index: 2,
        note: "",
        include_in_agent_context: true,
        usage_available: false,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        messages,
        latestContextUsage: {
          message_id: "older-perspective",
          agent_index: 0,
          available: true,
          input_tokens: 999,
          context_tokens: 65536,
          exact: false,
          omitted_round_numbers: [],
        },
      }),
    );

    expect(html).not.toContain("context-usage");
    expect(html).not.toContain("999 Tokens");
  });

  it("hides the usage row when the latest perspective has no provider or preflight count", () => {
    const messages: DiscussionMessage[] = [
      {
        id: "a1",
        role: "agent",
        content: "Antwort",
        round_number: 1,
        agent_name: "Agent 1",
        theory_label: "Systemtheorie",
        color: "#1",
        agent_index: 0,
        note: "",
        include_in_agent_context: true,
        usage_available: false,
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [agents[0]],
        agentLifecycle: {},
        messages,
      }),
    );

    expect(html).not.toContain("context-usage");
  });
});

describe("ActivityPanel perspective and synthesis status", () => {
  const synthesis = {
    enabled: true,
    api_host: null,
    llm_id: null,
    temperature: null,
  };
  const completedRoundMessages: DiscussionMessage[] = [
    ...agents.map((agent, index) => ({
      id: `a${index + 1}`,
      role: "agent" as const,
      content: `Answer ${index + 1}`,
      round_number: 1,
      agent_name: agent.name,
      theory_label: null,
      color: agent.color,
      agent_index: index,
      perspective_number: agent.perspective_number,
      client_id: agent.client_id,
      note: "",
      include_in_agent_context: true,
    })),
    {
      id: "s1",
      role: "synthesis",
      content: "Summary",
      round_number: 1,
      agent_name: null,
      theory_label: null,
      color: null,
      agent_index: null,
      perspective_number: null,
      client_id: null,
      note: "",
      include_in_agent_context: false,
    },
  ];

  it("renders one activity heading", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [],
        agentLifecycle: {},
        messages: [],
      }),
    );

    expect((html.match(/class="panel-header"/g) ?? []).length).toBe(1);
  });

  it("shows the Integrated AI timing notice throughout an Integrated AI discussion", () => {
    const empty = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        usesIntegratedAI: true,
        currentAgents: [],
        agentLifecycle: {},
        messages: [],
      }),
    );
    const streaming = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        usesIntegratedAI: true,
        currentAgents: agents,
        agentLifecycle: { a1: "streaming", a2: "waiting", a3: "waiting" },
        messages: [],
      }),
    );
    const completed = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        usesIntegratedAI: true,
        currentAgents: agents,
        agentLifecycle: {},
        messages: completedRoundMessages,
      }),
    );
    const external = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        usesIntegratedAI: false,
        currentAgents: agents,
        agentLifecycle: { a1: "streaming", a2: "waiting", a3: "waiting" },
        messages: [],
      }),
    );

    for (const html of [empty, streaming, completed]) {
      expect(html).toContain('class="activity-info-notice"');
      expect(html).toContain(">help</span>");
      expect(html).toContain(
        "Die Generierung mit Integrated AI kann je nach Computer mehrere Minuten dauern.",
      );
    }
    expect(external).not.toContain("activity-info-notice");
  });

  it("shows the stable perspective slot and its selected catalogue label", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [{ ...agents[0], name: "Unused Label", prompt_id: "conceptualization" }],
        agentLifecycle: {},
        messages: [],
        perspectives: [{ id: "conceptualization", label: "Conceptualization" }],
      }),
    );

    expect(html).toContain("Perspektive 1");
    expect(html).toMatch(
      /Perspektive 1:\s*<span class="agent-status-perspective-name">Conceptualization<\/span>/,
    );
    expect(html).not.toContain("Unused Label");
  });

  it("renders every terminal stage as done at the end of a round", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        messages: completedRoundMessages,
        synthesis,
      }),
    );

    expect(html).toContain("4/4 Schritte");
    for (const agent of agents) {
      expect(html).toMatch(
        new RegExp(`agent-status-row[^>]*is-done[^>]*data-client-id="${agent.client_id}"`),
      );
    }
    expect(html).toContain('data-synthesis-state="complete"');
  });

  it("keeps a completed round unchanged when a perspective is disabled afterward", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [...agents.slice(0, 2), { ...agents[2], enabled: false }],
        agentLifecycle: {},
        messages: completedRoundMessages,
        synthesis,
      }),
    );

    expect(html).toContain("4/4 Schritte");
    expect(html).toMatch(/agent-status-row[^>]*is-inactive[^>]*data-client-id="a3"/);
  });

  it("uses perspective-only progress when synthesis was disabled for the completed round", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: [agents[0], agents[1]],
        agentLifecycle: {},
        messages: completedRoundMessages.filter(
          (message) => message.role === "agent" && message.id !== "a3",
        ),
        synthesis: { ...synthesis, enabled: false },
      }),
    );

    expect(html).toContain("2/2 Perspektiven");
    expect(html).not.toContain("2/2 Schritte");
  });

  it("counts a failed synthesis as a finished terminal step", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        messages: [
          ...completedRoundMessages.slice(0, 3),
          {
            ...completedRoundMessages[3],
            content: "",
            error: "Provider unavailable",
            error_code: "synthesis_generation_failed",
          },
        ],
        synthesis,
      }),
    );

    expect(html).toContain("4/4 Schritte");
    expect(html).toContain('data-synthesis-state="error"');
    expect(html).toContain("Fehler");
  });

  it("hides synthesis before a discussion starts and counts it as a progress step once running", () => {
    const idle = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        messages: [],
        synthesis,
      }),
    );
    expect(idle).not.toContain("synthesis-status-row");

    const waiting = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: agents,
        agentLifecycle: { a1: "streaming", a2: "waiting", a3: "waiting" },
        messages: [],
        synthesis,
      }),
    );
    expect(waiting).toContain('data-synthesis-state="waiting"');
    expect(waiting).toContain(
      'class="material-symbol message-loading" aria-hidden="true">pending</span>',
    );
    expect(waiting).toContain("0/4 Schritte");

    const writing = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: true,
        currentAgents: agents,
        agentLifecycle: { a1: "complete", a2: "complete", a3: "complete" },
        messages: [],
        synthesis,
        streamingSynthesis: { error: null },
      }),
    );
    expect(writing).toContain('data-synthesis-state="writing"');
    expect(writing).toContain('class="agent-waveform" aria-hidden="true"');
    expect(writing).toContain("3/4 Schritte");

    const complete = renderToStaticMarkup(
      createElement(ActivityPanel, {
        isStreaming: false,
        currentAgents: agents,
        agentLifecycle: {},
        synthesis,
        messages: [
          {
            id: "s1",
            role: "synthesis",
            content: "No usable perspective contributions were available for synthesis.",
            round_number: 1,
            agent_name: null,
            theory_label: null,
            color: null,
            agent_index: null,
            note: "",
            include_in_agent_context: false,
            error: "No usable contributions",
            error_code: "synthesis_no_usable_contributions",
          },
        ],
      }),
    );
    expect(complete).toContain('data-synthesis-state="complete"');
    expect(complete).toContain(
      '<span class="material-symbol" aria-hidden="true">check</span> fertig',
    );
    expect(complete).toContain("1/1 Schritte");
  });
});
