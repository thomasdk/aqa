import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import {
  getPerspectives,
  getSessionTypes,
  getLocalAIStatus,
  listHosts,
  listQuickActions,
  listRoles,
  startLocalAI,
  type QuickAction,
} from "../../api";
import {
  defaultSelectionForAISource,
  readPreferredAISource,
  usesIntegratedAI,
  type AISource,
} from "../aiSourceSelection";
import { getStartableLocalAIModelId } from "../localAIState";
import { isLocalAIUsable } from "../AIReadinessIndicator";
import { reconcileDraftAgentHostSelections, type AgentHostSelection } from "../hostModelSelection";
import type {
  AgentConfig,
  HostInfo,
  LocalAIStatus,
  Perspective,
  Role,
  SessionType,
  SynthesisConfig,
} from "../types";
import { selectPersistedAISource } from "../../uiPreferences";
import type { SessionHydrationController } from "./useSessionHydration";
import { useLocalAIStatus } from "./useLocalAIStatus";

export type WorkbenchCatalogController = {
  acceptLocalAIStatus: (status: NonNullable<ReturnType<typeof useLocalAIStatus>["status"]>) => void;
  readonly aiSource: AISource;
  readonly hosts: HostInfo[];
  readonly hostsLoaded: boolean;
  readonly isStartingIntegratedAI: boolean;
  readonly localAIStatus: ReturnType<typeof useLocalAIStatus>["status"];
  readonly localAIStatusFailed: boolean;
  readonly perspectives: Perspective[];
  readonly quickActions: QuickAction[];
  readonly roles: Role[];
  readonly sessionTypes: SessionType[];
  defaultHostSelection: () => AgentHostSelection;
  prepareDiscussionStart: (
    agents: AgentConfig[],
    synthesis: SynthesisConfig,
  ) => Promise<{ agents: AgentConfig[]; synthesis: SynthesisConfig } | null>;
  refreshHosts: () => Promise<void>;
  refreshPerspectives: () => Promise<void>;
  refreshQuickActions: () => Promise<void>;
  refreshSessionTypes: () => Promise<void>;
  selectAISource: (source: AISource) => void;
};

type UseWorkbenchCatalogsOptions = {
  hasDiscussionRef: MutableRefObject<boolean>;
  sessionRef: MutableRefObject<SessionHydrationController | null>;
  view: string;
};

// The managed backend allows 120 seconds for model loading; keep a small margin for status delivery.
const LOCAL_AI_READINESS_TIMEOUT_MS = 130_000;
const LOCAL_AI_READINESS_POLL_MS = 500;

const waitForStatusBefore = (deadline: number): Promise<LocalAIStatus> => {
  const remaining = Math.max(0, deadline - Date.now());
  return new Promise<LocalAIStatus>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error("Managed Integrated AI did not become ready.")),
      remaining,
    );
    void getLocalAIStatus().then(
      (status) => {
        window.clearTimeout(timer);
        resolve(status);
      },
      (error: unknown) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
};

export const waitForManagedLocalAI = async (
  initialStatus: LocalAIStatus,
  onStatus: (status: LocalAIStatus) => void,
): Promise<LocalAIStatus> => {
  let status = initialStatus;
  const deadline = Date.now() + LOCAL_AI_READINESS_TIMEOUT_MS;
  while (!isLocalAIUsable(status)) {
    if (status.state !== "starting" || Date.now() >= deadline) {
      throw new Error("Managed Integrated AI did not become ready.");
    }
    try {
      status = await waitForStatusBefore(deadline);
      onStatus(status);
    } catch {
      if (Date.now() >= deadline) {
        throw new Error("Managed Integrated AI did not become ready.");
      }
    }
    if (isLocalAIUsable(status)) return status;
    if (status.state !== "starting") {
      throw new Error("Managed Integrated AI did not become ready.");
    }
    const delay = Math.min(LOCAL_AI_READINESS_POLL_MS, deadline - Date.now());
    await new Promise<void>((resolve) => window.setTimeout(resolve, delay));
  }
  return status;
};

