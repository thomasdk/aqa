import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { TFunction } from "i18next";
import {
  ApiError,
  cancelDiscussionGeneration,
  continueDiscussionStream,
  DiscussionStreamIncompleteError,
  getDiscussionState,
  openSession,
  setMessageContextInclusion,
  setMessageNote,
  clearMessageNote,
  startDiscussionStream,
  updateDiscussionAgents,
  updateDiscussionSynthesis,
  type StartDiscussionParams,
} from "../../api";
import { translateClientError, translateErrorCode } from "../../i18n";
import { recoverContextInclusionAfterNotFound } from "../discussionContextInclusionRecovery";
import {
  beginDiscussionGeneration,
  INITIAL_DISCUSSION_GENERATION,
  invalidateDiscussionGeneration,
  isCurrentDiscussionGeneration,
  type DiscussionGeneration,
} from "../discussionGeneration";
import {
  moveAgent as moveAgentRoster,
  setAgentEnabled as setAgentEnabledRoster,
} from "../discussionAgentRosterState";
import { createInitialAgentLifecycle, type AgentLifecycle } from "../ActivityPanel";
import type { StreamingAgent, StreamingSynthesis } from "../DiscussionView";
import type {
  AgentConfig,
  ContextUsage,
  DiscussionMessage,
  SSEEvent,
  SynthesisConfig,
} from "../types";
import { sendRoundNotification, type RoundNotificationOutcome } from "../../roundNotifications";
import {
  createGenerationOperationId,
  setGenerationOperationActive,
} from "../../generationSleepInhibition";

type ActivityLogger = (message: string, level?: "info" | "warning" | "error") => void;

type AgentCompleteEvent = Extract<SSEEvent, { type: "agent_complete" }>;
const SLEEP_INHIBITION_HEARTBEAT_MS = 15_000;

const terminalNotificationOutcome = (
  status: DiscussionStreamingSnapshot["roundStatus"],
): RoundNotificationOutcome | null => {
  if (status === "completed" || status === "failed" || status === "interrupted") return status;
  return null;
};

export const toAgentDiscussionMessage = (
  event: AgentCompleteEvent,
  roundNumber: number,
  contextUsage: ContextUsage | undefined,
): DiscussionMessage => ({
  id: event.message_id,
  role: "agent",
  content: event.text,
  round_number: roundNumber,
  status: event.status ?? (event.error ? "failed" : "completed"),
  agent_name: event.agent_name,
  theory_label: event.theory_label,
  color: event.color || null,
  agent_index: event.agent_index,
  perspective_number: event.perspective_number,
  client_id: event.client_id,
  note: "",
  include_note_in_agent_context: false,
  error: event.error,
  error_code: event.error_code ?? null,
  error_params: event.error_params ?? {},
  usage_available: event.usage_available ?? null,
  prompt_tokens: event.prompt_tokens ?? null,
  completion_tokens: event.completion_tokens ?? null,
  total_tokens: event.total_tokens ?? null,
  context_usage_available: contextUsage?.available ?? null,
  input_context_tokens: contextUsage?.input_tokens ?? null,
  context_window_tokens: contextUsage?.context_tokens ?? null,
  context_tokens_exact: contextUsage?.exact ?? null,
  omitted_round_numbers: contextUsage?.omitted_round_numbers ?? [],
  include_in_agent_context: true,
});

export type DiscussionStreamingSnapshot = {
  activeSessionFileId: string | null;
  agents: AgentConfig[];
  hasDiscussion: boolean;
  messages: DiscussionMessage[];
  roundStatus?: "in_progress" | "completed" | "interrupted" | "failed" | null;
};

export type DiscussionStreamingController = {
  readonly agentLifecycle: AgentLifecycle;
  readonly currentAgents: AgentConfig[];
  readonly hasDiscussion: boolean;
  readonly isContextInclusionSaving: boolean;
  readonly isSavingAgentRoster: boolean;
  readonly isSavingSynthesis: boolean;
  readonly isStopInProgress: boolean;
  readonly isStreaming: boolean;
  readonly latestContextUsage: ContextUsage | null;
  readonly messages: DiscussionMessage[];
  /** Absolute start time for the current round; retained above the view layer. */
  readonly roundStartedAt: number | null;
  /** Null when no duration was measured for the loaded round. */
  readonly roundElapsedSeconds: number | null;
  readonly roundStatus: "in_progress" | "completed" | "interrupted" | "failed" | null;
  readonly streamingAgents: StreamingAgent[];
  readonly streamingSynthesis: StreamingSynthesis | null;
  clear: () => void;
  acceptNextRoundConfiguration: (agents: AgentConfig[], synthesis: SynthesisConfig) => void;
  continueDiscussion: (
    userInput: string,
    focusSegment: string | null,
    targetMessageId: string | null,
    sequentialMode: boolean,
    preparedAgents?: AgentConfig[],
    providerRebind?: { configuration_id: string; model_id: string } | null,
  ) => Promise<void>;
  hydrateSnapshot: (snapshot: DiscussionStreamingSnapshot) => void;
  invalidate: () => void;
  moveAgent: (clientId: string, delta: -1 | 1) => void;
  setMessageContextInclusion: (messageId: string, include: boolean) => Promise<void>;
  setNote: (messageId: string, note: string, includeNoteInAgentContext: boolean) => Promise<void>;
  start: (params: StartDiscussionParams) => Promise<void>;
  stop: () => void;
  toggleAgent: (clientId: string, enabled: boolean) => void;
  toggleSynthesis: (enabled: boolean) => Promise<void>;
};

