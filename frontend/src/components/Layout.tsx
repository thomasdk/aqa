/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { AppearanceSelect } from "./AppearanceSelect";
import {
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import {
  type AppLocale,
  formatDateTime,
  formatNumber,
  localeTag,
  translateClientError,
} from "../i18n";
import AqaBrand from "./AqaBrand";
import AboutDialog from "./AboutDialog";
import IconButton from "./IconButton";
import { MaterialSymbol } from "./MaterialSymbol";
import NoticeBanner from "./NoticeBanner";
import BlockedActionHint from "./BlockedActionHint";
import DiscussionView from "./DiscussionView";
import ActivityPanel from "./ActivityPanel";
import {
  PerspectiveConfigurationControls,
  SynthesisConfigurationControls,
  hasValidProviderSelection,
} from "./DiscussionConfigurationControls";
import { ConfirmDialog, Modal } from "./Modal";
import {
  Button,
  ChoiceIndicator,
  DialogFooter,
  Input,
  PageHeader,
  Select,
  StepMarker,
  Textarea,
} from "./design-system";
import PromptPreview from "./PromptPreview";
import PromptConfigurationManager from "./PromptConfigurationManager";
import NetworkConfig, { type HostDraftDependencies } from "./NetworkConfig";
import LocalAI from "./LocalAI";
import RoleManager from "./RoleManager";
import ViewNavigation, { WORKBENCH_VIEWS, type WorkbenchView } from "./ViewNavigation";
import AIReadinessIndicator from "./AIReadinessIndicator";
import { isLocalAIUsable } from "./AIReadinessIndicator";
import {
  defaultSelectionForAISource,
  hasUsableExternalAI,
  integratedHosts,
  usesIntegratedAI,
  type AISource,
} from "./aiSourceSelection";
import {
  exportDiscussionUrl,
  getDiscussionExport,
  resetDiscussion,
  updateNextRoundConfiguration,
} from "../api";
import type { ContextEstimate } from "../api";
import {
  hasNativeMarkdownExport,
  saveMarkdownExport,
  subscribeNativeAboutOpen,
} from "../desktopBridge";
import { formatReleaseDate, releaseInfo } from "../releaseInfo";
import type { AgentConfig, Perspective, SessionInputDefinition } from "./types";
import SessionsTab from "./SessionsTab";
import { DISCUSSION_SPLIT_PANE_MIN_WIDTH } from "./discussionSplitPane";
import { type AgentHostSelection } from "./hostModelSelection";
import { isAgentActive } from "./discussionAgentRosterState";
import { useAppDocumentMetadata } from "./hooks/useAppDocumentMetadata";
import { useDiscussionMaterialPane } from "./hooks/useDiscussionMaterialPane";
import { useApplicationActivity } from "./hooks/useApplicationActivity";
import { useDiscussionStreaming } from "./hooks/useDiscussionStreaming";
import {
  useDiscussionMaterialPresentation,
  type DiscussionContextEstimateDraft,
} from "./hooks/useDiscussionMaterialPresentation";
import {
  persistPreferredTargetLanguage,
  type SessionHydrationController,
  useSessionHydration,
} from "./hooks/useSessionHydration";
import { useWorkbenchCatalogs } from "./hooks/useWorkbenchCatalogs";
import { sessionInputText } from "./sessionInputs";
import { getStartableLocalAIModelId } from "./localAIState";
import {
  selectPersistedLocale,
  selectPersistedPreventSleepWhileGenerating,
  selectPersistedRoundNotifications,
} from "../uiPreferences";
import {
  getRoundNotificationSnapshot,
  requestRoundNotificationPermission,
  subscribeRoundNotifications,
} from "../roundNotifications";
import {
  getGenerationSleepInhibitionSnapshot,
  subscribeGenerationSleepInhibition,
} from "../generationSleepInhibition";
import { buildDiscussionExportFilename } from "./exportFilename";
import { shouldPersistTitleEdit } from "./sessionTab";

const NUMBERED_MATERIAL_LINE = /^(Z\d{4,}):\s?(.*)$/;
const ACTIVE_VIEW_STORAGE_KEY = "aqa.activeView.v1";
const VIEW_LABEL_KEYS: Record<AppView, string> = {
  setup: "nav.setup",
  discussion: "nav.discussion",
  sessions: "nav.continue",
  network: "nav.network",
  "local-ai": "nav.localAi",
  roles: "nav.roles",
  preview: "nav.preview",
  system: "nav.system",
};

export function contextEstimateBlocksStart(estimate: ContextEstimate | null): boolean {
  return estimate?.known === true && estimate.overflow;
}

export function sessionInputErrorDescriptionId(
  error: string | null,
  errorInputKey: string | null,
  inputKey: string,
): string | undefined {
  return error && errorInputKey === inputKey ? "setup-session-input-error" : undefined;
}

/**
 * Render persisted citation units with a fixed number gutter.  The backend
 * owns segmentation and stable Z identifiers; this display layer lets each
 * unit wrap naturally without turning viewport-dependent visual rows into
 * new citations.  Blank source lines remain visible as paragraph spacing.
 */
export function renderNumberedMaterialLines(material: string): ReactNode {
  const lines = material.split("\n");
  const hasNumberedLine = lines.some((line) => NUMBERED_MATERIAL_LINE.test(line));
  if (!hasNumberedLine) return <span className="material-raw-text">{material}</span>;

  return lines.map((line, index) => {
    const match = NUMBERED_MATERIAL_LINE.exec(line);
    if (match) {
      return (
        <div className="material-numbered-line" key={`${match[1]}-${index}`}>
          <span className="material-line-number">{match[1]}</span>
          <span className="material-line-text">{match[2] || "\u00a0"}</span>
        </div>
      );
    }
    if (!line) {
      return <div className="material-paragraph-break" key={`blank-${index}`} aria-hidden="true" />;
    }
    return (
      <div
        className="material-numbered-line material-numbered-line--unlabelled"
        key={`raw-${index}`}
      >
        <span className="material-line-text">{line}</span>
      </div>
    );
  });
}

type AppView = WorkbenchView;

type InitialView = {
  view: AppView;
  wasRestored: boolean;
};

function readActiveView(): AppView | null {
  try {
    const stored = window.sessionStorage.getItem(ACTIVE_VIEW_STORAGE_KEY);
    return (WORKBENCH_VIEWS as readonly string[]).includes(stored ?? "")
      ? (stored as AppView)
      : null;
  } catch {
    return null;
  }
}

function persistActiveView(view: AppView): void {
  try {
    window.sessionStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, view);
  } catch {
    // The current segment remains usable when browser storage is unavailable.
  }
}

const MATERIAL_TYPES = [
  "interview",
  "focus_group",
  "document",
  "media",
  "fieldnotes",
  "memo",
  "other",
] as const;

const perspectiveDisplayName = (
  promptId: string | null,
  perspectives: readonly Perspective[],
): string | null => {
  const perspective = perspectives.find((item) => item.id === promptId);
  return perspective?.label ?? null;
};

/**
 * Apply a new source default only to slots that were still following the
 * previous source default. Any other host/model pair is an explicit user
 * override and must remain intact when Integrated AI prepares to start.
 */
export function preserveExplicitHostModelSelections<T extends AgentHostSelection>(
  selections: readonly T[],
  previousDefault: AgentHostSelection,
  nextDefault: AgentHostSelection,
  explicitIndexes: ReadonlySet<number> = new Set(),
): T[] {
  return selections.map((selection, index) => {
    const isUnset = selection.api_host === null && selection.llm_id === null;
    const followsPreviousDefault =
      selection.api_host === previousDefault.api_host &&
      selection.llm_id === previousDefault.llm_id;
    return !explicitIndexes.has(index) && (isUnset || followsPreviousDefault)
      ? { ...selection, ...nextDefault }
      : selection;
  });
}

export function isCurrentHostModelSelection(
  selection: AgentHostSelection,
  hosts: readonly {
    configuration_id: string;
    label: string;
    url: string;
    model: string;
    models: string[];
  }[],
): boolean {
  if (!selection.host_configuration_id || !selection.api_host || !selection.llm_id) return false;
  const normalizedUrl = selection.api_host.replace(/\/$/, "");
  const modelId = selection.llm_id;
  return hosts.some(
    (host) =>
      host.configuration_id === selection.host_configuration_id &&
      host.url.replace(/\/$/, "") === normalizedUrl &&
      (host.model === modelId || host.models.includes(modelId)),
  );
}

export function isSequentialModeAvailable(activePerspectiveCount: number): boolean {
  return activePerspectiveCount >= 2;
}

export function effectiveSequentialMode(
  sequentialMode: boolean,
  activePerspectiveCount: number,
): boolean {
  return isSequentialModeAvailable(activePerspectiveCount) && sequentialMode;
}

export function areRequiredSetupInputsValid(
  material: string,
  targetLanguage: string,
  requiredInputs: readonly SessionInputDefinition[],
  values: Readonly<Record<string, string>>,
): boolean {
  return (
    Boolean(material.trim()) &&
    Boolean(targetLanguage.trim()) &&
    requiredInputs.every((input) => Boolean(values[input.key]?.trim()))
  );
}

export type NewDiscussionDisposition = "start" | "confirm" | "wait-save" | "block-save-failed";