/** Owns mutable setup catalogues and the selected AI source. */
export function useWorkbenchCatalogs({
  hasDiscussionRef,
  sessionRef,
  view,
}: UseWorkbenchCatalogsOptions): WorkbenchCatalogController {
  const [aiSource, setAISource] = useState<AISource>(readPreferredAISource);
  const [perspectives, setPerspectives] = useState<Perspective[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [sessionTypes, setSessionTypes] = useState<SessionType[]>([]);
  const [quickActions, setQuickActions] = useState<QuickAction[]>([]);
  const [hosts, setHosts] = useState<HostInfo[]>([]);
  const [hostsLoaded, setHostsLoaded] = useState(false);
  const [isStartingIntegratedAI, setIsStartingIntegratedAI] = useState(false);
  const hostsRef = useRef<HostInfo[]>([]);
  const aiSourceRef = useRef(aiSource);
  const hostRequestRef = useRef(0);
  const integratedAIStartRef = useRef(false);
  const mountedRef = useRef(true);
  const {
    acceptStatus,
    failed: localAIStatusFailed,
    status: localAIStatus,
  } = useLocalAIStatus(view);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      hostRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    aiSourceRef.current = aiSource;
  }, [aiSource]);

  const defaultHostSelection = useCallback(
    (): AgentHostSelection => defaultSelectionForAISource(aiSourceRef.current, hostsRef.current),
    [],
  );

  const mayUpdateDraft = useCallback(
    () => !hasDiscussionRef.current && !sessionRef.current?.isSnapshotAuthoritative,
    [hasDiscussionRef, sessionRef],
  );

  const reconcileDraftHosts = useCallback(
    (previousHosts: readonly HostInfo[], nextHosts: readonly HostInfo[]) => {
      if (!mayUpdateDraft()) return;
      const session = sessionRef.current;
      if (!session) return;
      session.updateDraftAgents((previousAgents) =>
        reconcileDraftAgentHostSelections(previousAgents, previousHosts, nextHosts, (catalogue) =>
          defaultSelectionForAISource(aiSourceRef.current, catalogue as HostInfo[]),
        ),
      );
      session.updateDraftSynthesis((previousSynthesis) => {
        const [reconciled] = reconcileDraftAgentHostSelections(
          [previousSynthesis],
          previousHosts,
          nextHosts,
          (catalogue) => defaultSelectionForAISource(aiSourceRef.current, catalogue as HostInfo[]),
        );
        return reconciled;
      });
    },
    [mayUpdateDraft, sessionRef],
  );

  const refreshHosts = useCallback(async (): Promise<void> => {
    const requestId = ++hostRequestRef.current;
    const previousHosts = hostsRef.current;
    const nextHosts = await listHosts();
    if (!mountedRef.current || hostRequestRef.current !== requestId) return;
    hostsRef.current = nextHosts;
    setHosts(nextHosts);
    setHostsLoaded(true);
    reconcileDraftHosts(previousHosts, nextHosts);
  }, [reconcileDraftHosts]);

  const refreshPerspectives = useCallback(async (): Promise<void> => {
    const [nextPerspectives, nextRoles] = await Promise.all([getPerspectives(), listRoles()]);
    if (!mountedRef.current) return;
    setPerspectives(nextPerspectives);
    setRoles(Array.isArray(nextRoles) ? nextRoles : []);
    if (!mayUpdateDraft()) return;
    sessionRef.current?.updateDraftAgents((previous) => {
      const validIds = new Set(nextPerspectives.map((item) => item.id));
      return previous.map((agent) =>
        agent.prompt_id !== null && !validIds.has(agent.prompt_id)
          ? { ...agent, prompt_id: null, enabled: false }
          : agent,
      );
    });
  }, [mayUpdateDraft, sessionRef]);

  const refreshSessionTypes = useCallback(async (): Promise<void> => {
    const nextSessionTypes = await getSessionTypes();
    if (!mountedRef.current) return;
    setSessionTypes(nextSessionTypes);
    const session = sessionRef.current;
    if (!session || session.isSnapshotAuthoritative) return;
    const selected = nextSessionTypes.some((item) => item.key === session.sessionType)
      ? session.sessionType
      : (nextSessionTypes[0]?.key ?? "");
    if (selected !== session.sessionType) session.selectSessionType(selected);
  }, [sessionRef]);

  const refreshQuickActions = useCallback(async (): Promise<void> => {
    const nextQuickActions = await listQuickActions();
    if (mountedRef.current) setQuickActions(nextQuickActions.actions);
  }, []);

  const selectAISource = useCallback(
    (source: AISource) => {
      aiSourceRef.current = source;
      setAISource(source);
      selectPersistedAISource(source);
      if (!mayUpdateDraft()) return;
      const selection = defaultSelectionForAISource(source, hostsRef.current);
      sessionRef.current?.updateDraftAgents((previous) =>
        previous.map((agent) => ({ ...agent, ...selection })),
      );
      sessionRef.current?.updateDraftSynthesis((previous) => ({ ...previous, ...selection }));
    },
    [mayUpdateDraft, sessionRef],
  );

  const prepareDiscussionStart = useCallback(
    async (agents: AgentConfig[], synthesis: SynthesisConfig) => {
      if (integratedAIStartRef.current) return null;
      const requiresIntegratedAI =
        aiSourceRef.current === "integrated" ||
        usesIntegratedAI(agents, synthesis, hostsRef.current);
      if (!requiresIntegratedAI) {
        return { agents, synthesis };
      }

      const bindCurrentManagedHost = async () => {
        await refreshHosts();
        const localSelection = defaultSelectionForAISource("integrated", hostsRef.current);
        if (
          !localSelection.host_configuration_id ||
          !localSelection.api_host ||
          !localSelection.llm_id
        ) {
          throw new Error("Managed Integrated AI host is not available.");
        }
        const replaceDraftDefaults = aiSourceRef.current === "integrated" && mayUpdateDraft();
        const bindSelection = <T extends AgentHostSelection>(selection: T): T =>
          replaceDraftDefaults ||
          selection.host_configuration_id === localSelection.host_configuration_id
            ? { ...selection, ...localSelection }
            : selection;
        const preparedAgents = agents.map(bindSelection);
        const preparedSynthesis = bindSelection(synthesis);
        if (mayUpdateDraft()) {
          sessionRef.current?.updateDraftAgents(preparedAgents);
          sessionRef.current?.updateDraftSynthesis(preparedSynthesis);
        }
        return { agents: preparedAgents, synthesis: preparedSynthesis };
      };

      if (isLocalAIUsable(localAIStatus)) return bindCurrentManagedHost();
      const localModelId = getStartableLocalAIModelId(localAIStatus);
      const existingStart = localAIStatus?.state === "starting" ? localAIStatus : null;
      if (!localModelId && !existingStart) {
        throw new Error("Managed Integrated AI is not startable.");
      }

      integratedAIStartRef.current = true;
      setIsStartingIntegratedAI(true);
      try {
        let startedStatus = existingStart;
        if (localModelId) {
          startedStatus = await startLocalAI({
            model_id: localModelId,
            context_tokens: localAIStatus?.context_tokens ?? 32_768,
            mtp_enabled: Boolean(localAIStatus?.mtp_enabled),
            ...(localAIStatus?.mtp_enabled ? { mtp_draft_tokens: 4 } : {}),
          });
        }
        if (!startedStatus) throw new Error("Managed Integrated AI is not startable.");
        const readyStatus = await waitForManagedLocalAI(startedStatus, acceptStatus);
        acceptStatus(readyStatus);
        return bindCurrentManagedHost();
      } finally {
        integratedAIStartRef.current = false;
        if (mountedRef.current) setIsStartingIntegratedAI(false);
      }
    },
    [acceptStatus, localAIStatus, mayUpdateDraft, refreshHosts, sessionRef],
  );

  useEffect(() => {
    void refreshPerspectives().catch((error: unknown) => {
      console.error("Failed to load perspectives:", error);
    });
    void refreshSessionTypes().catch((error: unknown) => {
      console.error("Failed to load session types:", error);
    });
    void refreshQuickActions().catch((error: unknown) => {
      console.error("Failed to load quick actions:", error);
    });
    void refreshHosts().catch((error: unknown) => {
      console.error("Failed to load hosts:", error);
    });
  }, [refreshHosts, refreshPerspectives, refreshQuickActions, refreshSessionTypes]);

  return useMemo(
    () => ({
      acceptLocalAIStatus: acceptStatus,
      aiSource,
      defaultHostSelection,
      hosts,
      hostsLoaded,
      isStartingIntegratedAI,
      localAIStatus,
      localAIStatusFailed,
      perspectives,
      prepareDiscussionStart,
      quickActions,
      refreshHosts,
      refreshPerspectives,
      refreshQuickActions,
      refreshSessionTypes,
      roles,
      selectAISource,
      sessionTypes,
    }),
    [
      aiSource,
      acceptStatus,
      defaultHostSelection,
      hosts,
      hostsLoaded,
      isStartingIntegratedAI,
      localAIStatus,
      localAIStatusFailed,
      perspectives,
      prepareDiscussionStart,
      quickActions,
      refreshHosts,
      refreshPerspectives,
      refreshQuickActions,
      refreshSessionTypes,
      roles,
      selectAISource,
      sessionTypes,
    ],
  );
}
