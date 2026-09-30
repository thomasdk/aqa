/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { useState, useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import i18n, { formatNumber } from "../i18n";
import { Button } from "./design-system";
import { IconButton } from "./IconButton";
import MaterialSymbol from "./MaterialSymbol";
import {
  hasValidProviderSelection,
  PerspectiveConfigurationControls,
  SynthesisConfigurationControls,
} from "./DiscussionConfigurationControls";
import { isAgentActive } from "./discussionAgentRosterState";
import type {
  DiscussionMessage,
  AgentConfig,
  ContextUsage,
  HostInfo,
  LocalAIStatus,
  Perspective,
  Role,
  RoundProviderProvenance,
  SynthesisConfig,
} from "./types";

export type AgentLifecycleState = "idle" | "waiting" | "streaming" | "complete" | "error";
export type AgentLifecycle = Record<string, AgentLifecycleState>;

export const EXTERNAL_AI_LONG_WAIT_NOTICE_SECONDS = 600;

export type AgentActivityStatus = {
  agent: AgentConfig;
  state: AgentLifecycleState;
};

export const createInitialAgentLifecycle = (agents: AgentConfig[]): AgentLifecycle =>
  Object.fromEntries(agents.map((agent) => [agent.client_id, "waiting" as const]));

export const derivePersistedAgentState = (
  agent: AgentConfig,
  messages: readonly DiscussionMessage[],
  currentRound: number,
): AgentLifecycleState | undefined => {
  const terminalMessage = messages.find(
    (message) =>
      message.role === "agent" &&
      message.round_number === currentRound &&
      message.client_id === agent.client_id &&
      message.perspective_number === agent.perspective_number,
  );
  return terminalMessage
    ? (terminalMessage.status ?? "completed") === "completed" && !terminalMessage.error
      ? "complete"
      : "error"
    : undefined;
};

/**
 * Live state is authoritative while streaming; otherwise derive state from
 * persisted messages. Missing live entries wait, and missing saved entries idle.
 */
export const resolveAgentLifecycle = (
  agent: AgentConfig,
  lifecycle: AgentLifecycle,
  messages: readonly DiscussionMessage[],
  isStreaming: boolean,
  currentRound: number,
): AgentLifecycleState => {
  if (isStreaming) {
    return lifecycle[agent.client_id] ?? "waiting";
  }
  return derivePersistedAgentState(agent, messages, currentRound) ?? "idle";
};

/**
 * Disabled and errored agents never inflate completed progress. Live state is
 * used during streaming and persisted state between rounds.
 */
export const getAgentActivityStatus = (
  agents: AgentConfig[],
  lifecycle: AgentLifecycle,
  messages: readonly DiscussionMessage[] = [],
  isStreaming: boolean = false,
  currentRound: number = 0,
): { statuses: AgentActivityStatus[]; completedCount: number } => {
  const active = agents.filter(isAgentActive);
  const statuses = active.map((agent) => ({
    agent,
    state: resolveAgentLifecycle(agent, lifecycle, messages, isStreaming, currentRound),
  }));

  return {
    statuses,
    completedCount: statuses.filter((status) => status.state === "complete").length,
  };
};

export type CompletedRoundProgress = {
  terminalAgentCount: number;
  hasTerminalSynthesis: boolean;
};

/**
 * Count the stages that actually reached a terminal state in one persisted
 * round. This intentionally does not inspect the editable current roster:
 * roster changes prepare the next round and must not rewrite past progress.
 */
export const getCompletedRoundProgress = (
  messages: readonly DiscussionMessage[],
  currentRound: number,
): CompletedRoundProgress => {
  const terminalAgents = new Set<string>();
  let hasTerminalSynthesis = false;

  for (const message of messages) {
    if (message.round_number !== currentRound) continue;
    if (message.role === "agent") {
      if ((message.status ?? "completed") === "in_progress") continue;
      terminalAgents.add(
        message.client_id ??
          `perspective:${message.perspective_number ?? message.agent_index ?? message.id}`,
      );
    } else if (message.role === "synthesis") {
      hasTerminalSynthesis = (message.status ?? "completed") !== "in_progress";
    }
  }

  return { terminalAgentCount: terminalAgents.size, hasTerminalSynthesis };
};

export type ProgressPresentationMode = "determinate";

export type ProgressPresentation = {
  mode: ProgressPresentationMode;
  ariaValueNow: number | null;
  ariaValueMax: number | null;
  ariaValueText: string;
  percent: number;
};

export const getProgressPresentation = (args: {
  isStreaming: boolean;
  completedCount: number;
  totalAgents: number;
  includesSynthesis?: boolean;
}): ProgressPresentation => {
  const { completedCount, totalAgents, includesSynthesis = false } = args;
  const safeTotal = Math.max(0, totalAgents);
  const safeCompleted = Math.max(0, Math.min(completedCount, safeTotal));
  const percent = safeTotal > 0 ? (safeCompleted / safeTotal) * 100 : 0;

  // Partial completion remains determinate while later agents stream.
  return {
    mode: "determinate",
    ariaValueNow: safeCompleted,
    ariaValueMax: safeTotal,
    ariaValueText:
      safeTotal > 0
        ? i18n.t(includesSynthesis ? "activity.stepsProgressAria" : "activity.progressAria", {
            complete: safeCompleted,
            total: safeTotal,
          })
        : i18n.t("activity.noAgents"),
    percent,
  };
};

export type ContextWindowPressure = "info" | "warning" | "danger";

export type ContextWindowPresentation = {
  percentage: number;
  radialPercentage: number;
  pressure: ContextWindowPressure;
};

/**
 * Derive an honest context-window fraction for the latest perspective.
 * The display keeps an over-cap percentage visible, while the radial ring
 * itself cannot exceed a complete circle.
 */
export const getContextWindowPresentation = (
  inputTokens: number,
  contextWindowTokens: number | null | undefined,
): ContextWindowPresentation | null => {
  if (
    !Number.isFinite(inputTokens) ||
    inputTokens < 0 ||
    !Number.isFinite(contextWindowTokens) ||
    !contextWindowTokens ||
    contextWindowTokens <= 0
  ) {
    return null;
  }

  const percentage = Math.round((inputTokens / contextWindowTokens) * 100);
  return {
    percentage,
    radialPercentage: Math.max(0, Math.min(100, percentage)),
    pressure: percentage >= 90 ? "danger" : percentage >= 70 ? "warning" : "info",
  };
};

type Props = {
  isStreaming: boolean;
  roundStatus?: "in_progress" | "completed" | "interrupted" | "failed" | null;
  usesIntegratedAI?: boolean;
  currentAgents: AgentConfig[];
  agentLifecycle: AgentLifecycle;
  messages: DiscussionMessage[];
  roundStartedAt?: number | null;
  roundElapsedSeconds?: number | null;
  latestContextUsage?: ContextUsage | null;
  /**
   * Stop the in-flight discussion generation. Provided by Layout. The
   * button is rendered only while `isStreaming` is true; while the
   * cancellation request is in flight, `isStopInProgress` disables the
   * button to prevent double-clicks racing the server.
   */
  onStop?: () => void;
  isStopInProgress?: boolean;
  onMoveAgent?: (clientId: string, delta: -1 | 1) => void;
  onToggleAgent?: (clientId: string, enabled: boolean) => void;
  /**
   * Disables roster controls while a roster change is being persisted.
   */
  isRosterSaving?: boolean;
  synthesis?: SynthesisConfig;
  streamingSynthesis?: { error: string | null; error_code?: string | null } | null;
  perspectives?: readonly Perspective[];
  onToggleSynthesis?: (enabled: boolean) => void;
  isSynthesisSaving?: boolean;
  roles?: readonly Role[];
  hosts?: readonly HostInfo[];
  localStatus?: LocalAIStatus | null;
  onApplyNextRoundConfiguration?: (
    agents: AgentConfig[],
    synthesis: SynthesisConfig,
  ) => Promise<boolean>;
  isRoundConfigurationSaving?: boolean;
  configurationOpenRequest?: number;
  roundProviderProvenance?: readonly RoundProviderProvenance[];
};

type RosterRowProps = {
  agent: AgentConfig;
  slotNumber: number;
  perspectiveName: string;
  isFirst: boolean;
  isLast: boolean;
  isRosterLocked: boolean;
  onMoveAgent?: (clientId: string, delta: -1 | 1) => void;
  onToggleAgent?: (clientId: string, enabled: boolean) => void;
  lifecycle: AgentLifecycleState | undefined;
  /**
   * When true the row is rendered as the compact inactive variant
   * (no lifecycle badge, just an "(inaktiv)" label and the inline
   * controls). When false the row is rendered as the active variant
   * using the supplied ``lifecycle`` to pick the lifecycle badge.
   */
  isActive: boolean;
  onConfigure?: () => void;
  configureExpanded?: boolean;
  configureControlsId?: string;
  configuration?: ReactNode;
};

const RosterRow = ({
  agent,
  slotNumber,
  perspectiveName,
  isFirst,
  isLast,
  isRosterLocked,
  onMoveAgent,
  onToggleAgent,
  lifecycle,
  isActive,
  onConfigure,
  configureExpanded = false,
  configureControlsId,
  configuration,
}: RosterRowProps) => {
  const { t } = useTranslation();
  let rowClass = "agent-status-row";
  let state: ReactNode;
  if (!isActive) {
    rowClass += " is-inactive";
    state = (
      <span className="agent-status-state" aria-label={t("activity.inactive")}>
        ({t("activity.inactive").toLocaleLowerCase()})
      </span>
    );
  } else if (lifecycle === "error") {
    rowClass += " is-error";
    state = (
      <span className="agent-status-state is-error">
        <MaterialSymbol name="warning" decorative /> {t("common.error")}
      </span>
    );
  } else if (lifecycle === "streaming") {
    rowClass += " is-writing";
    state = (
      <>
        <span className="agent-waveform" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
        <span className="agent-status-state">{t("activity.writing")}</span>
      </>
    );
  } else if (lifecycle === "complete") {
    rowClass += " is-done";
    state = (
      <span className="agent-status-state is-done">
        <MaterialSymbol name="check" decorative /> {t("activity.done")}
      </span>
    );
  } else if (lifecycle === "idle") {
    rowClass += " is-idle";
    state = <span className="agent-status-state is-idle">{t("activity.ready")}</span>;
  } else {
    rowClass += " is-queued";
    state = (
      <span className="agent-status-state">
        <MaterialSymbol name="pending" decorative className="message-loading" />{" "}
        {t("activity.waiting")}
      </span>
    );
  }

  return (
    <div
      className={`${rowClass}${configureExpanded ? " is-expanded" : ""}`}
      style={{ borderLeftColor: agent.color }}
      data-client-id={agent.client_id}
    >
      <div className="agent-status-summary">
        <span className="agent-status-name">
          {t("setup.perspectiveSlot", { number: slotNumber })}:{" "}
          <span className="agent-status-perspective-name">{perspectiveName}</span>
        </span>
        {state}
        <span className="agent-status-controls">
          {onConfigure && (
            <Button
              variant="text"
              size="small"
              className="agent-status-options-btn"
              onClick={onConfigure}
              disabled={isRosterLocked}
              aria-controls={configureControlsId}
              aria-expanded={configureExpanded}
              aria-label={t("activity.configurePerspective", { name: perspectiveName })}
            >
              <MaterialSymbol name="tune" decorative />
              <span>{t("setup.options")}</span>
            </Button>
          )}
          <label className="checkbox agent-status-active-toggle">
            <input
              type="checkbox"
              checked={agent.enabled}
              disabled={isRosterLocked || !onToggleAgent}
              onChange={(event) => onToggleAgent?.(agent.client_id, event.target.checked)}
              aria-label={t("activity.activeAgent", { name: perspectiveName })}
            />
            {t("common.active")}
          </label>
          <IconButton
            size="small"
            className="agent-status-move-btn"
            onClick={() => onMoveAgent?.(agent.client_id, -1)}
            disabled={isRosterLocked || isFirst || !onMoveAgent}
            label={t("activity.moveAgentUp", { name: perspectiveName })}
          >
            <MaterialSymbol name="arrow_upward" decorative />
          </IconButton>
          <IconButton
            size="small"
            className="agent-status-move-btn"
            onClick={() => onMoveAgent?.(agent.client_id, 1)}
            disabled={isRosterLocked || isLast || !onMoveAgent}
            label={t("activity.moveAgentDown", { name: perspectiveName })}
          >
            <MaterialSymbol name="arrow_downward" decorative />
          </IconButton>
        </span>
      </div>
      {configuration}
    </div>
  );
};

const ActivityPanel = ({
  isStreaming,
  roundStatus = null,
  usesIntegratedAI = false,
  currentAgents,
  agentLifecycle,
  messages,
  roundStartedAt = null,
  roundElapsedSeconds = null,
  latestContextUsage = null,
  onStop,
  isStopInProgress,
  onMoveAgent,
  onToggleAgent,
  isRosterSaving,
  synthesis,
  streamingSynthesis = null,
  perspectives = [],
  onToggleSynthesis,
  isSynthesisSaving,
  roles = [],
  hosts = [],
  localStatus = null,
  onApplyNextRoundConfiguration,
  isRoundConfigurationSaving = false,
  configurationOpenRequest = 0,
  roundProviderProvenance = [],
}: Props) => {
  const { t } = useTranslation();
  const [runningElapsed, setRunningElapsed] = useState({
    startedAt: null as number | null,
    seconds: 0,
  });
  const [draftAgents, setDraftAgents] = useState<AgentConfig[]>(currentAgents);
  const [draftSynthesis, setDraftSynthesis] = useState<SynthesisConfig | null>(synthesis ?? null);
  const [openDraftOptions, setOpenDraftOptions] = useState<Record<string, boolean>>({});
  const [draftSynthesisOptionsOpen, setDraftSynthesisOptionsOpen] = useState(false);
  const [showRecoveryGuidance, setShowRecoveryGuidance] = useState(false);
  const configurationRecoveryRef = useRef<HTMLParagraphElement>(null);
  const handledConfigurationRequestRef = useRef(0);
  const queuedConfigurationRef = useRef<{
    agents: AgentConfig[];
    synthesis: SynthesisConfig;
  } | null>(null);
  const configurationSaveRunningRef = useRef(false);
  const currentAgentsRef = useRef(currentAgents);
  const synthesisRef = useRef(synthesis);
  const lastPerspectiveMessage = [...messages]
    .reverse()
    .find((message) => message.role === "agent");
  const storedContextUsage: ContextUsage | null =
    lastPerspectiveMessage?.context_usage_available != null &&
    typeof lastPerspectiveMessage.agent_index === "number"
      ? {
          message_id: lastPerspectiveMessage.id,
          agent_index: lastPerspectiveMessage.agent_index,
          available: Boolean(lastPerspectiveMessage.context_usage_available),
          input_tokens: lastPerspectiveMessage.input_context_tokens ?? null,
          context_tokens: lastPerspectiveMessage.context_window_tokens ?? null,
          exact: Boolean(lastPerspectiveMessage.context_tokens_exact),
          omitted_round_numbers: lastPerspectiveMessage.omitted_round_numbers ?? [],
        }
      : null;
  // A context event for an as-yet incomplete perspective is newer than the
  // stored answer. Once its answer has been persisted, use that same
  // message's provider usage (or saved preflight measurement) instead.
  const liveContextUsage =
    isStreaming &&
    latestContextUsage &&
    latestContextUsage.message_id !== lastPerspectiveMessage?.id
      ? latestContextUsage
      : null;
  const displayedContextUsage = liveContextUsage ?? storedContextUsage;
  const providerPromptTokens =
    !liveContextUsage &&
    lastPerspectiveMessage?.usage_available === true &&
    typeof lastPerspectiveMessage.prompt_tokens === "number" &&
    Number.isFinite(lastPerspectiveMessage.prompt_tokens) &&
    lastPerspectiveMessage.prompt_tokens >= 0
      ? lastPerspectiveMessage.prompt_tokens
      : null;
  const contextTokens = providerPromptTokens ?? displayedContextUsage?.input_tokens ?? null;
  const contextTokensExact =
    providerPromptTokens != null ? true : Boolean(displayedContextUsage?.exact);
  const contextWindowTokens =
    displayedContextUsage?.context_tokens ?? lastPerspectiveMessage?.context_window_tokens ?? null;
  const contextWindowPresentation = getContextWindowPresentation(
    contextTokens ?? -1,
    contextWindowTokens,
  );

  const elapsed =
    roundStartedAt == null
      ? roundElapsedSeconds
      : runningElapsed.startedAt === roundStartedAt
        ? runningElapsed.seconds
        : 0;

  useEffect(() => {
    if (!isStreaming || roundStartedAt == null) return;
    const refreshElapsed = () =>
      setRunningElapsed({
        startedAt: roundStartedAt,
        seconds: Math.max(0, Math.floor((Date.now() - roundStartedAt) / 1000)),
      });
    refreshElapsed();
    const interval = setInterval(refreshElapsed, 1000);
    return () => clearInterval(interval);
  }, [isStreaming, roundStartedAt]);

  const configurationOpen =
    Object.values(openDraftOptions).some(Boolean) || draftSynthesisOptionsOpen;

  useEffect(() => {
    if (!isStreaming) return;
    setOpenDraftOptions({});
    setDraftSynthesisOptionsOpen(false);
    setShowRecoveryGuidance(false);
  }, [isStreaming]);

  useEffect(() => {
    currentAgentsRef.current = currentAgents;
    synthesisRef.current = synthesis;
    if (configurationOpen || configurationSaveRunningRef.current) return;
    setDraftAgents(currentAgents.map((agent) => ({ ...agent })));
    setDraftSynthesis(synthesis ? { ...synthesis } : null);
  }, [configurationOpen, currentAgents, synthesis]);

  useEffect(() => {
    if (
      configurationOpenRequest <= 0 ||
      configurationOpenRequest === handledConfigurationRequestRef.current
    ) {
      return;
    }
    handledConfigurationRequestRef.current = configurationOpenRequest;
    setDraftAgents(currentAgents.map((agent) => ({ ...agent })));
    setDraftSynthesis(synthesis ? { ...synthesis } : null);
    setOpenDraftOptions(
      Object.fromEntries(
        currentAgents
          .filter(
            (agent) =>
              (agent.prompt_id !== null &&
                !perspectives.some((item) => item.id === agent.prompt_id)) ||
              !hasValidProviderSelection(agent, hosts, localStatus) ||
              (agent.enabled && !(agent.host_configuration_id && agent.api_host && agent.llm_id)),
          )
          .map((agent) => [agent.client_id, true]),
      ),
    );
    setDraftSynthesisOptionsOpen(
      Boolean(
        synthesis?.enabled &&
        (!hasValidProviderSelection(synthesis, hosts, localStatus) ||
          !(synthesis.host_configuration_id && synthesis.api_host && synthesis.llm_id)),
      ),
    );
    setShowRecoveryGuidance(true);
  }, [configurationOpenRequest, currentAgents, hosts, localStatus, perspectives, synthesis]);

  useEffect(() => {
    if (configurationOpenRequest > 0 && configurationOpen) {
      configurationRecoveryRef.current?.focus();
    }
  }, [configurationOpen, configurationOpenRequest]);

  const formatTime = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const currentRound = messages.length > 0 ? Math.max(...messages.map((m) => m.round_number)) : 0;

  const activeAgents = currentAgents.filter(isAgentActive);
  const totalAgents = activeAgents.length;
  const { statuses, completedCount } = getAgentActivityStatus(
    currentAgents,
    agentLifecycle,
    messages,
    isStreaming,
    currentRound,
  );
  // Disable every interactive roster control while a generation is
  // streaming (a server-side ``agent_index`` event could be in
  // flight) or while a roster persistence PUT is in flight (a fast
  // user must not queue a second mutation that races the first).
  const isRosterLocked = isStreaming || Boolean(isRosterSaving) || isRoundConfigurationSaving;
  const latestSynthesis = [...messages]
    .reverse()
    .find((message) => message.role === "synthesis" && message.round_number === currentRound);
  const synthesisState = (() => {
    if (streamingSynthesis?.error) return "error" as const;
    if (streamingSynthesis) return "writing" as const;
    if (latestSynthesis) {
      return (latestSynthesis.status && latestSynthesis.status !== "completed") ||
        (latestSynthesis.error &&
          latestSynthesis.error_code !== "synthesis_no_usable_contributions")
        ? ("error" as const)
        : ("complete" as const);
    }
    if (!synthesis?.enabled) return "ready" as const;
    // A configured synthesis waits for the perspective round to finish;
    // once its stream begins the branch above switches it to "writing".
    if (isStreaming) return "waiting" as const;
    return "ready" as const;
  })();
  const synthesisStateLabel =
    synthesisState === "complete"
      ? t("activity.done")
      : synthesisState === "error"
        ? t("common.error")
        : t(`activity.${synthesisState}`);
  const synthesisLifecycleIcon: ReactNode =
    synthesisState === "complete" ? (
      <MaterialSymbol name="check" decorative />
    ) : synthesisState === "error" ? (
      <MaterialSymbol name="warning" decorative />
    ) : synthesisState === "waiting" ? (
      <MaterialSymbol name="pending" decorative className="message-loading" />
    ) : synthesisState === "writing" ? (
      <span className="agent-waveform" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </span>
    ) : null;
  const synthesisEnabled = synthesis?.enabled === true;
  const completedRoundProgress = getCompletedRoundProgress(messages, currentRound);
  const hasCompletedRoundSnapshot =
    !isStreaming &&
    (completedRoundProgress.terminalAgentCount > 0 || completedRoundProgress.hasTerminalSynthesis);
  const includesSynthesis = isStreaming
    ? synthesisEnabled
    : completedRoundProgress.hasTerminalSynthesis;
  const completedSteps = hasCompletedRoundSnapshot
    ? completedRoundProgress.terminalAgentCount +
      (completedRoundProgress.hasTerminalSynthesis ? 1 : 0)
    : completedCount + (synthesisEnabled && synthesisState === "complete" ? 1 : 0);
  const totalSteps = hasCompletedRoundSnapshot
    ? completedSteps
    : totalAgents + (synthesisEnabled ? 1 : 0);
  const presentation = getProgressPresentation({
    isStreaming,
    completedCount: completedSteps,
    totalAgents: totalSteps,
    includesSynthesis,
  });

  const renderProgressBlock = () => (
    <div className="activity-progress">
      <div
        className="activity-progress-bar"
        role="progressbar"
        aria-label={t(includesSynthesis ? "activity.completedSteps" : "activity.completedAgents")}
        aria-valuemin={0}
        aria-valuemax={presentation.ariaValueMax ?? undefined}
        aria-valuenow={presentation.ariaValueNow ?? undefined}
        aria-valuetext={presentation.ariaValueText}
      >
        <div
          className={`activity-progress-fill ${completedSteps === totalSteps && totalSteps > 0 ? "is-complete" : ""}`}
          style={{ width: `${presentation.percent}%` }}
        />
      </div>
      <span className="activity-progress-label">
        {t(includesSynthesis ? "activity.stepsProgress" : "activity.agentsProgress", {
          complete: completedSteps,
          total: totalSteps,
        })}
      </span>
    </div>
  );

  const configurationIsValid = (agents: AgentConfig[], nextSynthesis: SynthesisConfig) =>
    agents.every((agent) => {
      const roleIsValid = agent.prompt_id
        ? perspectives.some((perspective) => perspective.id === agent.prompt_id)
        : !agent.enabled;
      const providerIsValid =
        hasValidProviderSelection(agent, hosts, localStatus) &&
        (!agent.enabled || Boolean(agent.host_configuration_id && agent.api_host && agent.llm_id));
      return roleIsValid && providerIsValid;
    }) &&
    Boolean(
      !nextSynthesis.enabled ||
      (hasValidProviderSelection(nextSynthesis, hosts, localStatus) &&
        Boolean(
          nextSynthesis.host_configuration_id && nextSynthesis.api_host && nextSynthesis.llm_id,
        )),
    );

  const persistConfiguration = async (agents: AgentConfig[], nextSynthesis: SynthesisConfig) => {
    if (!onApplyNextRoundConfiguration || !configurationIsValid(agents, nextSynthesis)) return;
    queuedConfigurationRef.current = { agents, synthesis: nextSynthesis };
    if (configurationSaveRunningRef.current) return;
    configurationSaveRunningRef.current = true;
    while (queuedConfigurationRef.current) {
      const next = queuedConfigurationRef.current;
      queuedConfigurationRef.current = null;
      const applied = await onApplyNextRoundConfiguration(next.agents, next.synthesis);
      if (!applied) {
        queuedConfigurationRef.current = null;
        setDraftAgents(currentAgentsRef.current.map((agent) => ({ ...agent })));
        setDraftSynthesis(synthesisRef.current ? { ...synthesisRef.current } : null);
        break;
      }
      setShowRecoveryGuidance(false);
    }
    configurationSaveRunningRef.current = false;
  };
  const openPerspectiveConfiguration = (clientId: string) => {
    setShowRecoveryGuidance(false);
    setOpenDraftOptions((previous) => ({ ...previous, [clientId]: !previous[clientId] }));
  };
  const openSynthesisConfiguration = () => {
    setShowRecoveryGuidance(false);
    setDraftSynthesisOptionsOpen((open) => !open);
  };
  const toggleAgent = (clientId: string, enabled: boolean) => {
    if (messages.length === 0 || !draftSynthesis || !onApplyNextRoundConfiguration) {
      onToggleAgent?.(clientId, enabled);
      return;
    }
    const nextAgents = draftAgents.map((agent) =>
      agent.client_id === clientId ? { ...agent, enabled } : agent,
    );
    setDraftAgents(nextAgents);
    void persistConfiguration(nextAgents, draftSynthesis);
  };
  const toggleSynthesis = (enabled: boolean) => {
    if (messages.length === 0 || !draftSynthesis || !onApplyNextRoundConfiguration) {
      onToggleSynthesis?.(enabled);
      return;
    }
    const nextSynthesis = { ...draftSynthesis, enabled };
    setDraftSynthesis(nextSynthesis);
    void persistConfiguration(draftAgents, nextSynthesis);
  };

  return (
    <div className="activity-panel">
      <div className="panel-header">{t("activity.title")}</div>

      {usesIntegratedAI && (
        <aside className="activity-info-notice" role="status">
          <MaterialSymbol name="help" decorative />
          <span>{t("activity.integratedGenerationNotice")}</span>
        </aside>
      )}

      {isStreaming ? (
        <div className="activity-streaming">
          <div className="activity-header-row">
            <span className="activity-round">{t("activity.round", { count: currentRound })}</span>
            {onStop && (
              <button
                type="button"
                className="activity-stop-btn"
                onClick={onStop}
                disabled={Boolean(isStopInProgress)}
                aria-label={t("activity.stopGeneration")}
                title={t("activity.cancelGeneration")}
              >
                {isStopInProgress ? (
                  <>
                    <MaterialSymbol name="pending" decorative className="message-loading" />{" "}
                    {t("common.stop")} …
                  </>
                ) : (
                  <>
                    <MaterialSymbol name="stop" decorative /> {t("activity.stopGeneration")}
                  </>
                )}
              </button>
            )}
            <span className="activity-timer">
              <MaterialSymbol name="schedule" decorative /> {formatTime(elapsed ?? 0)}
            </span>
          </div>

          {renderProgressBlock()}

          {!usesIntegratedAI &&
            elapsed !== null &&
            elapsed >= EXTERNAL_AI_LONG_WAIT_NOTICE_SECONDS && (
              <aside className="activity-info-notice" role="status">
                <MaterialSymbol name="schedule" decorative />
                <span>{t("activity.externalLongWaitNotice")}</span>
              </aside>
            )}
        </div>
      ) : messages.length > 0 ? (
        <div className="activity-idle">
          <div className="activity-header-row">
            <span className="activity-round">
              {roundStatus === "interrupted"
                ? t("activity.roundInterrupted", { count: currentRound })
                : roundStatus === "failed"
                  ? t("activity.roundFailed", { count: currentRound })
                  : t("activity.roundComplete", { count: currentRound })}
            </span>
            {elapsed !== null && (
              <span className="activity-timer">
                <MaterialSymbol name="schedule" decorative /> {formatTime(elapsed)}
              </span>
            )}
          </div>
          {renderProgressBlock()}
        </div>
      ) : (
        <div className="activity-empty">{t("activity.empty")}</div>
      )}

      {contextTokens != null && (
        <div className="context-usage" aria-label={t("activity.contextUsage")}>
          {contextWindowPresentation && (
            <svg
              className={`context-usage-radial is-${contextWindowPresentation.pressure}`}
              viewBox="0 0 36 36"
              aria-hidden="true"
              focusable="false"
            >
              <circle className="context-usage-radial-track" cx="18" cy="18" r="15.9155" />
              <circle
                className="context-usage-radial-value"
                cx="18"
                cy="18"
                r="15.9155"
                pathLength="100"
                strokeDasharray={`${contextWindowPresentation.radialPercentage} 100`}
              />
            </svg>
          )}
          <span className="context-usage-value">
            {contextWindowPresentation && contextWindowTokens != null
              ? t(
                  contextTokensExact
                    ? "activity.lastPerspectiveContextWindowExact"
                    : "activity.lastPerspectiveContextWindowEstimated",
                  {
                    used: formatNumber(contextTokens),
                    available: formatNumber(contextWindowTokens),
                    percent: contextWindowPresentation.percentage,
                  },
                )
              : t(
                  contextTokensExact
                    ? "activity.lastPerspectiveContextExact"
                    : "activity.lastPerspectiveContextEstimated",
                  { count: formatNumber(contextTokens) },
                )}
          </span>
        </div>
      )}

      {showRecoveryGuidance && (
        <p
          className="configuration-recovery-guidance"
          role="alert"
          ref={configurationRecoveryRef}
          tabIndex={-1}
        >
          {t("activity.providerRecoveryGuidance")}
        </p>
      )}
      {currentAgents.length > 0 && (
        <div className="agent-status-list" aria-label={t("activity.agents")}>
          {draftAgents.map((agent, idx) => {
            const slotKey = agent.client_id || String(idx);
            const optionsId = `activity-perspective-options-${slotKey}`;
            const resolved = isAgentActive(agent)
              ? statuses.find((status) => status.agent.client_id === agent.client_id)?.state
              : undefined;
            const perspectiveName = agent.prompt_id
              ? (perspectives.find((perspective) => perspective.id === agent.prompt_id)?.label ??
                agent.name)
              : t("activity.none");
            return (
              <RosterRow
                key={agent.client_id}
                agent={agent}
                slotNumber={agent.perspective_number || idx + 1}
                perspectiveName={perspectiveName}
                isFirst={idx === 0}
                isLast={idx === currentAgents.length - 1}
                isRosterLocked={isRosterLocked}
                onMoveAgent={configurationOpen ? undefined : onMoveAgent}
                onToggleAgent={toggleAgent}
                lifecycle={resolved ?? agentLifecycle[agent.client_id]}
                isActive={isAgentActive(agent)}
                onConfigure={
                  onApplyNextRoundConfiguration
                    ? () => openPerspectiveConfiguration(agent.client_id)
                    : undefined
                }
                configureExpanded={openDraftOptions[slotKey] === true}
                configureControlsId={optionsId}
                configuration={
                  openDraftOptions[slotKey] === true ? (
                    <PerspectiveConfigurationControls
                      agent={agent}
                      index={idx}
                      perspectives={perspectives}
                      roles={roles}
                      hosts={hosts}
                      localStatus={localStatus}
                      expanded
                      inline
                      disabled={isStreaming}
                      idPrefix="activity"
                      onToggleExpanded={() => openPerspectiveConfiguration(slotKey)}
                      onChange={(patch) => {
                        const nextAgents = draftAgents.map((item, itemIndex) =>
                          itemIndex === idx ? { ...item, ...patch } : item,
                        );
                        setDraftAgents(nextAgents);
                        if (draftSynthesis) void persistConfiguration(nextAgents, draftSynthesis);
                      }}
                    />
                  ) : undefined
                }
              />
            );
          })}
        </div>
      )}
      {synthesis && draftSynthesis && (isStreaming || messages.length > 0) && (
        <div
          className={`synthesis-status-row is-${synthesisState}${draftSynthesisOptionsOpen ? " is-expanded" : ""}`}
          data-synthesis-state={synthesisState}
        >
          <div className="synthesis-status-summary">
            <span className="synthesis-status-name">
              <MaterialSymbol name="account_tree" decorative /> {t("activity.synthesis")}
            </span>
            <span className={`synthesis-status-lifecycle is-${synthesisState}`}>
              {synthesisLifecycleIcon}
              {synthesisLifecycleIcon ? " " : ""}
              {synthesisStateLabel}
            </span>
            <span className="synthesis-status-controls">
              {onApplyNextRoundConfiguration && (
                <Button
                  variant="text"
                  size="small"
                  className="agent-status-options-btn synthesis-status-options-btn"
                  disabled={isStreaming || isRoundConfigurationSaving}
                  onClick={openSynthesisConfiguration}
                  aria-label={t("activity.configureSynthesis")}
                  aria-controls="activity-synthesis-options"
                  aria-expanded={draftSynthesisOptionsOpen}
                >
                  <MaterialSymbol name="tune" decorative />
                  <span>{t("setup.options")}</span>
                </Button>
              )}
              <label className="checkbox synthesis-status-toggle">
                <input
                  type="checkbox"
                  checked={draftSynthesis.enabled}
                  disabled={
                    isStreaming ||
                    Boolean(isSynthesisSaving) ||
                    isRoundConfigurationSaving ||
                    (!onToggleSynthesis && !onApplyNextRoundConfiguration)
                  }
                  onChange={(event) => toggleSynthesis(event.target.checked)}
                  aria-label={t("activity.activeSynthesis")}
                />
                {t("common.active")}
              </label>
            </span>
          </div>
          {draftSynthesisOptionsOpen && (
            <SynthesisConfigurationControls
              synthesis={draftSynthesis}
              hosts={hosts}
              localStatus={localStatus}
              expanded
              inline
              disabled={isStreaming}
              idPrefix="activity"
              onToggleExpanded={openSynthesisConfiguration}
              onChange={(patch) => {
                const nextSynthesis = { ...draftSynthesis, ...patch };
                setDraftSynthesis(nextSynthesis);
                void persistConfiguration(draftAgents, nextSynthesis);
              }}
            />
          )}
        </div>
      )}
      {roundProviderProvenance.length > 0 && (
        <details className="provider-history">
          <summary>{t("discussion.providerHistory")}</summary>
          <p>{t("discussion.providerHistoryHint")}</p>
          {/* The history table overflows locally at narrow widths and needs a keyboard scroll target. */}
          {/* eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex */}
          <div
            className="provider-history-table-wrap"
            role="region"
            aria-label={t("discussion.providerHistory")}
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("discussion.providerHistoryRound")}</th>
                  <th scope="col">{t("discussion.providerHistoryAssignment")}</th>
                  <th scope="col">{t("setup.host")}</th>
                  <th scope="col">{t("setup.model")}</th>
                </tr>
              </thead>
              {roundProviderProvenance.map((round) => (
                <tbody key={round.round_number}>
                  {round.providers.map((provider, index) => (
                    <tr
                      key={`${round.round_number}-${provider.kind}-${provider.client_id ?? "synthesis"}-${index}`}
                    >
                      {index === 0 && (
                        <th scope="rowgroup" rowSpan={round.providers.length}>
                          {round.round_number}
                        </th>
                      )}
                      <td>
                        {provider.kind === "synthesis"
                          ? t("activity.synthesis")
                          : (provider.prompt_label ??
                            currentAgents.find((agent) => agent.client_id === provider.client_id)
                              ?.name ??
                            t("setup.perspective"))}
                      </td>
                      <td>{provider.host_label ?? t("discussion.unknownHistoricalHost")}</td>
                      <td>{provider.model_id}</td>
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </details>
      )}
    </div>
  );
};

export default ActivityPanel;