export function newDiscussionDisposition(args: {
  hasExistingDiscussion: boolean;
  isStreaming: boolean;
  isSavingTitle: boolean;
  titleSaveFailed: boolean;
  hasUnsavedTitle: boolean;
  hasUnsavedSetupDraft: boolean;
}): NewDiscussionDisposition {
  if (args.isSavingTitle) return "wait-save";
  if (args.titleSaveFailed) return "block-save-failed";
  if (
    args.hasExistingDiscussion ||
    args.isStreaming ||
    args.hasUnsavedTitle ||
    args.hasUnsavedSetupDraft
  ) {
    return "confirm";
  }
  return "start";
}

const Layout = () => {
  const { t, i18n } = useTranslation();
  const roundNotifications = useSyncExternalStore(
    subscribeRoundNotifications,
    getRoundNotificationSnapshot,
    getRoundNotificationSnapshot,
  );
  const generationSleepInhibition = useSyncExternalStore(
    subscribeGenerationSleepInhibition,
    getGenerationSleepInhibitionSnapshot,
    getGenerationSleepInhibitionSnapshot,
  );
  const appLocale: AppLocale = i18n.resolvedLanguage?.startsWith("en") ? "en" : "de";
  const initialViewRef = useRef<InitialView | null>(null);
  if (initialViewRef.current === null) {
    const restoredView = readActiveView();
    initialViewRef.current = {
      view: restoredView ?? "setup",
      wasRestored: restoredView !== null,
    };
  }
  const [view, setView] = useState<AppView>(() => initialViewRef.current!.view);
  const [aboutOpen, setAboutOpen] = useState(false);
  const aboutReturnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    persistActiveView(view);
  }, [view]);

  useEffect(() => subscribeNativeAboutOpen(() => setAboutOpen(true)), []);

  useEffect(() => {
    const rememberFocus = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement && !event.target.closest(".modal-overlay")) {
        aboutReturnFocusRef.current = event.target;
      }
    };
    document.addEventListener("focusin", rememberFocus);
    return () => document.removeEventListener("focusin", rememberFocus);
  }, []);

  useAppDocumentMetadata(i18n.resolvedLanguage, t);
  const [interpretationError, setInterpretationError] = useState<string | null>(null);
  const [interpretationErrorInputKey, setInterpretationErrorInputKey] = useState<string | null>(
    null,
  );
  const [setupDraftDirty, setSetupDraftDirty] = useState(false);
  const [openAgentOptions, setOpenAgentOptions] = useState<Record<string, boolean>>({});
  const [synthesisOptionsOpen, setSynthesisOptionsOpen] = useState(false);
  const [discussionCustomizationOpen, setDiscussionCustomizationOpen] = useState(false);
  const [researchMaterialContextOpen, setResearchMaterialContextOpen] = useState(false);
  const [optionalSessionInputsOpen, setOptionalSessionInputsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const hasDiscussionRef = useRef(false);
  const sessionRef = useRef<SessionHydrationController | null>(null);
  const streamingRef = useRef<ReturnType<typeof useDiscussionStreaming> | null>(null);
  const discussionTitleInputRef = useRef<HTMLInputElement | null>(null);
  const materialInputRef = useRef<HTMLTextAreaElement | null>(null);
  const setupHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const newDiscussionPendingRef = useRef(false);
  const focusSetupAfterModalRef = useRef(false);

  const navigateToDiscussion = useCallback(() => setView("discussion"), []);
  const navigateToSetup = useCallback(() => setView("setup"), []);

  const catalogs = useWorkbenchCatalogs({
    hasDiscussionRef,
    sessionRef,
    view,
  });
  const session = useSessionHydration({
    defaultHostSelection: catalogs.defaultHostSelection,
    onNavigateToDiscussion: navigateToDiscussion,
    onNavigateToSetup: navigateToSetup,
    perspectives: catalogs.perspectives,
    sessionTypes: catalogs.sessionTypes,
    setError,
    setInterpretationError,
    startupViewWasRestored: initialViewRef.current.wasRestored,
    streamingRef,
    t,
  });
  sessionRef.current = session;
  const {
    activeSessionFileId,
    lastActiveDiscussionId,
    activeSessionInputs,
    agents,
    currentSessionInputValues,
    defaultMaterial,
    defaultMaterialType,
    discussionTitle,
    discussionTitleDraft,
    discussionTitleSaveFailed,
    isEditingDiscussionTitle,
    isSavingDiscussionTitle,
    material,
    materialType,
    markTargetLanguageInvalid,
    optionalSessionInputs,
    requiredSessionInputs,
    researchMaterialContextInput,
    roundProviderProvenance,
    sequentialMode,
    sessionInputDrafts,
    sessionType,
    sessionsNotice,
    synthesis,
    targetLanguage,
    targetLanguageError,
    beginDiscussionTitleEdit,
    cancelDiscussionTitleEdit,
    clearTargetLanguageError,
    clearSessionsNotice,
    handleActiveSessionDeleted,
    openSavedSession,
    saveDiscussionTitle,
    selectMaterialType,
    selectSequentialMode,
    updateAgentConfiguration: updateAgentConfigurationFromSession,
    updateDiscussionTitleDraft,
    updateMaterial,
    updateSessionInputValue,
    updateSynthesisConfiguration: updateSynthesisConfigurationFromSession,
    updateTargetLanguage,
    validateStart,
  } = session;

  useEffect(() => {
    if (session.activeSessionFileId !== null) setSetupDraftDirty(false);
  }, [session.activeSessionFileId]);

  const materialPane = useDiscussionMaterialPane(view);

  useEffect(() => {
    if (isEditingDiscussionTitle) discussionTitleInputRef.current?.focus();
  }, [isEditingDiscussionTitle]);

  const sessionInputRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const targetLanguageRef = useRef<HTMLInputElement | null>(null);
  const {
    addDiscussionActivity: addActivity,
    clear: clearActivity,
    entries: activityLog,
    isOpen: isActivityOpen,
    logRef: activityLogRef,
    setIsOpen: setIsActivityOpen,
  } = useApplicationActivity();

  // Errors and success notices are rendered strings, not locale-neutral
  // codes. Clear transient copy when the product locale changes so a German
  // backend failure is never left visible inside the English UI (or vice
  // versa). The underlying user-entered configuration remains untouched.
  useEffect(() => {
    setError(null);
    setExportNotice(null);
    setInterpretationError(null);
    clearSessionsNotice();
  }, [clearSessionsNotice, i18n.resolvedLanguage]);

  const {
    aiSource,
    hosts,
    hostsLoaded,
    isStartingIntegratedAI,
    localAIStatus,
    localAIStatusFailed,
    perspectives,
    quickActions,
    roles,
    sessionTypes,
    prepareDiscussionStart: prepareDiscussionStartFromCatalog,
    refreshHosts,
    refreshPerspectives,
    refreshQuickActions,
    refreshSessionTypes,
    selectAISource: selectAISourceFromCatalog,
  } = catalogs;

  const explicitAgentHostModelOverridesRef = useRef<Set<string>>(new Set());
  const explicitSynthesisHostModelOverrideRef = useRef(false);
  useEffect(() => {
    explicitAgentHostModelOverridesRef.current = new Set();
    explicitSynthesisHostModelOverrideRef.current = false;
  }, [session.activeSessionFileId, session.isSnapshotAuthoritative]);

  const selectAISource = useCallback(
    (source: AISource) => {
      setSetupDraftDirty(true);
      const previousDefault = defaultSelectionForAISource(aiSource, hosts);
      const nextDefault = defaultSelectionForAISource(source, hosts);
      const currentAgents = session.agents;
      const currentSynthesis = session.synthesis;
      selectAISourceFromCatalog(source);
      if (session.isSnapshotAuthoritative) return;
      session.updateDraftAgents((previous) =>
        preserveExplicitHostModelSelections(
          currentAgents,
          previousDefault,
          nextDefault,
          new Set(
            currentAgents.flatMap((agent, index) =>
              explicitAgentHostModelOverridesRef.current.has(agent.client_id) ? [index] : [],
            ),
          ),
        ).map((selection, index) => ({ ...previous[index], ...selection })),
      );
      session.updateDraftSynthesis((previous) => ({
        ...previous,
        ...preserveExplicitHostModelSelections(
          [currentSynthesis],
          previousDefault,
          nextDefault,
          explicitSynthesisHostModelOverrideRef.current ? new Set([0]) : new Set(),
        )[0],
      }));
    },
    [aiSource, hosts, selectAISourceFromCatalog, session],
  );

  const prepareDiscussionStart = useCallback(
    async (draftAgents: AgentConfig[], draftSynthesis: typeof synthesis) => {
      const sourceDefault = defaultSelectionForAISource(aiSource, hosts);
      const integratedHostUrls = new Set(integratedHosts(hosts).map((host) => host.url));
      const isIntegratedSelection = (selection: AgentHostSelection): boolean =>
        selection.api_host !== null && integratedHostUrls.has(selection.api_host);
      const hasIntegratedWork = usesIntegratedAI(draftAgents, draftSynthesis, hosts);
      const explicitAgents = draftAgents.map((agent) => ({
        api_host: agent.api_host,
        llm_id: agent.llm_id,
      }));
      const explicitSynthesis = {
        api_host: draftSynthesis.api_host,
        llm_id: draftSynthesis.llm_id,
      };
      const prepared = await prepareDiscussionStartFromCatalog(draftAgents, draftSynthesis);
      if (!prepared) return prepared;
      const preserve = (selection: AgentHostSelection): boolean => {
        const isUnset = selection.api_host === null && selection.llm_id === null;
        const followsSourceDefault =
          selection.api_host === sourceDefault.api_host &&
          selection.llm_id === sourceDefault.llm_id;
        return !isUnset && !followsSourceDefault;
      };
      const shouldPreserve = (selection: AgentHostSelection, index: number): boolean =>
        hasIntegratedWork && isIntegratedSelection(selection)
          ? false
          : explicitAgentHostModelOverridesRef.current.has(draftAgents[index].client_id) ||
            session.isSnapshotAuthoritative ||
            preserve(selection);
      const preparedAgents = prepared.agents.map((agent, index) =>
        shouldPreserve(explicitAgents[index], index)
          ? { ...agent, ...explicitAgents[index] }
          : agent,
      );
      const preparedSynthesis =
        hasIntegratedWork && isIntegratedSelection(explicitSynthesis)
          ? prepared.synthesis
          : explicitSynthesisHostModelOverrideRef.current ||
              session.isSnapshotAuthoritative ||
              preserve(explicitSynthesis)
            ? { ...prepared.synthesis, ...explicitSynthesis }
            : prepared.synthesis;
      if (!session.isSnapshotAuthoritative) {
        session.updateDraftAgents(preparedAgents);
        session.updateDraftSynthesis(preparedSynthesis);
      }
      return {
        agents: preparedAgents,
        synthesis: preparedSynthesis,
      };
    },
    [aiSource, hosts, prepareDiscussionStartFromCatalog, session],
  );

  const updateAgentConfiguration = useCallback(
    (index: number, patch: Partial<AgentConfig>) => {
      setSetupDraftDirty(true);
      if (
        Object.prototype.hasOwnProperty.call(patch, "api_host") ||
        Object.prototype.hasOwnProperty.call(patch, "llm_id")
      ) {
        const clientId = session.agents[index]?.client_id;
        if (clientId) explicitAgentHostModelOverridesRef.current.add(clientId);
      }
      updateAgentConfigurationFromSession(index, patch);
    },
    [session.agents, updateAgentConfigurationFromSession],
  );

  const updateSynthesisConfiguration = useCallback(
    (patch: Partial<typeof synthesis>) => {
      setSetupDraftDirty(true);
      if (
        Object.prototype.hasOwnProperty.call(patch, "api_host") ||
        Object.prototype.hasOwnProperty.call(patch, "llm_id")
      ) {
        explicitSynthesisHostModelOverrideRef.current = true;
      }
      updateSynthesisConfigurationFromSession(patch);
    },
    [updateSynthesisConfigurationFromSession],
  );

  const getDraftHostDependencies = useCallback(
    (host: (typeof hosts)[number]): HostDraftDependencies => {
      const empty: HostDraftDependencies = {
        defaultAssignments: [],
        explicitAssignments: [],
        defaultSynthesis: false,
        explicitSynthesis: false,
      };
      if (session.isSnapshotAuthoritative) return empty;
      const normalizedHost = host.url.replace(/\/$/, "");
      const dependencies = agents.reduce<HostDraftDependencies>((result, agent, index) => {
        if (
          agent.host_configuration_id !== host.configuration_id ||
          (agent.api_host ?? "").replace(/\/$/, "") !== normalizedHost
        ) {
          return result;
        }
        const name =
          perspectiveDisplayName(agent.prompt_id, perspectives) ??
          t("setup.perspectiveSlot", { number: index + 1 });
        if (explicitAgentHostModelOverridesRef.current.has(agent.client_id)) {
          result.explicitAssignments.push(name);
        } else {
          result.defaultAssignments.push(name);
        }
        return result;
      }, empty);
      if (
        synthesis.host_configuration_id === host.configuration_id &&
        (synthesis.api_host ?? "").replace(/\/$/, "") === normalizedHost
      ) {
        if (explicitSynthesisHostModelOverrideRef.current) dependencies.explicitSynthesis = true;
        else dependencies.defaultSynthesis = true;
      }
      return dependencies;
    },
    [
      agents,
      perspectives,
      session.isSnapshotAuthoritative,
      synthesis.api_host,
      synthesis.host_configuration_id,
      t,
    ],
  );
  const hasModifiedSessionInput = (input: SessionInputDefinition | undefined) => {
    if (!input) return false;
    const savedValue = sessionInputDrafts[sessionType]?.[input.key];
    return savedValue !== undefined && savedValue !== sessionInputText(input.default_text);
  };
  const hasModifiedResearchMaterialContext = hasModifiedSessionInput(researchMaterialContextInput);
  const hasModifiedOptionalSessionInput = optionalSessionInputs.some(hasModifiedSessionInput);

  // A restored draft must not hide context the user already supplied. Once
  // optional content differs from its supplied template, keep its disclosure
  // visible so the initial view remains truthful.
  useEffect(() => {
    if (hasModifiedResearchMaterialContext) setResearchMaterialContextOpen(true);
  }, [hasModifiedResearchMaterialContext]);

  useEffect(() => {
    if (hasModifiedOptionalSessionInput) setOptionalSessionInputsOpen(true);
  }, [hasModifiedOptionalSessionInput]);

  const handleStreamingLocalAINotRunning = useCallback(() => setView("local-ai"), []);

  const discussionStreaming = useDiscussionStreaming({
    activeSessionFileId,
    addActivity,
    onDiscussionStarted: session.setDiscussionStarted,
    onLocalAINotRunning: handleStreamingLocalAINotRunning,
    setAgents: session.updateDiscussionAgents,
    setError,
    setSynthesis: session.updateDiscussionSynthesis,
    synthesis,
    t,
  });
  streamingRef.current = discussionStreaming;
  const {
    agentLifecycle,
    currentAgents,
    hasDiscussion,
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
    streamingAgents,
    streamingSynthesis,
  } = discussionStreaming;

  useEffect(() => {
    hasDiscussionRef.current = hasDiscussion;
  }, [hasDiscussion]);

  const selectView = useCallback(
    (next: AppView) => {
      // Startup restoration is advisory: any human navigation wins over an
      // in-flight list/open response.
      session.invalidatePendingRestore();
      setView(next);
    },
    [session],
  );

  const selectSessionType = session.selectSessionType;

  const contextEstimateDraft = useMemo<DiscussionContextEstimateDraft>(
    () => ({
      agents,
      synthesis,
      sessionType,
      targetLanguage,
      sessionInputValues: currentSessionInputValues,
      sequentialMode: effectiveSequentialMode(sequentialMode, agents.filter(isAgentActive).length),
    }),
    [agents, currentSessionInputValues, sequentialMode, sessionType, synthesis, targetLanguage],
  );
  const { contextEstimate, materialTokenEstimate, materialWithLineNumbers } =
    useDiscussionMaterialPresentation(
      material,
      materialType,
      hasDiscussion,
      contextEstimateDraft,
      JSON.stringify([localAIStatus?.state, localAIStatus?.context_tokens, hosts]),
    );

  const activePerspectiveNames = agents
    .filter(isAgentActive)
    .map((agent) => perspectiveDisplayName(agent.prompt_id, perspectives) ?? agent.name)
    .filter(Boolean);
  const activePerspectiveCount = agents.filter(isAgentActive).length;
  const sequentialModeAvailable = isSequentialModeAvailable(activePerspectiveCount);
  const effectiveSequentialModeValue = effectiveSequentialMode(
    sequentialMode,
    activePerspectiveCount,
  );
  const setupInputsValid = areRequiredSetupInputsValid(
    material,
    targetLanguage,
    requiredSessionInputs,
    currentSessionInputValues,
  );
  const materialMissing = !material.trim();
  const canResetMaterial =
    defaultMaterial !== null &&
    (material !== defaultMaterial ||
      (defaultMaterialType !== null && materialType !== defaultMaterialType));

  type AppModal =
    | null
    | {
        kind: "confirm";
        title: string;
        messages: string[];
        onConfirm: () => Promise<void>;
        confirmLabel?: string;
        destructive?: boolean;
      }
    | { kind: "alert"; message: string };

  const [modal, setModal] = useState<AppModal>(null);
  const [modalPending, setModalPending] = useState(false);
  const [modalConfirmError, setModalConfirmError] = useState<string | null>(null);

  useEffect(() => {
    if (modal !== null || !focusSetupAfterModalRef.current) return;
    focusSetupAfterModalRef.current = false;
    setupHeadingRef.current?.focus();
  }, [modal]);

  const handleStartDiscussion = useCallback(async () => {
    const focusTarget = validateStart();
    if (focusTarget?.kind === "material") {
      setInterpretationError(null);
      setView("setup");
      window.requestAnimationFrame(() => materialInputRef.current?.focus());
      return;
    }
    if (focusTarget?.kind === "target-language") {
      markTargetLanguageInvalid();
      setInterpretationErrorInputKey(null);
      setInterpretationError(t("setup.inputRequired", { label: t("setup.targetLanguage") }));
      setView("setup");
      window.requestAnimationFrame(() => targetLanguageRef.current?.focus());
      return;
    }
    if (focusTarget?.kind === "session-input") {
      clearTargetLanguageError();
      const missingInput = activeSessionInputs.find((input) => input.key === focusTarget.key);
      if (!missingInput) return;
      setInterpretationErrorInputKey(missingInput.key);
      setInterpretationError(
        t("setup.inputRequired", { label: sessionInputText(missingInput.label) }),
      );
      setView("setup");
      window.requestAnimationFrame(() => sessionInputRefs.current[missingInput.key]?.focus());
      return;
    }

    const normalizedTargetLanguage = targetLanguage.trim();
    clearTargetLanguageError();
    setInterpretationError(null);
    updateTargetLanguage(normalizedTargetLanguage);
    persistPreferredTargetLanguage(normalizedTargetLanguage);

    let preparedDiscussion: { agents: AgentConfig[]; synthesis: typeof synthesis } | null;
    try {
      preparedDiscussion = await prepareDiscussionStart(agents, synthesis);
    } catch (error) {
      setError(translateClientError(error, "localAi.startError"));
      return;
    }
    if (!preparedDiscussion) return;

    setView("discussion");
    void discussionStreaming
      .start({
        material,
        agents: preparedDiscussion.agents,
        title: "",
        material_context: {
          material_type: materialType,
          session_type: sessionType,
          target_language: normalizedTargetLanguage,
          input_values: currentSessionInputValues,
        },
        sequential_mode: effectiveSequentialMode(
          sequentialMode,
          agents.filter(isAgentActive).length,
        ),
        synthesis: preparedDiscussion.synthesis,
      })
      .then(async () => {
        try {
          await session.refreshProviderProvenance();
        } catch {
          setError(t("discussion.providerHistoryRefreshFailed"));
        }
      });
  }, [
    activeSessionInputs,
    agents,
    clearTargetLanguageError,
    currentSessionInputValues,
    discussionStreaming,
    material,
    materialType,
    markTargetLanguageInvalid,
    sequentialMode,
    session,
    sessionType,
    synthesis,
    t,
    targetLanguage,
    prepareDiscussionStart,
    updateTargetLanguage,
    validateStart,
  ]);

  const discussionUsesIntegratedAI = usesIntegratedAI(currentAgents, synthesis, hosts);
  const continuePendingRef = useRef(false);
  const [discussionFollowUp, setDiscussionFollowUp] = useState("");
  const [isRoundConfigurationSaving, setIsRoundConfigurationSaving] = useState(false);
  const [roundConfigurationOpenRequest, setRoundConfigurationOpenRequest] = useState(0);

  useEffect(() => {
    setDiscussionFollowUp("");
  }, [session.activeSessionFileId]);

  const performContinue = useCallback(
    async (
      userInput: string,
      focusSegment: string | null,
      targetMessageId: string | null,
      continuationAgents: AgentConfig[],
      continuationSynthesis: typeof synthesis,
    ) => {
      if (continuePendingRef.current) return false;
      continuePendingRef.current = true;
      try {
        const preparedDiscussion = await prepareDiscussionStart(
          continuationAgents,
          continuationSynthesis,
        );
        if (!preparedDiscussion) return false;
        await discussionStreaming.continueDiscussion(
          userInput,
          focusSegment,
          targetMessageId,
          effectiveSequentialMode(
            sequentialMode,
            preparedDiscussion.agents.filter(isAgentActive).length,
          ),
          preparedDiscussion.agents,
        );
        try {
          await session.refreshProviderProvenance();
        } catch {
          setError(t("discussion.providerHistoryRefreshFailed"));
        }
        return true;
      } catch (error) {
        setError(translateClientError(error, "localAi.startError"));
        if (usesIntegratedAI(continuationAgents, continuationSynthesis, hosts)) {
          setView("local-ai");
        }
        return false;
      } finally {
        continuePendingRef.current = false;
      }
    },
    [discussionStreaming, hosts, prepareDiscussionStart, sequentialMode, session, t],
  );

  const handleContinue = useCallback(
    async (userInput: string, focusSegment: string | null, targetMessageId: string | null) => {
      const missingPerspectiveProvider = currentAgents.some(
        (agent) =>
          isAgentActive(agent) &&
          (agent.api_host !== null || agent.llm_id !== null) &&
          !isCurrentHostModelSelection(agent, hosts),
      );
      const missingSynthesisProvider =
        synthesis.enabled &&
        (synthesis.api_host !== null || synthesis.llm_id !== null) &&
        !isCurrentHostModelSelection(synthesis, hosts);
      if (missingPerspectiveProvider || missingSynthesisProvider) {
        setRoundConfigurationOpenRequest((request) => request + 1);
        return false;
      }
      return performContinue(userInput, focusSegment, targetMessageId, currentAgents, synthesis);
    },
    [currentAgents, hosts, performContinue, synthesis],
  );

  const applyNextRoundConfiguration = useCallback(
    async (nextAgents: AgentConfig[], nextSynthesis: typeof synthesis) => {
      if (!activeSessionFileId || isStreaming) {
        return false;
      }
      setIsRoundConfigurationSaving(true);
      try {
        await updateNextRoundConfiguration({
          file_id: activeSessionFileId,
          agents: nextAgents.map((agent) => ({
            name: agent.name,
            client_id: agent.client_id,
            prompt_id: agent.prompt_id,
            color: agent.color,
            temperature: agent.temperature,
            llm_id: agent.llm_id,
            api_host: agent.api_host,
            host_configuration_id: agent.host_configuration_id ?? null,
            max_tokens: agent.max_tokens,
            enabled: agent.enabled,
            perspective_number: agent.perspective_number,
          })),
          synthesis: {
            enabled: nextSynthesis.enabled,
            api_host: nextSynthesis.api_host,
            llm_id: nextSynthesis.llm_id,
            host_configuration_id: nextSynthesis.host_configuration_id ?? null,
            temperature: nextSynthesis.temperature,
          },
        });
        discussionStreaming.acceptNextRoundConfiguration(nextAgents, nextSynthesis);
        return true;
      } catch (error) {
        setError(translateClientError(error, "errors.nextRoundConfigurationFailed"));
        return false;
      } finally {
        setIsRoundConfigurationSaving(false);
      }
    },
    [activeSessionFileId, discussionStreaming, isStreaming],
  );

  const handleStop = discussionStreaming.stop;
  const handleMoveAgent = discussionStreaming.moveAgent;
  const handleToggleAgent = discussionStreaming.toggleAgent;
  const handleToggleSynthesis = discussionStreaming.toggleSynthesis;
  const handleSetNote = discussionStreaming.setNote;
  const handleSetMessageContextInclusion = discussionStreaming.setMessageContextInclusion;

  const handleNew = useCallback(() => {
    const startNew = async () => {
      session.invalidatePendingRestore();
      await session.awaitPendingSessionOpen();
      await resetDiscussion();
      await session.startFreshDraft();
      setSetupDraftDirty(false);
    };

    const hasExistingDiscussion = Boolean(activeSessionFileId || hasDiscussion);
    const hasUnsavedTitle =
      isEditingDiscussionTitle && shouldPersistTitleEdit(discussionTitleDraft, discussionTitle);
    const disposition = newDiscussionDisposition({
      hasExistingDiscussion,
      isStreaming,
      isSavingTitle: isSavingDiscussionTitle,
      titleSaveFailed: discussionTitleSaveFailed,
      hasUnsavedTitle,
      hasUnsavedSetupDraft: setupDraftDirty,
    });
    if (disposition === "wait-save") {
      setModal({ kind: "alert", message: t("toolbar.newDiscussionSavePending") });
      return;
    }
    if (disposition === "block-save-failed") {
      setModal({ kind: "alert", message: t("toolbar.newDiscussionSaveFailed") });
      return;
    }
    if (disposition === "confirm") {
      const messages = [
        ...(isStreaming ? [t("toolbar.newDiscussionInterrupt")] : []),
        ...(hasExistingDiscussion ? [t("toolbar.newDiscussionSaved")] : []),
        ...(hasUnsavedTitle ? [t("toolbar.newDiscussionUnsavedTitle")] : []),
        ...(setupDraftDirty ? [t("toolbar.newDiscussionUnsavedSetup")] : []),
      ];
      setModalPending(false);
      setModalConfirmError(null);
      setModal({
        kind: "confirm",
        title: t("toolbar.newDiscussionConfirmTitle"),
        messages,
        onConfirm: startNew,
        confirmLabel: t("toolbar.newDiscussionConfirm"),
        destructive: isStreaming || hasUnsavedTitle || setupDraftDirty,
      });
      return;
    }
    void startNew()
      .then(() => window.setTimeout(() => setupHeadingRef.current?.focus(), 0))
      .catch((err: unknown) => {
        console.error("Reset failed:", err);
        setError(translateClientError(err, "errors.reset"));
      });
  }, [
    activeSessionFileId,
    discussionTitle,
    discussionTitleDraft,
    discussionTitleSaveFailed,
    hasDiscussion,
    isEditingDiscussionTitle,
    isSavingDiscussionTitle,
    isStreaming,
    session,
    setModalConfirmError,
    setModalPending,
    setModal,
    setupDraftDirty,
    t,
  ]);

  const handleExport = useCallback(async () => {
    setExportNotice(null);
    const filename = buildDiscussionExportFilename(discussionTitle, activeSessionFileId);
    if (hasNativeMarkdownExport()) {
      try {
        const markdown = await getDiscussionExport(appLocale, filename);
        const savedFilename = await saveMarkdownExport(filename, markdown);
        if (savedFilename) {
          setExportNotice(t("toolbar.exportSaved", { filename: savedFilename }));
        }
      } catch (err) {
        console.error("Export failed:", err);
        setError(translateClientError(err, "errors.export"));
      }
      return;
    }

    const a = document.createElement("a");
    a.href = exportDiscussionUrl(appLocale, filename);
    a.download = filename;
    // Start the attachment navigation in the original user gesture.  An
    // awaited Blob fetch may lose that activation before a synthetic click,
    // which browsers can then block as an unsolicited download.  An error is
    // opened in its own tab instead of silently leaving the app unchanged.
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }, [activeSessionFileId, appLocale, discussionTitle, t]);

  const localAIReady = isLocalAIUsable(localAIStatus);
  const externalAIReady = hasUsableExternalAI(hosts);
  const anyAIReady = localAIReady || externalAIReady;
  const aiReadinessChecked = hostsLoaded && (localAIStatus !== null || localAIStatusFailed);
  const selectedSourceReady = aiSource === "integrated" ? localAIReady : externalAIReady;
  const selectedIntegratedAIStartable =
    aiSource === "integrated" && getStartableLocalAIModelId(localAIStatus) !== null;
  const selectedSourceUsable = selectedSourceReady || selectedIntegratedAIStartable;
  const contextBudgetOverflow = contextEstimateBlocksStart(contextEstimate);
  const selectedModelsAvailable =
    agents.every(
      (agent) => !agent.enabled || hasValidProviderSelection(agent, hosts, localAIStatus),
    ) &&
    (!synthesis.enabled || hasValidProviderSelection(synthesis, hosts, localAIStatus));
  const startDisabled =
    isStreaming ||
    isStartingIntegratedAI ||
    !aiReadinessChecked ||
    !selectedSourceUsable ||
    activePerspectiveCount === 0 ||
    !setupInputsValid ||
    !selectedModelsAvailable ||
    contextBudgetOverflow;
  const startDisabledReason =
    isStreaming || isStartingIntegratedAI
      ? null
      : !setupInputsValid
        ? t("setup.startDisabledRequiredInputs")
        : !selectedModelsAvailable
          ? t("activity.modelUnavailableHelp")
          : contextBudgetOverflow
            ? t("setup.contextBudgetOverflow")
            : activePerspectiveCount === 0
              ? t("setup.startDisabledNoPerspective")
              : !selectedSourceUsable && anyAIReady
                ? t("setup.startDisabledSelectedAI")
                : null;

  const renderSessionInput = (input: SessionInputDefinition): ReactNode => {
    const inputId = `setup-input-${input.key}`;
    const hintId = `${inputId}-hint`;
    const defaultText = sessionInputText(input.default_text);
    const currentValue = currentSessionInputValues[input.key] ?? "";
    const canReset = currentValue !== defaultText;
    const requiredMissing = input.required && !currentValue.trim();
    const hint = sessionInputText(input.hint);
    const describedBy =
      [
        hint ? hintId : undefined,
        sessionInputErrorDescriptionId(interpretationError, interpretationErrorInputKey, input.key),
      ]
        .filter(Boolean)
        .join(" ") || undefined;
    return (
      <div className="setup-group" key={input.key}>
        <div className="setup-label-row">
          <label htmlFor={inputId}>
            {sessionInputText(input.label)}
            {input.required ? ` (${t("setup.required")})` : ""}
          </label>
          {canReset && (
            <IconButton
              className="icon-btn inline-btn"
              label={t("setup.resetToDefault", {
                label: sessionInputText(input.label),
              })}
              onClick={() => {
                setSetupDraftDirty(true);
                updateSessionInputValue(input.key, defaultText);
              }}
            >
              <MaterialSymbol name="refresh" decorative />
            </IconButton>
          )}
        </div>
        {hint && (
          <small id={hintId} className="ds-field__description">
            {hint}
          </small>
        )}
        <Textarea
          id={inputId}
          ref={(element) => {
            sessionInputRefs.current[input.key] = element;
          }}
          className={`setup-session-input${requiredMissing ? " setup-required-missing" : ""}`}
          value={currentValue}
          onChange={(event) => {
            setSetupDraftDirty(true);
            updateSessionInputValue(input.key, event.target.value);
          }}
          required={input.required}
          aria-required={input.required}
          aria-invalid={requiredMissing}
          aria-describedby={describedBy}
          rows={6}
        />
      </div>
    );
  };

  return (
    <div className="app-shell">
      <nav className="view-switcher" aria-label={t("app.navigation")}>
        <AqaBrand isGenerating={isStreaming} onActivate={() => selectView("setup")} />
        <div className="navigation-row">
          <ViewNavigation view={view} onNavigate={selectView} />
          <div className="toolbar-actions">
            {hasDiscussion && (
              <>
                <Button
                  variant="toolbar"
                  onClick={handleExport}
                  title={t("toolbar.exportMarkdown")}
                >
                  <MaterialSymbol name="file_download" decorative />
                  <span>{t("toolbar.export")}</span>
                </Button>
                <Button variant="toolbar" onClick={handleNew} title={t("toolbar.newDiscussion")}>
                  <MaterialSymbol name="add_comment" decorative />
                  <span>{t("toolbar.newDiscussion")}</span>
                </Button>
              </>
            )}
          </div>
        </div>
      </nav>

      <main className="app-main">
        <p className="visually-hidden" aria-live="polite" aria-atomic="true">
          {t(VIEW_LABEL_KEYS[view])}
        </p>
        {view !== "sessions" && sessionsNotice && (
          <NoticeBanner className="sessions-notice" tone="info" onDismiss={clearSessionsNotice}>
            {sessionsNotice}
          </NoticeBanner>
        )}
        {error && (
          <NoticeBanner className="error-banner" tone="error" onDismiss={() => setError(null)}>
            {error}
          </NoticeBanner>
        )}
        {exportNotice && (
          <NoticeBanner
            className="export-notice"
            tone="success"
            onDismiss={() => setExportNotice(null)}
          >
            {exportNotice}
          </NoticeBanner>
        )}

        {view === "setup" && (
          <>
            <header className="view-page-header">
              <h1 id="setup-page-title" ref={setupHeadingRef} tabIndex={-1}>
                {t("setup.title")}
              </h1>
            </header>
            {lastActiveDiscussionId &&
              !hasDiscussion &&
              !isStartingIntegratedAI &&
              !isStreaming &&
              !isStopInProgress && (
                <section className="resume-last-discussion" aria-labelledby="resume-last-title">
                  <MaterialSymbol name="history" decorative />
                  <div>
                    <h2 id="resume-last-title">{t("sessions.resumeLastTitle")}</h2>
                    <p>{t("sessions.resumeLastDescription")}</p>
                  </div>
                  <Button variant="secondary" onClick={() => selectView("sessions")}>
                    {t("sessions.resumeLast")}
                  </Button>
                </section>
              )}
            <AIReadinessIndicator
              hosts={hosts}
              source={aiSource}
              localStatus={localAIStatus}
              localStatusFailed={localAIStatusFailed}
              readinessChecked={aiReadinessChecked}
              onSourceChange={selectAISource}
              onNavigate={selectView}
            />
            <div className="prepare-flow">
              <section className="prepare-step" aria-labelledby="setup-purpose-title">
                <header className="prepare-step-header">
                  <StepMarker className="prepare-step-number">1</StepMarker>
                  <div>
                    <h2 id="setup-purpose-title">{t("setup.chooseSessionType")}</h2>
                    <p>{t("setup.chooseSessionTypeHelp")}</p>
                  </div>
                </header>
                <fieldset className="session-type-gallery">
                  <legend className="visually-hidden">{t("setup.sessionType")}</legend>
                  {sessionTypes.map((type) => {
                    const selected = type.key === sessionType;
                    return (
                      <label
                        key={type.key}
                        className={`session-type-card${selected ? " is-selected" : ""}`}
                      >
                        <input
                          className="choice-radio-input"
                          type="radio"
                          name="session-type"
                          value={type.key}
                          checked={selected}
                          onChange={() => {
                            setSetupDraftDirty(true);
                            selectSessionType(type.key);
                          }}
                        />
                        <ChoiceIndicator className="session-type-card-marker" selected={selected} />
                        <span>
                          <strong>{type.label}</strong>
                          {type.description && <small>{type.description}</small>}
                        </span>
                      </label>
                    );
                  })}
                </fieldset>
              </section>

              <section className="prepare-step" aria-labelledby="setup-material-title">
                <header className="prepare-step-header">
                  <StepMarker className="prepare-step-number">2</StepMarker>
                  <div className="prepare-step-header-copy">
                    <h2 id="setup-material-title">{t("setup.addMaterial")}</h2>
                    <p>{t("setup.addMaterialDescription")}</p>
                  </div>
                  {researchMaterialContextInput && (
                    <button
                      type="button"
                      className="agent-config-options-toggle"
                      aria-expanded={researchMaterialContextOpen}
                      aria-controls="setup-research-material-context"
                      onClick={() => setResearchMaterialContextOpen((open) => !open)}
                    >
                      <MaterialSymbol name="tune" decorative />
                      {t("setup.options")}
                    </button>
                  )}
                </header>

                <div className="setup-group">
                  <div className="setup-label-row">
                    <label htmlFor="setup-material-input">
                      {t("setup.material")} ({t("setup.required")})
                    </label>
                    {canResetMaterial && (
                      <IconButton
                        className="icon-btn inline-btn"
                        label={t("setup.resetToDefault", { label: t("setup.material") })}
                        onClick={() => {
                          setSetupDraftDirty(true);
                          updateMaterial(defaultMaterial ?? "");
                          if (defaultMaterialType) selectMaterialType(defaultMaterialType);
                        }}
                      >
                        <MaterialSymbol name="refresh" decorative />
                      </IconButton>
                    )}
                  </div>
                  <small className="setup-material-example-note">
                    {t("setup.materialExample")}
                  </small>
                  <Textarea
                    id="setup-material-input"
                    ref={materialInputRef}
                    className={`setup-material-input${materialMissing ? " setup-required-missing" : ""}`}
                    value={material}
                    onChange={(e) => {
                      setSetupDraftDirty(true);
                      updateMaterial(e.target.value);
                    }}
                    placeholder={t("setup.materialPlaceholder")}
                    rows={12}
                    required
                    aria-required="true"
                    aria-invalid={materialMissing}
                    aria-describedby="setup-material-guidance"
                  />
                  <small className="setup-token-estimate">
                    {materialTokenEstimate === null
                      ? t("setup.materialTokenEstimateUnavailable")
                      : t("setup.materialTokenEstimate", {
                          count: formatNumber(materialTokenEstimate),
                        })}
                  </small>
                  <NoticeBanner
                    id="setup-material-guidance"
                    className="setup-material-guidance"
                    tone={contextBudgetOverflow ? "error" : "info"}
                    role="note"
                  >
                    <span className="setup-material-guidance__content">
                      <span id="setup-context-budget">
                        {contextBudgetOverflow
                          ? t("setup.contextBudgetOverflow")
                          : t("setup.integratedMaterialDurationGuidance")}
                      </span>
                    </span>
                  </NoticeBanner>
                </div>

                <div className="setup-row">
                  <div className="setup-group">
                    <label htmlFor="setup-material-type">{t("setup.materialType")}</label>
                    <Select
                      id="setup-material-type"
                      value={materialType}
                      onChange={(e) => {
                        setSetupDraftDirty(true);
                        selectMaterialType(e.target.value);
                      }}
                    >
                      {MATERIAL_TYPES.map((value) => (
                        <option key={value} value={value}>
                          {t(`setup.materialTypes.${value}`)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="setup-group">
                    <label htmlFor="setup-target-language">
                      {t("setup.targetLanguage")} ({t("setup.required")})
                    </label>
                    <Input
                      id="setup-target-language"
                      ref={targetLanguageRef}
                      type="text"
                      value={targetLanguage}
                      onChange={(event) => {
                        setSetupDraftDirty(true);
                        updateTargetLanguage(event.target.value);
                      }}
                      placeholder={t("setup.targetLanguagePlaceholder")}
                      required
                      aria-required="true"
                      className={!targetLanguage.trim() ? "setup-required-missing" : undefined}
                      aria-invalid={!targetLanguage.trim()}
                      aria-describedby={
                        targetLanguageError ? "setup-session-input-error" : undefined
                      }
                    />
                  </div>
                </div>

                {researchMaterialContextOpen && researchMaterialContextInput && (
                  <div
                    id="setup-research-material-context"
                    className="prepare-optional-inputs-content"
                  >
                    {renderSessionInput(researchMaterialContextInput)}
                  </div>
                )}
              </section>

              <section className="prepare-step" aria-labelledby="setup-task-title">
                <header className="prepare-step-header">
                  <StepMarker className="prepare-step-number">3</StepMarker>
                  <div className="prepare-step-header-copy">
                    <h2 id="setup-task-title">{t("setup.describeTask")}</h2>
                  </div>
                  {optionalSessionInputs.length > 0 && (
                    <button
                      type="button"
                      className="agent-config-options-toggle"
                      aria-expanded={optionalSessionInputsOpen}
                      aria-controls="setup-optional-inputs"
                      onClick={() => setOptionalSessionInputsOpen((open) => !open)}
                    >
                      <MaterialSymbol name="tune" decorative />
                      {t("setup.options")}
                    </button>
                  )}
                </header>
                {requiredSessionInputs.map(renderSessionInput)}
                {optionalSessionInputs.length > 0 && (
                  <div className="prepare-optional-inputs">
                    {optionalSessionInputsOpen && (
                      <div id="setup-optional-inputs" className="prepare-optional-inputs-content">
                        {optionalSessionInputs.map(renderSessionInput)}
                      </div>
                    )}
                  </div>
                )}
                {interpretationError && (
                  <small id="setup-session-input-error" className="setup-field-error" role="alert">
                    {interpretationError}
                  </small>
                )}
              </section>

              <section className="prepare-step" aria-labelledby="setup-discussion-title">
                <header className="prepare-step-header">
                  <StepMarker className="prepare-step-number">4</StepMarker>
                  <div>
                    <h2 id="setup-discussion-title">{t("setup.readyToDiscuss")}</h2>
                  </div>
                </header>
                <div className="discussion-configuration-summary">
                  <div>
                    <p className="discussion-configuration-perspectives">
                      {activePerspectiveNames.length > 0
                        ? activePerspectiveNames.join(" · ")
                        : t("setup.noPerspective")}
                    </p>
                    <p className="discussion-configuration-facts">
                      {effectiveSequentialModeValue
                        ? t("setup.sequential")
                        : t("setup.independent")}
                      {" · "}
                      {synthesis.enabled
                        ? t("setup.synthesisActive")
                        : t("setup.synthesisInactive")}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="agent-config-options-toggle"
                    aria-expanded={discussionCustomizationOpen}
                    aria-controls="setup-discussion-customization"
                    onClick={() => setDiscussionCustomizationOpen((open) => !open)}
                  >
                    <MaterialSymbol name="tune" decorative />
                    {t("setup.options")}
                  </button>
                </div>

                {discussionCustomizationOpen && (
                  <div id="setup-discussion-customization" className="discussion-customization">
                    <h3>{t("setup.agents")}</h3>

                    {agents.map((agent, idx) => {
                      const slotKey = agent.client_id || String(idx);
                      return (
                        <PerspectiveConfigurationControls
                          key={slotKey}
                          agent={agent}
                          index={idx}
                          perspectives={perspectives}
                          roles={roles}
                          hosts={hosts}
                          localStatus={localAIStatus}
                          expanded={openAgentOptions[slotKey] === true}
                          fallbackToFirstHost
                          idPrefix="setup"
                          onToggleExpanded={() =>
                            setOpenAgentOptions((previous) => ({
                              ...previous,
                              [slotKey]: !previous[slotKey],
                            }))
                          }
                          onChange={(patch) => updateAgentConfiguration(idx, patch)}
                        />
                      );
                    })}

                    <SynthesisConfigurationControls
                      synthesis={synthesis}
                      hosts={hosts}
                      localStatus={localAIStatus}
                      expanded={synthesisOptionsOpen}
                      fallbackToFirstHost
                      idPrefix="setup"
                      onToggleExpanded={() => setSynthesisOptionsOpen((open) => !open)}
                      onChange={updateSynthesisConfiguration}
                    />

                    <fieldset className="setup-mode-toggle discussion-mode-config">
                      <legend>{t("setup.answerMode")}</legend>
                      <label className="setup-mode-option">
                        <input
                          className="choice-radio-input"
                          type="radio"
                          name="discussion-mode"
                          value="sequential"
                          checked={effectiveSequentialModeValue}
                          disabled={!sequentialModeAvailable}
                          aria-describedby="setup-sequential-help"
                          onChange={() => {
                            setSetupDraftDirty(true);
                            selectSequentialMode(true);
                          }}
                        />
                        <ChoiceIndicator
                          className="setup-mode-option-marker"
                          selected={effectiveSequentialModeValue}
                        />
                        <span>{t("setup.sequential")}</span>
                      </label>
                      <label className="setup-mode-option">
                        <input
                          className="choice-radio-input"
                          type="radio"
                          name="discussion-mode"
                          value="independent"
                          checked={!effectiveSequentialModeValue}
                          onChange={() => {
                            setSetupDraftDirty(true);
                            selectSequentialMode(false);
                          }}
                        />
                        <ChoiceIndicator
                          className="setup-mode-option-marker"
                          selected={!effectiveSequentialModeValue}
                        />
                        <span>{t("setup.independent")}</span>
                      </label>
                      <p id="setup-sequential-help" className="setup-help-text">
                        {sequentialModeAvailable
                          ? t("setup.sequentialHelp")
                          : t("setup.sequentialUnavailable")}
                      </p>
                    </fieldset>
                  </div>
                )}
              </section>

              <section
                className="prepare-step prepare-step--start"
                aria-labelledby="setup-start-title"
              >
                <div className="prepare-start-area">
                  <header className="prepare-step-header">
                    <StepMarker className="prepare-step-number">5</StepMarker>
                    <div>
                      <h2 id="setup-start-title">{t("discussion.start")}</h2>
                    </div>
                  </header>
                  <div className="prepare-start-action">
                    <Button
                      variant="primary"
                      disabled={startDisabled}
                      aria-describedby={
                        startDisabledReason ? "setup-start-disabled-reason" : undefined
                      }
                      onClick={handleStartDiscussion}
                    >
                      {isStartingIntegratedAI
                        ? t("localAi.starting")
                        : isStreaming
                          ? t("setup.running")
                          : t("discussion.start")}
                    </Button>
                    {startDisabledReason && (
                      <BlockedActionHint id="setup-start-disabled-reason" role="status">
                        {startDisabledReason}
                      </BlockedActionHint>
                    )}
                  </div>
                </div>
              </section>
            </div>
          </>
        )}

        {view === "discussion" && (
          <section className="discussion-shell" aria-labelledby="discussion-page-title">
            <PageHeader
              className="view-page-header"
              titleId="discussion-page-title"
              title={t("discussion.title")}
            />
            {hasDiscussion && (
              <header className="discussion-title-bar">
                {isEditingDiscussionTitle ? (
                  <form
                    className="discussion-title-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void saveDiscussionTitle();
                    }}
                  >
                    <Input
                      ref={discussionTitleInputRef}
                      className="discussion-title-input"
                      value={discussionTitleDraft}
                      onChange={(event) => updateDiscussionTitleDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          event.preventDefault();
                          cancelDiscussionTitleEdit();
                        }
                      }}
                      aria-label={t("discussion.editTitle")}
                      maxLength={200}
                      disabled={isSavingDiscussionTitle}
                    />
                    <Button type="submit" variant="secondary" disabled={isSavingDiscussionTitle}>
                      {isSavingDiscussionTitle ? t("common.saving") : t("common.save")}
                    </Button>
                    <Button variant="secondary" onClick={cancelDiscussionTitleEdit}>
                      {t("common.cancel")}
                    </Button>
                  </form>
                ) : (
                  <button
                    type="button"
                    className="discussion-title-button"
                    onClick={() => beginDiscussionTitleEdit(isStreaming)}
                    disabled={!activeSessionFileId || isStreaming || isSavingDiscussionTitle}
                    title={t("discussion.editTitle")}
                    aria-label={`${t("discussion.editTitle")}: ${discussionTitle || t("discussion.title")}`}
                  >
                    <span className="discussion-title-text">{discussionTitle || "Diskussion"}</span>
                    <MaterialSymbol name="edit" decorative className="discussion-title-edit-icon" />
                  </button>
                )}
              </header>
            )}
            <div
              ref={materialPane.layoutRef}
              className={`discussion-layout${materialPane.isCollapsed ? " is-material-collapsed" : ""}${materialPane.isDesktop ? "" : " is-mobile-stack"}`}
              style={materialPane.style}
            >
              {material &&
                (materialPane.isCollapsed ? (
                  <aside
                    className="material-panel material-rail"
                    aria-label={t("discussion.expandMaterial")}
                  >
                    <button
                      type="button"
                      className="material-rail-toggle"
                      onClick={materialPane.toggle}
                      title={t("discussion.expandMaterial")}
                      aria-label={t("discussion.expandMaterial")}
                      aria-expanded="false"
                      aria-controls="material-pane-content"
                    >
                      <span className="material-rail-toggle-label">{t("setup.material")}</span>
                    </button>
                  </aside>
                ) : (
                  <section className="material-panel" aria-label={t("discussion.material")}>
                    <div className="material-panel-header">
                      <div className="material-panel-heading">
                        <span className="material-panel-title">{t("setup.material")}</span>
                        <span className="material-token-estimate">
                          {materialTokenEstimate === null
                            ? t("setup.materialTokenEstimateUnavailable")
                            : `~${formatNumber(materialTokenEstimate)} ${t("prompts.tokens")}`}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="material-collapse-btn"
                        onClick={materialPane.toggle}
                        title={t("discussion.collapseMaterial")}
                        aria-label={t("discussion.collapseMaterial")}
                        aria-expanded="true"
                        aria-controls="material-pane-content"
                      >
                        «
                      </button>
                    </div>
                    <div
                      id="material-pane-content"
                      className="material-content material-numbered-content"
                    >
                      {renderNumberedMaterialLines(materialWithLineNumbers || material)}
                    </div>
                  </section>
                ))}

              {material && materialPane.isDesktop && !materialPane.isCollapsed && (
                // An adjustable ARIA separator is interactive by definition; the lint
                // rule does not account for this widget role.
                // eslint-disable-next-line jsx-a11y-x/no-noninteractive-element-interactions
                <div
                  ref={materialPane.separatorRef}
                  role="separator"
                  tabIndex={0}
                  aria-label={t("discussion.resizeMaterial")}
                  aria-orientation="vertical"
                  aria-valuemin={DISCUSSION_SPLIT_PANE_MIN_WIDTH}
                  aria-valuemax={materialPane.maxWidth}
                  aria-valuenow={materialPane.width}
                  className="material-separator"
                  onPointerDown={materialPane.onPointerDown}
                  onPointerMove={materialPane.onPointerMove}
                  onPointerUp={materialPane.releasePointer}
                  onPointerCancel={materialPane.releasePointer}
                  onLostPointerCapture={materialPane.releasePointer}
                  onKeyDown={materialPane.onKeyDown}
                  onDoubleClick={materialPane.onDoubleClick}
                />
              )}

              <div className="discussion-workspace">
                <ActivityPanel
                  isStreaming={isStreaming}
                  usesIntegratedAI={discussionUsesIntegratedAI}
                  currentAgents={currentAgents}
                  perspectives={perspectives}
                  roles={roles}
                  hosts={hosts}
                  localStatus={localAIStatus}
                  agentLifecycle={agentLifecycle}
                  messages={messages}
                  roundStatus={roundStatus}
                  roundElapsedSeconds={roundElapsedSeconds}
                  roundStartedAt={roundStartedAt}
                  streamingSynthesis={streamingSynthesis}
                  latestContextUsage={latestContextUsage}
                  onStop={isStreaming ? handleStop : undefined}
                  isStopInProgress={isStopInProgress}
                  onMoveAgent={handleMoveAgent}
                  onToggleAgent={handleToggleAgent}
                  isRosterSaving={isSavingAgentRoster}
                  synthesis={synthesis}
                  onToggleSynthesis={handleToggleSynthesis}
                  isSynthesisSaving={isSavingSynthesis}
                  onApplyNextRoundConfiguration={applyNextRoundConfiguration}
                  isRoundConfigurationSaving={isRoundConfigurationSaving}
                  configurationOpenRequest={roundConfigurationOpenRequest}
                  roundProviderProvenance={roundProviderProvenance}
                />

                <DiscussionView
                  messages={messages}
                  streamingAgents={streamingAgents}
                  streamingSynthesis={streamingSynthesis}
                  currentAgents={currentAgents}
                  usesIntegratedAI={discussionUsesIntegratedAI}
                  independentAnswers={
                    hasDiscussion &&
                    !effectiveSequentialMode(
                      sequentialMode,
                      currentAgents.filter(isAgentActive).length,
                    )
                  }
                  quickActions={quickActions}
                  isStreaming={isStreaming}
                  isSynthesisSaving={isSavingSynthesis}
                  isContinuePending={isStartingIntegratedAI}
                  followUpDraft={discussionFollowUp}
                  onFollowUpDraftChange={setDiscussionFollowUp}
                  onContinue={handleContinue}
                  onSetNote={handleSetNote}
                  onSetContextInclusion={handleSetMessageContextInclusion}
                  isContextInclusionSaving={isContextInclusionSaving}
                />
              </div>
            </div>
          </section>
        )}

        {view === "network" && (
          <NetworkConfig
            onHostsChanged={refreshHosts}
            getDraftDependencies={getDraftHostDependencies}
          />
        )}

        {view === "local-ai" && (
          <LocalAI onHostsChanged={refreshHosts} onStatusChanged={catalogs.acceptLocalAIStatus} />
        )}

        {view === "roles" && <RoleManager onRolesChanged={refreshPerspectives} />}

        {view === "preview" && <PromptPreview />}

        {view === "sessions" && (
          <SessionsTab
            activeFileId={activeSessionFileId}
            onOpen={openSavedSession}
            onActiveSessionDeleted={handleActiveSessionDeleted}
            onMutationStart={clearSessionsNotice}
            externalNotice={sessionsNotice}
            onNoticeDismiss={clearSessionsNotice}
          />
        )}

        {view === "system" && (
          <section className="system-page" aria-labelledby="system-page-title">
            <PageHeader
              className="system-page-header"
              titleId="system-page-title"
              title={t("system.title")}
              subtitle={t("system.intro")}
            />
            <section className="system-language" aria-labelledby="system-appearance-title">
              <div className="system-language-header">
                <div>
                  <h2 id="system-appearance-title">{t("system.appearanceTitle")}</h2>
                  <p>{t("system.appearanceIntro")}</p>
                </div>
                <AppearanceSelect />
              </div>
            </section>
            <section className="system-language" aria-labelledby="system-language-title">
              <div className="system-language-header">
                <div>
                  <h2 id="system-language-title">{t("system.languageTitle")}</h2>
                  <p>{t("system.languageIntro")}</p>
                </div>
                <label className="locale-switcher">
                  <span className="visually-hidden">{t("app.language")}</span>
                  <Select
                    value={
                      (i18n.resolvedLanguage?.startsWith("en") ? "en" : "de") satisfies AppLocale
                    }
                    onChange={(event) =>
                      void selectPersistedLocale(event.target.value as AppLocale)
                    }
                    aria-label={t("app.language")}
                  >
                    <option value="de">{t("app.german")}</option>
                    <option value="en">{t("app.english")}</option>
                  </Select>
                </label>
              </div>
            </section>
            <section
              className="system-language system-release-information"
              aria-labelledby="system-release-title"
            >
              <div className="system-language-header">
                <div>
                  <h2 id="system-release-title">{t("release.systemTitle")}</h2>
                  <p>{t("release.systemIntro")}</p>
                </div>
                <Button
                  className="system-release-actions"
                  variant="secondary"
                  onClick={() => setAboutOpen(true)}
                >
                  {t("about.open")}
                </Button>
              </div>
              <dl className="system-release-list">
                <div>
                  <dt>{t("release.versionLabel")}</dt>
                  <dd>{releaseInfo.version}</dd>
                </div>
                <div>
                  <dt>{t("release.dateLabel")}</dt>
                  <dd>
                    {releaseInfo.releaseDate
                      ? formatReleaseDate(releaseInfo.releaseDate, localeTag(i18n.resolvedLanguage))
                      : t("release.dateUnassigned")}
                  </dd>
                </div>
                <div>
                  <dt>{t("release.statusLabel")}</dt>
                  <dd>{t(`release.status.${releaseInfo.releaseStatus}`)}</dd>
                </div>
                <div>
                  <dt>{t("release.githubLabel")}</dt>
                  <dd>
                    {releaseInfo.links.githubRepository ? (
                      <a
                        href={releaseInfo.links.githubRepository}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t("release.openGithub")}
                      </a>
                    ) : (
                      <>
                        <span className="release-link-unavailable" aria-disabled="true">
                          {t("release.unavailable")}
                        </span>
                        <span className="release-link-explanation">
                          {t("release.githubUnavailable")}
                        </span>
                      </>
                    )}
                  </dd>
                </div>
              </dl>
            </section>
            <section
              className="system-language system-notifications"
              aria-labelledby="system-notifications-title"
            >
              <div className="system-language-header">
                <div>
                  <h2 id="system-notifications-title">{t("system.notificationsTitle")}</h2>
                  <p>{t("system.notificationsIntro")}</p>
                  {roundNotifications.enabled && roundNotifications.permission === "granted" && (
                    <p className="system-notification-status">{t("system.notificationsGranted")}</p>
                  )}
                  {roundNotifications.enabled && roundNotifications.permission === "default" && (
                    <p className="system-notification-status">
                      {t("system.notificationsNeedsPermission")}
                    </p>
                  )}
                  {roundNotifications.enabled && roundNotifications.permission === "denied" && (
                    <p className="system-notification-status is-error">
                      {t("system.notificationsBlocked")}
                    </p>
                  )}
                  {roundNotifications.enabled &&
                    roundNotifications.permission === "unsupported" && (
                      <p className="system-notification-status">
                        {t("system.notificationsUnsupported")}
                      </p>
                    )}
                  {roundNotifications.enabled &&
                    roundNotifications.permission === "unavailable" && (
                      <p
                        className="system-notification-status is-error"
                        role={roundNotifications.permissionRequestAttempted ? "status" : undefined}
                      >
                        {t("system.notificationsUnavailable")}
                      </p>
                    )}
                </div>
                <div className="system-notification-controls">
                  <label
                    className="checkbox"
                    htmlFor="system-round-notifications"
                    data-round-notification-control
                  >
                    <input
                      id="system-round-notifications"
                      type="checkbox"
                      checked={roundNotifications.enabled}
                      onChange={(event) => selectPersistedRoundNotifications(event.target.checked)}
                    />
                    <span>{t("system.notificationsToggle")}</span>
                  </label>
                  {roundNotifications.enabled &&
                    (roundNotifications.permission === "default" ||
                      roundNotifications.permission === "unavailable") && (
                      <Button
                        variant="secondary"
                        onClick={() => void requestRoundNotificationPermission()}
                      >
                        {t(
                          roundNotifications.permission === "unavailable"
                            ? "system.notificationsRetry"
                            : "system.notificationsAllow",
                        )}
                      </Button>
                    )}
                </div>
              </div>
            </section>
            <section
              className="system-language system-notifications"
              aria-labelledby="system-sleep-inhibition-title"
            >
              <div className="system-language-header">
                <div>
                  <h2 id="system-sleep-inhibition-title">{t("system.sleepInhibitionTitle")}</h2>
                  <p>{t("system.sleepInhibitionIntro")}</p>
                </div>
                <div className="system-notification-controls">
                  <label className="checkbox" htmlFor="system-prevent-sleep-while-generating">
                    <input
                      id="system-prevent-sleep-while-generating"
                      type="checkbox"
                      checked={generationSleepInhibition.enabled}
                      onChange={(event) =>
                        selectPersistedPreventSleepWhileGenerating(event.target.checked)
                      }
                    />
                    <span>{t("system.sleepInhibitionToggle")}</span>
                  </label>
                </div>
              </div>
            </section>
            <PromptConfigurationManager
              onConfigurationChanged={refreshSessionTypes}
              onQuickActionsChanged={refreshQuickActions}
            />
          </section>
        )}
      </main>

      {aboutOpen && (
        <AboutDialog onClose={() => setAboutOpen(false)} returnFocusRef={aboutReturnFocusRef} />
      )}

      {modal?.kind === "alert" && (
        <Modal label={t("common.error")} onClose={() => setModal(null)}>
          <p className="modal-message">{modal.message}</p>
          <DialogFooter>
            <Button variant="primary" onClick={() => setModal(null)}>
              {t("common.ok")}
            </Button>
          </DialogFooter>
        </Modal>
      )}
      {modal?.kind === "confirm" && (
        <ConfirmDialog
          title={modal.title}
          message={
            <>
              {modal.messages.map((message) => (
                <p key={message}>{message}</p>
              ))}
              {modalConfirmError && (
                <p className="setup-field-error" role="alert">
                  {modalConfirmError}
                </p>
              )}
            </>
          }
          cancelLabel={t("common.cancel")}
          confirmLabel={modal.confirmLabel ?? t("common.ok")}
          variant={modal.destructive ? "destructive" : "default"}
          disabled={modalPending}
          onCancel={() => {
            setModalConfirmError(null);
            setModal(null);
          }}
          onConfirm={() => {
            if (newDiscussionPendingRef.current) return;
            newDiscussionPendingRef.current = true;
            setModalPending(true);
            setModalConfirmError(null);
            void modal
              .onConfirm()
              .then(() => {
                focusSetupAfterModalRef.current = true;
                setModal(null);
              })
              .catch((err: unknown) => {
                console.error("Reset failed:", err);
                const message = translateClientError(err, "errors.reset");
                setError(message);
                setModalConfirmError(message);
              })
              .finally(() => {
                newDiscussionPendingRef.current = false;
                setModalPending(false);
              });
          }}
        />
      )}
      <div className="activity-log-panel">
        <div className="activity-log-header">
          <button
            type="button"
            className="activity-log-toggle"
            onClick={() => setIsActivityOpen(!isActivityOpen)}
            aria-expanded={isActivityOpen}
            aria-controls="activity-log-content"
          >
            <span className="activity-log-header-label">
              <MaterialSymbol name="memory" decorative className="activity-log-header-icon" />
              <span>{t("activityLog.title", { count: activityLog.length })}</span>
            </span>
          </button>
          <button
            type="button"
            className="activity-log-clear-btn"
            onClick={clearActivity}
            title={t("activityLog.clear")}
            aria-label={t("activityLog.clear")}
          >
            {t("activityLog.clear")}
          </button>
        </div>
        {isActivityOpen && (
          // A populated activity log has a bounded scroll area and needs a keyboard scroll target.
          // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
          <div
            id="activity-log-content"
            className="activity-log"
            ref={activityLogRef}
            role="region"
            aria-label={t("activityLog.title", { count: activityLog.length })}
            tabIndex={0}
          >
            {activityLog.length === 0 && (
              <div className="activity-log-empty">{t("activityLog.empty")}</div>
            )}
            {activityLog.map((entry) => (
              <div
                key={entry.id}
                className={`activity-log-line activity-log-${entry.source} activity-log-${entry.level}`}
              >
                <span className="activity-log-line-source">
                  {t(
                    entry.source === "server"
                      ? "activityLog.sourceServer"
                      : "activityLog.sourceDiscussion",
                  )}
                  {` · ${t(`activityLog.level.${entry.level}`)}`}
                </span>
                <time className="activity-log-line-time" dateTime={entry.timestamp}>
                  {formatDateTime(new Date(entry.timestamp), {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </time>
                {entry.message}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Layout;