type UseDiscussionStreamingOptions = {
  activeSessionFileId: string | null;
  addActivity: ActivityLogger;
  onDiscussionStarted: (fileId: string | null, title: string) => void;
  onLocalAINotRunning: () => void;
  setAgents: Dispatch<SetStateAction<AgentConfig[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setSynthesis: Dispatch<SetStateAction<SynthesisConfig>>;
  synthesis: SynthesisConfig;
  t: TFunction;
};

/**
 * Owns transient discussion execution and the mutations that operate on an
 * opened discussion. The parent retains setup and session-navigation state.
 */
export function useDiscussionStreaming({
  activeSessionFileId,
  addActivity,
  onDiscussionStarted,
  onLocalAINotRunning,
  setAgents,
  setError,
  setSynthesis,
  synthesis,
  t,
}: UseDiscussionStreamingOptions): DiscussionStreamingController {
  const [messages, setMessages] = useState<DiscussionMessage[]>([]);
  const [latestContextUsage, setLatestContextUsage] = useState<ContextUsage | null>(null);
  const [streamingAgents, setStreamingAgents] = useState<StreamingAgent[]>([]);
  const [streamingSynthesis, setStreamingSynthesis] = useState<StreamingSynthesis | null>(null);
  const [agentLifecycle, setAgentLifecycle] = useState<AgentLifecycle>({});
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentAgents, setCurrentAgents] = useState<AgentConfig[]>([]);
  const [hasDiscussion, setHasDiscussion] = useState(false);
  const [roundStatus, setRoundStatus] = useState<
    "in_progress" | "completed" | "interrupted" | "failed" | null
  >(null);
  const [roundStartedAt, setRoundStartedAt] = useState<number | null>(null);
  const [roundElapsedSeconds, setRoundElapsedSeconds] = useState<number | null>(null);
  const [isStopInProgress, setIsStopInProgress] = useState(false);
  const [isSavingAgentRoster, setIsSavingAgentRoster] = useState(false);
  const [isSavingSynthesis, setIsSavingSynthesis] = useState(false);
  const [isContextInclusionSaving, setIsContextInclusionSaving] = useState(false);

  const discussionGenerationRef = useRef<DiscussionGeneration>(INITIAL_DISCUSSION_GENERATION);
  const abortControllerRef = useRef<AbortController | null>(null);
  const chunkCountRef = useRef(0);
  const currentAgentsRef = useRef<AgentConfig[]>([]);
  const contextUsageByMessageRef = useRef<Record<string, ContextUsage>>({});
  const contextInclusionSavingRef = useRef(false);
  const synthesisSaveRef = useRef(false);
  const activeSessionFileIdRef = useRef<string | null>(activeSessionFileId);
  const roundStartedAtRef = useRef<number | null>(null);
  const acceptedRunIdRef = useRef<number | null>(null);
  const notifiedRunIdRef = useRef<number | null>(null);
  const runHadErrorRef = useRef(false);
  const sleepInhibitionOperationIdRef = useRef(createGenerationOperationId());

  useEffect(() => {
    const operationId = sleepInhibitionOperationIdRef.current;
    setGenerationOperationActive(operationId, isStreaming);
    const heartbeat = isStreaming
      ? window.setInterval(
          () => setGenerationOperationActive(operationId, true),
          SLEEP_INHIBITION_HEARTBEAT_MS,
        )
      : null;
    return () => {
      if (heartbeat !== null) window.clearInterval(heartbeat);
      if (isStreaming) setGenerationOperationActive(operationId, false);
    };
  }, [isStreaming]);

  const startRoundTimer = useCallback(() => {
    const startedAt = Date.now();
    roundStartedAtRef.current = startedAt;
    setRoundStartedAt(startedAt);
    setRoundElapsedSeconds(0);
  }, []);

  const finishRoundTimer = useCallback(() => {
    const startedAt = roundStartedAtRef.current;
    if (startedAt == null) return;
    setRoundElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    roundStartedAtRef.current = null;
    setRoundStartedAt(null);
  }, []);

  const resetRoundTimer = useCallback(() => {
    roundStartedAtRef.current = null;
    setRoundStartedAt(null);
    setRoundElapsedSeconds(null);
  }, []);

  const notifyTerminalOutcome = useCallback(
    (runId: number, outcome: RoundNotificationOutcome) => {
      if (acceptedRunIdRef.current !== runId || notifiedRunIdRef.current === runId) return;
      notifiedRunIdRef.current = runId;
      const body =
        outcome === "completed"
          ? t("system.notificationCompleted")
          : outcome === "failed"
            ? t("system.notificationFailed")
            : t("system.notificationInterrupted");
      void sendRoundNotification({ title: "AQA", body });
    },
    [t],
  );

  useEffect(() => {
    activeSessionFileIdRef.current = activeSessionFileId;
  }, [activeSessionFileId]);

  const handleSSEEvent = useCallback(
    (event: SSEEvent, runId: number, isCurrentRun: () => boolean) => {
      if (event.type === "chunk") {
        chunkCountRef.current += 1;
      } else if (event.type === "user_message") {
        addActivity(t("activityLog.userMessageReceived"));
      } else if (event.type === "agent_start") {
        addActivity(t("activityLog.perspectiveStarted", { number: event.agent_index + 1 }));
      } else if (event.type === "agent_complete") {
        const failed = Boolean(event.error) || event.status === "failed";
        if (failed) runHadErrorRef.current = true;
        addActivity(
          t(failed ? "activityLog.perspectiveFailed" : "activityLog.perspectiveCompleted", {
            number: event.agent_index + 1,
            characters: event.text.length,
            chunks:
              chunkCountRef.current > 0
                ? t("activityLog.chunksSuffix", { count: chunkCountRef.current })
                : "",
          }),
          failed ? "error" : "info",
        );
        chunkCountRef.current = 0;
      } else if (event.type === "synthesis_start") {
        addActivity(t("activityLog.synthesisStarted", { round: event.round_number }));
      } else if (event.type === "synthesis_complete") {
        addActivity(t("activityLog.synthesisCompleted", { characters: event.text.length }));
      } else if (event.type === "synthesis_error") {
        runHadErrorRef.current = true;
        addActivity(t("activityLog.synthesisFailed"), "error");
      } else if (event.type === "context_usage") {
        addActivity(
          t("activityLog.contextUsage", {
            input: event.input_tokens ?? t("common.unknown"),
            window: event.context_tokens ?? t("common.unknown"),
            precision: event.exact ? t("activityLog.exact") : t("activityLog.estimated"),
          }),
        );
      } else if (event.type === "all_complete") {
        addActivity(
          t(
            runHadErrorRef.current
              ? "activityLog.discussionCompletedWithFailures"
              : "activityLog.discussionCompleted",
          ),
          runHadErrorRef.current ? "error" : "info",
        );
      } else if (event.type === "error") {
        addActivity(t("activityLog.discussionFailed"), "error");
      }

      switch (event.type) {
        case "discussion_started":
          activeSessionFileIdRef.current = event.file_id || null;
          onDiscussionStarted(activeSessionFileIdRef.current, event.title);
          break;
        case "user_message":
          setMessages((previous) => [
            ...previous,
            {
              id: event.message_id,
              role: "user",
              content: event.content,
              round_number: event.round_number,
              agent_name: null,
              theory_label: null,
              color: null,
              agent_index: null,
              perspective_number: null,
              note: "",
              include_note_in_agent_context: false,
              include_in_agent_context: true,
            },
          ]);
          break;
        case "context_usage":
          contextUsageByMessageRef.current[event.message_id] = event;
          setLatestContextUsage(event);
          break;
        case "agent_start":
          setAgentLifecycle((previous) => {
            if (previous[event.client_id] === "complete" || previous[event.client_id] === "error") {
              return previous;
            }
            return { ...previous, [event.client_id]: "streaming" };
          });
          setStreamingAgents((previous) => {
            if (previous.some((agent) => agent.message_id === event.message_id)) return previous;
            return [
              ...previous,
              {
                message_id: event.message_id,
                agent_index: event.agent_index,
                agent_name: event.agent_name,
                client_id: event.client_id,
                perspective_number: event.perspective_number,
                theory_label: event.theory_label,
                color: event.color,
                text: "",
                is_complete: false,
                error: null,
                error_code: null,
                error_params: {},
              },
            ];
          });
          break;
        case "chunk":
          setStreamingAgents((previous) =>
            previous.map((agent) =>
              agent.agent_index === event.agent_index
                ? { ...agent, text: agent.text + event.text }
                : agent,
            ),
          );
          break;
        case "agent_complete": {
          setStreamingAgents((previous) =>
            previous.filter((agent) => agent.message_id !== event.message_id),
          );
          const agent = currentAgentsRef.current[event.agent_index];
          if (agent) {
            setAgentLifecycle((previous) => {
              if (
                previous[agent.client_id] === "complete" ||
                previous[agent.client_id] === "error"
              ) {
                return previous;
              }
              return {
                ...previous,
                [agent.client_id]: event.error || event.status === "failed" ? "error" : "complete",
              };
            });
          }
          setMessages((previous) => {
            const contextUsage = contextUsageByMessageRef.current[event.message_id];
            const next = toAgentDiscussionMessage(
              event,
              previous.length > 0
                ? Math.max(...previous.map((message) => message.round_number))
                : 1,
              contextUsage,
            );
            const existingIndex = previous.findIndex((message) => message.id === event.message_id);
            if (existingIndex >= 0) {
              return previous.map((message, index) => (index === existingIndex ? next : message));
            }
            return [...previous, next];
          });
          break;
        }
        case "synthesis_start":
          setStreamingSynthesis((previous) =>
            previous?.message_id === event.message_id
              ? previous
              : {
                  message_id: event.message_id,
                  round_number: event.round_number,
                  text: "",
                  error: null,
                  error_code: null,
                  error_params: {},
                },
          );
          break;
        case "synthesis_chunk":
          setStreamingSynthesis((previous) =>
            previous?.message_id === event.message_id
              ? { ...previous, text: previous.text + event.text }
              : previous,
          );
          break;
        case "synthesis_complete":
          setStreamingSynthesis((previous) =>
            previous?.message_id === event.message_id ? null : previous,
          );
          setMessages((previous) => {
            const existingIndex = previous.findIndex((message) => message.id === event.message_id);
            if (existingIndex >= 0) {
              return previous.map((message, index) =>
                index === existingIndex
                  ? {
                      ...message,
                      content: event.text,
                      status: event.status ?? "completed",
                      error_code: event.error_code ?? null,
                      error_params: event.error_params ?? {},
                    }
                  : message,
              );
            }
            return [
              ...previous,
              {
                id: event.message_id,
                role: "synthesis",
                content: event.text,
                round_number: event.round_number,
                status: event.status ?? "completed",
                agent_name: null,
                theory_label: null,
                color: null,
                agent_index: null,
                perspective_number: null,
                note: "",
                include_note_in_agent_context: false,
                error_code: event.error_code ?? null,
                error_params: event.error_params ?? {},
                include_in_agent_context: false,
                usage_available: event.usage_available ?? null,
                prompt_tokens: event.prompt_tokens ?? null,
                completion_tokens: event.completion_tokens ?? null,
                total_tokens: event.total_tokens ?? null,
              },
            ];
          });
          break;
        case "synthesis_error":
          setStreamingSynthesis((previous) =>
            previous?.message_id === event.message_id ? null : previous,
          );
          setMessages((previous) => {
            const existingIndex = previous.findIndex((message) => message.id === event.message_id);
            if (existingIndex >= 0) {
              return previous.map((message, index) =>
                index === existingIndex
                  ? {
                      ...message,
                      content: event.text ?? message.content,
                      status: event.status ?? "failed",
                      error: event.message,
                      error_code: event.error_code ?? null,
                      error_params: event.error_params ?? {},
                    }
                  : message,
              );
            }
            return [
              ...previous,
              {
                id: event.message_id,
                role: "synthesis",
                content: event.text ?? "",
                round_number: event.round_number,
                status: event.status ?? "failed",
                agent_name: null,
                theory_label: null,
                color: null,
                agent_index: null,
                perspective_number: null,
                note: "",
                include_note_in_agent_context: false,
                include_in_agent_context: false,
                error: event.message,
                error_code: event.error_code ?? null,
                error_params: event.error_params ?? {},
              },
            ];
          });
          break;
        case "all_complete": {
          if (!isCurrentRun()) break;
          const fallbackOutcome = runHadErrorRef.current ? "failed" : "completed";
          finishRoundTimer();
          setIsStreaming(false);
          setStreamingAgents([]);
          setStreamingSynthesis(null);
          setHasDiscussion(true);
          void getDiscussionState()
            .then((state) => {
              if (!isCurrentRun()) return;
              setRoundStatus(state.round_status ?? null);
              const outcome = terminalNotificationOutcome(state.round_status);
              if (outcome) notifyTerminalOutcome(runId, outcome);
              setMessages((previous) => {
                const byId = new Map(previous.map((message) => [message.id, message]));
                for (const message of state.messages) {
                  const existing = byId.get(message.id);
                  if (!existing) byId.set(message.id, message);
                  else
                    byId.set(message.id, {
                      ...existing,
                      ...message,
                      note: message.note || existing.note,
                    });
                }
                return Array.from(byId.values());
              });
            })
            .catch((error: unknown) => {
              if (!isCurrentRun()) return;
              console.error("Failed to refresh state:", error);
              setError(t("errors.discussionState"));
              setIsStreaming(false);
              notifyTerminalOutcome(runId, fallbackOutcome);
            });
          break;
        }
        case "error":
          finishRoundTimer();
          setError(translateErrorCode(event.error_code, event.error_params));
          setIsStreaming(false);
          setRoundStatus("failed");
          setStreamingAgents([]);
          setStreamingSynthesis(null);
          notifyTerminalOutcome(runId, "failed");
          void getDiscussionState()
            .then((state) => {
              if (!isCurrentRun()) return;
              setRoundStatus(state.round_status ?? "failed");
              setMessages(state.messages);
              setHasDiscussion(state.has_active_discussion);
            })
            .catch(() => undefined);
          break;
      }
    },
    [addActivity, finishRoundTimer, notifyTerminalOutcome, onDiscussionStarted, setError, t],
  );

  const applyEventForRun = useCallback(
    (event: SSEEvent, runId: number) => {
      if (!isCurrentDiscussionGeneration(discussionGenerationRef.current, runId)) return;
      acceptedRunIdRef.current = runId;
      handleSSEEvent(event, runId, () =>
        isCurrentDiscussionGeneration(discussionGenerationRef.current, runId),
      );
    },
    [handleSSEEvent],
  );

  const invalidate = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    discussionGenerationRef.current = invalidateDiscussionGeneration(
      discussionGenerationRef.current,
    );
  }, []);

  const clearStreamingUI = useCallback(() => {
    setIsStreaming(false);
    setStreamingAgents([]);
    setStreamingSynthesis(null);
    setAgentLifecycle({});
  }, []);

  const handleIncompleteStream = useCallback(
    (runId: number) => {
      const sessionIdAtRequest = activeSessionFileIdRef.current;
      const isCurrentRecovery = () =>
        isCurrentDiscussionGeneration(discussionGenerationRef.current, runId) &&
        activeSessionFileIdRef.current === sessionIdAtRequest;
      finishRoundTimer();
      addActivity(t("activityLog.discussionFailed"), "error");
      setError(translateErrorCode("discussion_generation_interrupted"));
      clearStreamingUI();
      setRoundStatus("interrupted");
      notifyTerminalOutcome(runId, "interrupted");
      void cancelDiscussionGeneration()
        .then(() => {
          if (!isCurrentRecovery()) return null;
          return getDiscussionState();
        })
        .then((state) => {
          if (!state || !isCurrentRecovery()) return;
          setRoundStatus(state.round_status ?? "interrupted");
          setMessages(state.messages);
          setHasDiscussion(state.has_active_discussion);
        })
        .catch((error: unknown) => {
          console.debug("[Discussion] incomplete stream recovery failed (non-fatal):", error);
        });
    },
    [addActivity, clearStreamingUI, finishRoundTimer, notifyTerminalOutcome, setError, t],
  );

  const clear = useCallback(() => {
    invalidate();
    clearStreamingUI();
    setIsStopInProgress(false);
    contextUsageByMessageRef.current = {};
    setLatestContextUsage(null);
    setMessages([]);
    setCurrentAgents([]);
    currentAgentsRef.current = [];
    setHasDiscussion(false);
    setRoundStatus(null);
    resetRoundTimer();
  }, [clearStreamingUI, invalidate, resetRoundTimer]);

  const hydrateSnapshot = useCallback(
    (snapshot: DiscussionStreamingSnapshot) => {
      invalidate();
      clearStreamingUI();
      setIsStopInProgress(false);
      contextUsageByMessageRef.current = {};
      setLatestContextUsage(null);
      setMessages(snapshot.messages);
      setCurrentAgents(snapshot.agents);
      currentAgentsRef.current = snapshot.agents;
      setHasDiscussion(snapshot.hasDiscussion);
      setRoundStatus(snapshot.roundStatus ?? null);
      activeSessionFileIdRef.current = snapshot.activeSessionFileId;
      resetRoundTimer();
    },
    [clearStreamingUI, invalidate, resetRoundTimer],
  );

  const stop = useCallback(() => {
    if (isStopInProgress || !abortControllerRef.current) return;
    const stoppedRunId = discussionGenerationRef.current.id;
    const sessionIdAtRequest = activeSessionFileIdRef.current;
    const refreshGenerationId = discussionGenerationRef.current.id + 1;
    setIsStopInProgress(true);
    invalidate();
    const isCurrentRecovery = () =>
      isCurrentDiscussionGeneration(discussionGenerationRef.current, refreshGenerationId) &&
      activeSessionFileIdRef.current === sessionIdAtRequest;
    finishRoundTimer();
    setIsStreaming(false);
    setStreamingAgents([]);
    setStreamingSynthesis(null);
    addActivity(t("activityLog.discussionCancelled"));
    void cancelDiscussionGeneration()
      .then(() => {
        if (!isCurrentRecovery()) return null;
        notifyTerminalOutcome(stoppedRunId, "interrupted");
        return getDiscussionState();
      })
      .then((state) => {
        if (!state || !isCurrentRecovery()) return;
        setRoundStatus(state.round_status ?? "interrupted");
        setMessages(state.messages);
        setHasDiscussion(state.has_active_discussion);
      })
      .catch((error: unknown) => {
        console.debug("[Discussion] cancelDiscussionGeneration failed (non-fatal):", error);
      })
      .finally(() => {
        if (isCurrentRecovery()) setIsStopInProgress(false);
      });
  }, [addActivity, finishRoundTimer, invalidate, isStopInProgress, notifyTerminalOutcome, t]);

  const start = useCallback(
    async (params: StartDiscussionParams) => {
      abortControllerRef.current?.abort();
      const generation = beginDiscussionGeneration(discussionGenerationRef.current);
      discussionGenerationRef.current = generation;
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const runId = generation.id;

      setIsStopInProgress(false);
      startRoundTimer();
      setIsStreaming(true);
      setStreamingAgents([]);
      setStreamingSynthesis(null);
      setMessages([]);
      setRoundStatus("in_progress");
      runHadErrorRef.current = false;
      contextUsageByMessageRef.current = {};
      setLatestContextUsage(null);
      currentAgentsRef.current = params.agents;
      setCurrentAgents(params.agents);
      setAgentLifecycle(createInitialAgentLifecycle(params.agents));
      setHasDiscussion(true);
      activeSessionFileIdRef.current = null;
      onDiscussionStarted(null, "");
      setError(null);
      addActivity(
        t("activityLog.discussionStarted", {
          count: params.agents.filter((agent) => agent.enabled).length,
        }),
      );

      try {
        for await (const event of startDiscussionStream(params, { signal: controller.signal })) {
          applyEventForRun(event, runId);
        }
      } catch (error: unknown) {
        if (!isCurrentDiscussionGeneration(discussionGenerationRef.current, runId)) return;
        if ((error as Error).name === "AbortError") return;
        if (error instanceof DiscussionStreamIncompleteError) {
          handleIncompleteStream(runId);
          return;
        }
        if (error instanceof ApiError && error.code === "local_ai_not_running") {
          setError(translateErrorCode(error.code, error.params));
          onLocalAINotRunning();
          setIsStreaming(false);
          finishRoundTimer();
          return;
        }
        addActivity(t("activityLog.discussionFailed"), "error");
        setError(
          error instanceof ApiError
            ? translateErrorCode(error.code, error.params)
            : t("errors.discussionFailed"),
        );
        finishRoundTimer();
        clearStreamingUI();
        notifyTerminalOutcome(runId, "failed");
      }
    },
    [
      addActivity,
      applyEventForRun,
      clearStreamingUI,
      handleIncompleteStream,
      finishRoundTimer,
      onDiscussionStarted,
      onLocalAINotRunning,
      notifyTerminalOutcome,
      setError,
      startRoundTimer,
      t,
    ],
  );

  const continueDiscussion = useCallback(
    async (
      userInput: string,
      focusSegment: string | null,
      _targetMessageId: string | null,
      sequentialMode: boolean,
      preparedAgents?: AgentConfig[],
      providerRebind?: { configuration_id: string; model_id: string } | null,
    ) => {
      if (synthesisSaveRef.current) {
        setError(t("errors.synthesisPending"));
        return;
      }
      abortControllerRef.current?.abort();
      const generation = beginDiscussionGeneration(discussionGenerationRef.current);
      discussionGenerationRef.current = generation;
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const runId = generation.id;
      setIsStopInProgress(false);
      startRoundTimer();
      setIsStreaming(true);
      setStreamingAgents([]);
      setStreamingSynthesis(null);
      runHadErrorRef.current = false;
      contextUsageByMessageRef.current = {};
      setLatestContextUsage(null);
      const roundAgents = preparedAgents ?? currentAgents;
      currentAgentsRef.current = roundAgents;
      setCurrentAgents(roundAgents);
      setAgentLifecycle(createInitialAgentLifecycle(roundAgents));

      try {
        for await (const event of continueDiscussionStream(
          {
            user_input: userInput,
            agents: roundAgents,
            focus_segment: focusSegment,
            sequential_mode: sequentialMode,
            provider_rebind: providerRebind,
          },
          { signal: controller.signal },
        )) {
          applyEventForRun(event, runId);
        }
      } catch (error: unknown) {
        if (!isCurrentDiscussionGeneration(discussionGenerationRef.current, runId)) return;
        if ((error as Error).name === "AbortError") return;
        if (error instanceof DiscussionStreamIncompleteError) {
          handleIncompleteStream(runId);
          return;
        }
        addActivity(t("activityLog.discussionFailed"), "error");
        setError(translateClientError(error, "errors.continuationFailed"));
        setCurrentAgents(currentAgents);
        setAgentLifecycle(createInitialAgentLifecycle(currentAgents));
        finishRoundTimer();
        clearStreamingUI();
        notifyTerminalOutcome(runId, "failed");
        throw error;
      }
    },
    [
      addActivity,
      applyEventForRun,
      clearStreamingUI,
      currentAgents,
      finishRoundTimer,
      handleIncompleteStream,
      notifyTerminalOutcome,
      setError,
      startRoundTimer,
      t,
    ],
  );

  const setNote = useCallback(
    async (messageId: string, note: string, includeNoteInAgentContext: boolean) => {
      const normalizedNote = note.trim();
      const includeWithNote = Boolean(normalizedNote && includeNoteInAgentContext);
      const previousMessage = messages.find((message) => message.id === messageId);
      setMessages((previous) =>
        previous.map((message) =>
          message.id === messageId
            ? { ...message, note: normalizedNote, include_note_in_agent_context: includeWithNote }
            : message,
        ),
      );
      try {
        setError(null);
        if (normalizedNote) await setMessageNote(messageId, normalizedNote, includeWithNote);
        else await clearMessageNote(messageId);
      } catch (error: unknown) {
        if (previousMessage) {
          setMessages((previous) =>
            previous.map((message) =>
              message.id === messageId
                ? {
                    ...message,
                    note: previousMessage.note,
                    include_note_in_agent_context: previousMessage.include_note_in_agent_context,
                  }
                : message,
            ),
          );
        }
        try {
          const state = await getDiscussionState();
          setMessages(state.messages);
        } catch {
          // The local rollback is still truthful when the refresh is unavailable.
        }
        setError(translateClientError(error, "errors.noteSave"));
      }
    },
    [messages, setError],
  );

  const setMessageContextInclusionCommand = useCallback(
    async (messageId: string, include: boolean) => {
      if (contextInclusionSavingRef.current) return;
      const target = messages.find((message) => message.id === messageId);
      if (!target || target.include_in_agent_context === include) return;
      contextInclusionSavingRef.current = true;
      setIsContextInclusionSaving(true);
      const restoreTarget = () =>
        setMessages((previous) =>
          previous.map((message) =>
            message.id === messageId
              ? {
                  ...message,
                  include_in_agent_context: target.include_in_agent_context,
                  include_note_in_agent_context: target.include_note_in_agent_context,
                }
              : message,
          ),
        );
      setMessages((previous) =>
        previous.map((message) =>
          message.id === messageId
            ? {
                ...message,
                include_in_agent_context: include,
                ...(include ? {} : { include_note_in_agent_context: false }),
              }
            : message,
        ),
      );
      try {
        await setMessageContextInclusion(messageId, include);
      } catch (error: unknown) {
        if (error instanceof ApiError && error.code === "conflict") {
          try {
            const state = await getDiscussionState();
            setMessages(state.messages);
            setError(t("errors.contextLocked"));
          } catch {
            restoreTarget();
            setError(t("errors.contextRefresh"));
          }
          return;
        }
        try {
          const recoveredState = await recoverContextInclusionAfterNotFound(
            error,
            activeSessionFileIdRef.current,
            openSession,
            getDiscussionState,
            () => setMessageContextInclusion(messageId, include),
          );
          if (recoveredState) {
            setMessages(
              recoveredState.messages.map((message) =>
                message.id === messageId
                  ? {
                      ...message,
                      include_in_agent_context: include,
                      ...(include ? {} : { include_note_in_agent_context: false }),
                    }
                  : message,
              ),
            );
            return;
          }
        } catch {
          restoreTarget();
          setError(t("errors.contextRecovery"));
          return;
        }
        restoreTarget();
        setError(translateClientError(error, "errors.contextSave"));
      } finally {
        contextInclusionSavingRef.current = false;
        setIsContextInclusionSaving(false);
      }
    },
    [messages, setError, t],
  );

  const persistCurrentAgents = useCallback(
    async (next: AgentConfig[]) => {
      if (isStreaming || isSavingAgentRoster) return;
      const previous = currentAgents;
      setCurrentAgents(next);
      setAgents(next);
      currentAgentsRef.current = next;
      setIsSavingAgentRoster(true);
      try {
        await updateDiscussionAgents(next);
      } catch (error: unknown) {
        setCurrentAgents(previous);
        setAgents(previous);
        currentAgentsRef.current = previous;
        setError(translateClientError(error, "errors.agentsSave"));
      } finally {
        setIsSavingAgentRoster(false);
      }
    },
    [currentAgents, isSavingAgentRoster, isStreaming, setAgents, setError],
  );

  const moveAgent = useCallback(
    (clientId: string, delta: -1 | 1) => {
      if (isStreaming || isSavingAgentRoster) return;
      const index = currentAgents.findIndex((agent) => agent.client_id === clientId);
      if (index < 0) return;
      const next = moveAgentRoster(currentAgents, index, delta);
      if (next === currentAgents) return;
      void persistCurrentAgents([...next]);
    },
    [currentAgents, isSavingAgentRoster, isStreaming, persistCurrentAgents],
  );

  const toggleAgent = useCallback(
    (clientId: string, enabled: boolean) => {
      if (isStreaming || isSavingAgentRoster) return;
      void persistCurrentAgents([...setAgentEnabledRoster(currentAgents, clientId, enabled)]);
    },
    [currentAgents, isSavingAgentRoster, isStreaming, persistCurrentAgents],
  );

  const toggleSynthesis = useCallback(
    async (enabled: boolean) => {
      if (isStreaming || synthesisSaveRef.current || synthesis.enabled === enabled) return;
      const previous = synthesis;
      const next = { ...previous, enabled };
      const sessionIdAtRequest = activeSessionFileIdRef.current;
      if (!sessionIdAtRequest) return;
      setSynthesis(next);
      synthesisSaveRef.current = true;
      setIsSavingSynthesis(true);
      try {
        await updateDiscussionSynthesis(sessionIdAtRequest, next);
      } catch (error: unknown) {
        if (activeSessionFileIdRef.current === sessionIdAtRequest) {
          setSynthesis(previous);
          setError(translateClientError(error, "errors.synthesisSave"));
        }
      } finally {
        synthesisSaveRef.current = false;
        setIsSavingSynthesis(false);
      }
    },
    [isStreaming, setError, setSynthesis, synthesis],
  );

  const acceptNextRoundConfiguration = useCallback(
    (nextAgents: AgentConfig[], nextSynthesis: SynthesisConfig) => {
      currentAgentsRef.current = nextAgents;
      setCurrentAgents(nextAgents);
      setAgents(nextAgents);
      setSynthesis(nextSynthesis);
    },
    [setAgents, setSynthesis],
  );

  return useMemo(
    () => ({
      acceptNextRoundConfiguration,
      agentLifecycle,
      clear,
      continueDiscussion,
      currentAgents,
      hasDiscussion,
      hydrateSnapshot,
      invalidate,
      isContextInclusionSaving,
      isSavingAgentRoster,
      isSavingSynthesis,
      isStopInProgress,
      isStreaming,
      latestContextUsage,
      messages,
      roundStatus,
      roundElapsedSeconds,
      roundStartedAt,
      moveAgent,
      setMessageContextInclusion: setMessageContextInclusionCommand,
      setNote,
      start,
      stop,
      streamingAgents,
      streamingSynthesis,
      toggleAgent,
      toggleSynthesis,
    }),
    [
      acceptNextRoundConfiguration,
      agentLifecycle,
      clear,
      continueDiscussion,
      currentAgents,
      hasDiscussion,
      hydrateSnapshot,
      invalidate,
      isContextInclusionSaving,
      isSavingAgentRoster,
      isSavingSynthesis,
      isStopInProgress,
      isStreaming,
      latestContextUsage,
      messages,
      roundStatus,
      roundElapsedSeconds,
      roundStartedAt,
      moveAgent,
      setMessageContextInclusionCommand,
      setNote,
      start,
      stop,
      streamingAgents,
      streamingSynthesis,
      toggleAgent,
      toggleSynthesis,
    ],
  );
}
