import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { TFunction } from "i18next";
import {
  ApiError,
  getDefaultAgents,
  getDefaultMaterial,
  getDiscussionProviderProvenance,
  listSessions,
  openSession as apiOpenSession,
  renameSession,
  updateApplicationPreferences,
  type SessionMessage,
  type SessionSnapshot,
} from "../../api";
import { translateClientError } from "../../i18n";
import { sessionInputText } from "../sessionInputs";
import { normalizeSessionTitleInput, shouldPersistTitleEdit } from "../sessionTab";
import {
  clearLastActiveDiscussionId,
  persistLastActiveDiscussionId,
  readLastActiveDiscussionId,
} from "../lastActiveDiscussion";
import type {
  AgentConfig,
  DiscussionMessage,
  Perspective,
  RoundProviderProvenance,
  SessionInputDefinition,
  SessionType,
  SynthesisConfig,
} from "../types";
import type { DiscussionStreamingController } from "./useDiscussionStreaming";

const TARGET_LANGUAGE_STORAGE_KEY = "aqa.targetLanguage.v1";

function readPreferredTargetLanguage(): string {
  try {
    return window.localStorage.getItem(TARGET_LANGUAGE_STORAGE_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function persistPreferredTargetLanguage(language: string): void {
  try {
    window.localStorage.setItem(TARGET_LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Browser storage is a convenience, never a prerequisite for a discussion.
  }
}

const AGENT_COLORS = ["#2563eb", "#16a34a", "#dc2626"];

const createClientId = () =>
  crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

export const DEFAULT_SYNTHESIS: SynthesisConfig = {
  enabled: true,
  api_host: null,
  host_configuration_id: null,
  host_label: null,
  llm_id: null,
  temperature: null,
};

export function createDefaultAgents(): AgentConfig[] {
  return AGENT_COLORS.map((color, index) => ({
    name: `Perspective ${index + 1}`,
    client_id: createClientId(),
    prompt_id: null,
    color,
    temperature: null,
    llm_id: null,
    api_host: null,
    host_configuration_id: null,
    host_label: null,
    api_key: null,
    max_tokens: null,
    enabled: false,
    perspective_number: index + 1,
  }));
}

export type SetupFocusTarget =
  | { kind: "material" }
  | { kind: "target-language" }
  | { kind: "session-input"; key: string }
  | null;

export type SessionHydrationController = {
  readonly activeSessionFileId: string | null;
  readonly lastActiveDiscussionId: string | null;
  readonly activeSessionInputs: SessionInputDefinition[];
  readonly agents: AgentConfig[];
  readonly currentSessionInputValues: Record<string, string>;
  readonly defaultMaterial: string | null;
  readonly defaultMaterialType: string | null;
  readonly discussionTitle: string;
  readonly discussionTitleDraft: string;
  readonly discussionTitleSaveFailed: boolean;
  readonly isEditingDiscussionTitle: boolean;
  readonly isSavingDiscussionTitle: boolean;
  readonly isSnapshotAuthoritative: boolean;
  readonly material: string;
  readonly materialType: string;
  readonly optionalSessionInputs: SessionInputDefinition[];
  readonly requiredSessionInputs: SessionInputDefinition[];
  readonly researchMaterialContextInput: SessionInputDefinition | undefined;
  readonly roundProviderProvenance: RoundProviderProvenance[];
  readonly sequentialMode: boolean;
  readonly sessionType: string;
  readonly sessionInputDrafts: Record<string, Record<string, string>>;
  readonly sessionInputSnapshots: Record<string, SessionInputDefinition[]>;
  readonly sessionsNotice: string | null;
  readonly synthesis: SynthesisConfig;
  readonly targetLanguage: string;
  readonly targetLanguageError: boolean;
  beginDiscussionTitleEdit: (isStreaming: boolean) => void;
  cancelDiscussionTitleEdit: () => void;
  clearSessionsNotice: () => void;
  clearTargetLanguageError: () => void;
  handleActiveSessionDeleted: (
    wasOpen: boolean,
    deletedFileIds?: readonly string[],
  ) => Promise<void>;
  invalidatePendingRestore: () => void;
  awaitPendingSessionOpen: () => Promise<void>;
  markTargetLanguageInvalid: () => void;
  openSavedSession: (fileId: string) => Promise<void>;
  refreshProviderProvenance: () => Promise<void>;
  saveDiscussionTitle: () => Promise<void>;
  selectSessionType: (sessionType: string) => void;
  selectMaterialType: (materialType: string) => void;
  selectSequentialMode: (sequentialMode: boolean) => void;
  setDiscussionStarted: (fileId: string | null, title: string) => void;
  startFreshDraft: () => Promise<void>;
  updateAgentConfiguration: (index: number, patch: Partial<AgentConfig>) => void;
  updateDiscussionAgents: Dispatch<SetStateAction<AgentConfig[]>>;
  updateDiscussionSynthesis: Dispatch<SetStateAction<SynthesisConfig>>;
  updateDiscussionTitleDraft: (title: string) => void;
  updateDraftAgents: (next: SetStateAction<AgentConfig[]>) => void;
  updateDraftSynthesis: (next: SetStateAction<SynthesisConfig>) => void;
  updateMaterial: (material: string) => void;
  updateSessionInputValue: (key: string, value: string) => void;
  updateSynthesisConfiguration: (patch: Partial<SynthesisConfig>) => void;
  updateTargetLanguage: (language: string) => void;
  validateStart: () => SetupFocusTarget;
};

type UseSessionHydrationOptions = {
  defaultHostSelection: () => Pick<SynthesisConfig, "api_host" | "llm_id">;
  onNavigateToDiscussion: () => void;
  onNavigateToSetup: () => void;
  perspectives: readonly Perspective[];
  sessionTypes: readonly SessionType[];
  setError: Dispatch<SetStateAction<string | null>>;
  setInterpretationError: Dispatch<SetStateAction<string | null>>;
  startupViewWasRestored: boolean;
  streamingRef: MutableRefObject<DiscussionStreamingController | null>;
  t: TFunction;
};

function hydrateMessages(snapshotMessages: readonly SessionMessage[]): DiscussionMessage[] {
  return snapshotMessages.map((message) => {
    if (message.role === "agent") {
      return { ...message, theory_label: message.theory_label ?? null };
    }
    return {
      ...message,
      agent_name: null,
      theory_label: null,
      color: null,
      agent_index: null,
      perspective_number: null,
      client_id: null,
    };
  });
}

/** Owns the saved-session boundary and the setup draft that precedes it. */
export function useSessionHydration({
  defaultHostSelection,
  onNavigateToDiscussion,
  onNavigateToSetup,
  perspectives,
  sessionTypes,
  setError,
  setInterpretationError,
  startupViewWasRestored,
  streamingRef,
  t,
}: UseSessionHydrationOptions): SessionHydrationController {
  const [activeSessionFileId, setActiveSessionFileId] = useState<string | null>(null);
  const [lastActiveDiscussionId, setLastActiveDiscussionId] = useState<string | null>(null);
  const [discussionTitle, setDiscussionTitle] = useState("");
  const [isEditingDiscussionTitle, setIsEditingDiscussionTitle] = useState(false);
  const [discussionTitleDraft, setDiscussionTitleDraft] = useState("");
  const [isSavingDiscussionTitle, setIsSavingDiscussionTitle] = useState(false);
  const [discussionTitleSaveFailed, setDiscussionTitleSaveFailed] = useState(false);
  const [sessionsNotice, setSessionsNotice] = useState<string | null>(null);
  const [material, setMaterial] = useState("");
  const [defaultMaterial, setDefaultMaterial] = useState<string | null>(null);
  const [defaultMaterialType, setDefaultMaterialType] = useState<string | null>(null);
  const [materialType, setMaterialType] = useState("document");
  const [sessionType, setSessionType] = useState("exploration");
  const [targetLanguage, setTargetLanguage] = useState(readPreferredTargetLanguage);
  const [targetLanguageError, setTargetLanguageError] = useState(false);
  const [sessionInputDrafts, setSessionInputDrafts] = useState<
    Record<string, Record<string, string>>
  >({});
  const [sessionInputSnapshots, setSessionInputSnapshots] = useState<
    Record<string, SessionInputDefinition[]>
  >({});
  const [sequentialMode, setSequentialMode] = useState(true);
  const [agents, setAgents] = useState<AgentConfig[]>(createDefaultAgents);
  const [synthesis, setSynthesis] = useState<SynthesisConfig>(DEFAULT_SYNTHESIS);
  const [roundProviderProvenance, setRoundProviderProvenance] = useState<RoundProviderProvenance[]>(
    [],
  );
  const [isSnapshotAuthoritative, setIsSnapshotAuthoritative] = useState(false);

  const activeSessionFileIdRef = useRef<string | null>(null);
  const pendingSessionOpenRef = useRef<Promise<void>>(Promise.resolve());
  const provenanceEpochRef = useRef(0);
  const restoreEpochRef = useRef(0);
  const startupRestoreAttemptedRef = useRef(false);
  const snapshotAuthoritativeRef = useRef(false);
  const sessionTypeRef = useRef(sessionType);
  const perspectivesRef = useRef(perspectives);

  useEffect(() => {
    sessionTypeRef.current = sessionType;
  }, [sessionType]);
  useEffect(() => {
    perspectivesRef.current = perspectives;
  }, [perspectives]);

  const selectedSessionTypeDefinition = useMemo(
    () => sessionTypes.find((item) => item.key === sessionType),
    [sessionTypes, sessionType],
  );
  const activeSessionInputs = useMemo(
    () => sessionInputSnapshots[sessionType] ?? selectedSessionTypeDefinition?.inputs ?? [],
    [selectedSessionTypeDefinition, sessionInputSnapshots, sessionType],
  );
  const requiredSessionInputs = activeSessionInputs.filter((input) => input.required);
  const researchMaterialContextInput = activeSessionInputs.find(
    (input) => input.key === "research_material_context",
  );
  const optionalSessionInputs = activeSessionInputs.filter(
    (input) => !input.required && input.key !== "research_material_context",
  );
  const currentSessionInputValues = useMemo(() => {
    const draft = sessionInputDrafts[sessionType] ?? {};
    return Object.fromEntries(
      activeSessionInputs.map((input) => [
        input.key,
        draft[input.key] ?? sessionInputText(input.default_text),
      ]),
    );
  }, [activeSessionInputs, sessionInputDrafts, sessionType]);

  const invalidatePendingRestore = useCallback(() => {
    restoreEpochRef.current += 1;
  }, []);

  const awaitPendingSessionOpen = useCallback(() => pendingSessionOpenRef.current, []);

  const updateSessionInputValue = useCallback(
    (key: string, value: string) => {
      setSessionInputDrafts((previous) => ({
        ...previous,
        [sessionType]: { ...currentSessionInputValues, ...previous[sessionType], [key]: value },
      }));
      setInterpretationError(null);
    },
    [currentSessionInputValues, sessionType, setInterpretationError],
  );

  const updateMaterial = useCallback((nextMaterial: string) => {
    setMaterial(nextMaterial);
  }, []);

  const selectMaterialType = useCallback((nextMaterialType: string) => {
    setMaterialType(nextMaterialType);
  }, []);

  const updateTargetLanguage = useCallback((language: string) => {
    setTargetLanguage(language);
    setTargetLanguageError(false);
  }, []);

  const markTargetLanguageInvalid = useCallback(() => setTargetLanguageError(true), []);
  const clearTargetLanguageError = useCallback(() => setTargetLanguageError(false), []);

  const selectSequentialMode = useCallback((nextSequentialMode: boolean) => {
    setSequentialMode(nextSequentialMode);
  }, []);

  const updateDiscussionTitleDraft = useCallback((title: string) => {
    setDiscussionTitleDraft(title);
    setDiscussionTitleSaveFailed(false);
  }, []);

  const selectSessionType = useCallback(
    (nextSessionType: string) => {
      if (snapshotAuthoritativeRef.current || nextSessionType === sessionTypeRef.current) return;
      const definition = sessionTypes.find((item) => item.key === nextSessionType);
      if (!definition) return;

      // Invalidate the previous async defaults request before switching the
      // key so a late response cannot create a hybrid draft.
      restoreEpochRef.current += 1;
      sessionTypeRef.current = nextSessionType;
      setSessionType(nextSessionType);
      setSessionInputSnapshots((previous) => {
        if (!(nextSessionType in previous)) return previous;
        const next = { ...previous };
        delete next[nextSessionType];
        return next;
      });
      setSessionInputDrafts((previous) => {
        const previousValues = previous[nextSessionType] ?? {};
        return {
          ...previous,
          [nextSessionType]: Object.fromEntries(
            definition.inputs.map((input) => [
              input.key,
              previousValues[input.key] ?? sessionInputText(input.default_text),
            ]),
          ),
        };
      });
      setAgents((previous) =>
        previous.map((agent, index) => ({
          ...agent,
          name: `Perspective ${index + 1}`,
          prompt_id: null,
          enabled: false,
        })),
      );
      setInterpretationError(null);
    },
    [sessionTypes, setInterpretationError],
  );

  const updateDraftAgents = useCallback((next: SetStateAction<AgentConfig[]>) => {
    if (snapshotAuthoritativeRef.current) return;
    setAgents(next);
  }, []);

  const updateDraftSynthesis = useCallback((next: SetStateAction<SynthesisConfig>) => {
    if (snapshotAuthoritativeRef.current) return;
    setSynthesis(next);
  }, []);

  const updateDiscussionAgents = useCallback((next: SetStateAction<AgentConfig[]>) => {
    setAgents(next);
  }, []);

  const updateDiscussionSynthesis = useCallback((next: SetStateAction<SynthesisConfig>) => {
    setSynthesis(next);
  }, []);

  const updateAgentConfiguration = useCallback((index: number, patch: Partial<AgentConfig>) => {
    setAgents((previous) =>
      previous.map((agent, currentIndex) =>
        currentIndex === index ? { ...agent, ...patch } : agent,
      ),
    );
  }, []);

  const updateSynthesisConfiguration = useCallback((patch: Partial<SynthesisConfig>) => {
    setSynthesis((previous) => ({ ...previous, ...patch }));
  }, []);

  const setDiscussionStarted = useCallback((fileId: string | null, title: string) => {
    if (activeSessionFileIdRef.current !== fileId) {
      provenanceEpochRef.current += 1;
      setRoundProviderProvenance([]);
    }
    activeSessionFileIdRef.current = fileId;
    setActiveSessionFileId(fileId);
    if (fileId) {
      persistLastActiveDiscussionId(fileId);
      setLastActiveDiscussionId(fileId);
    }
    setDiscussionTitle(title);
    setIsEditingDiscussionTitle(false);
  }, []);

  const cancelDiscussionTitleEdit = useCallback(() => {
    setDiscussionTitleDraft("");
    setIsEditingDiscussionTitle(false);
    setDiscussionTitleSaveFailed(false);
  }, []);

  const beginDiscussionTitleEdit = useCallback(
    (isStreaming: boolean) => {
      if (!activeSessionFileId || !discussionTitle || isStreaming || isSavingDiscussionTitle)
        return;
      setDiscussionTitleDraft(discussionTitle);
      setIsEditingDiscussionTitle(true);
      setDiscussionTitleSaveFailed(false);
    },
    [activeSessionFileId, discussionTitle, isSavingDiscussionTitle],
  );

  const saveDiscussionTitle = useCallback(async () => {
    if (!activeSessionFileId) {
      cancelDiscussionTitleEdit();
      return;
    }
    if (!shouldPersistTitleEdit(discussionTitleDraft, discussionTitle)) {
      cancelDiscussionTitleEdit();
      return;
    }
    const normalizedDraft = normalizeSessionTitleInput(discussionTitleDraft);
    if (normalizedDraft === null) {
      cancelDiscussionTitleEdit();
      return;
    }
    setIsSavingDiscussionTitle(true);
    setDiscussionTitleSaveFailed(false);
    try {
      const updated = await renameSession(activeSessionFileId, normalizedDraft);
      setDiscussionTitle(updated.title);
      cancelDiscussionTitleEdit();
    } catch (error) {
      setDiscussionTitleSaveFailed(true);
      setError(translateClientError(error, "errors.titleSave"));
    } finally {
      setIsSavingDiscussionTitle(false);
    }
  }, [
    activeSessionFileId,
    cancelDiscussionTitleEdit,
    discussionTitle,
    discussionTitleDraft,
    setError,
  ]);

  const applySessionSnapshot = useCallback(
    (snapshot: SessionSnapshot) => {
      provenanceEpochRef.current += 1;
      snapshotAuthoritativeRef.current = true;
      setIsSnapshotAuthoritative(true);
      streamingRef.current?.invalidate();

      setMaterial(snapshot.material);
      const context = snapshot.material_context;
      setMaterialType(context.material_type);
      setTargetLanguage(context.target_language);
      setTargetLanguageError(false);
      sessionTypeRef.current = context.session_type;
      setSessionType(context.session_type);
      setSessionInputDrafts({ [context.session_type]: context.input_values });
      setSessionInputSnapshots({ [context.session_type]: context.input_definitions });
      const rehydratedAgents = snapshot.agents.map((agent): AgentConfig => ({
        name: agent.name,
        client_id: agent.client_id,
        prompt_id: agent.prompt_id ?? null,
        color: agent.color,
        temperature: agent.temperature ?? null,
        llm_id: agent.llm_id ?? null,
        api_host: agent.api_host ?? null,
        host_configuration_id: agent.host_configuration_id ?? null,
        host_label: agent.host_label ?? null,
        api_key: null,
        max_tokens: agent.max_tokens ?? null,
        enabled: agent.enabled,
        perspective_number: agent.perspective_number,
      }));
      setAgents(rehydratedAgents);
      setSynthesis(snapshot.synthesis);
      streamingRef.current?.hydrateSnapshot({
        activeSessionFileId: snapshot.file_id,
        agents: rehydratedAgents,
        hasDiscussion: snapshot.has_active_discussion,
        roundStatus: snapshot.round_status ?? null,
        messages: hydrateMessages(snapshot.messages),
      });
      setSequentialMode(snapshot.sequential_mode);
      setDiscussionStarted(snapshot.file_id, snapshot.title);
      setRoundProviderProvenance(snapshot.round_provider_provenance);
    },
    [setDiscussionStarted, streamingRef],
  );

  const openAndHydrate = useCallback(
    async (
      fileId: string,
      mayApply: () => boolean = () => true,
    ): Promise<SessionSnapshot | null> => {
      const pending = pendingSessionOpenRef.current.then(async () => {
        if (!mayApply()) return null;
        const snapshot = await apiOpenSession(fileId);
        if (!mayApply()) return null;
        applySessionSnapshot(snapshot);
        return snapshot;
      });
      pendingSessionOpenRef.current = pending.then(
        () => undefined,
        () => undefined,
      );
      return pending;
    },
    [applySessionSnapshot],
  );

  const openSavedSession = useCallback(
    async (fileId: string) => {
      invalidatePendingRestore();
      const epoch = restoreEpochRef.current;
      try {
        const snapshot = await openAndHydrate(fileId, () => restoreEpochRef.current === epoch);
        if (!snapshot) return;
        persistLastActiveDiscussionId(snapshot.file_id);
        setLastActiveDiscussionId(snapshot.file_id);
        setSessionsNotice(t("sessions.openedTitle", { title: snapshot.title }));
        onNavigateToDiscussion();
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.status === 404 &&
          readLastActiveDiscussionId() === fileId
        ) {
          clearLastActiveDiscussionId();
          setLastActiveDiscussionId(null);
        }
        setError(translateClientError(error, "errors.sessionOpen"));
        throw error;
      }
    },
    [invalidatePendingRestore, onNavigateToDiscussion, openAndHydrate, setError, t],
  );

  const refreshProviderProvenance = useCallback(async () => {
    const fileId = activeSessionFileIdRef.current;
    if (!fileId) return;
    const epoch = ++provenanceEpochRef.current;
    try {
      const provenance = await getDiscussionProviderProvenance();
      if (activeSessionFileIdRef.current === fileId && provenanceEpochRef.current === epoch) {
        setRoundProviderProvenance(provenance);
      }
    } catch (error) {
      if (activeSessionFileIdRef.current === fileId && provenanceEpochRef.current === epoch) {
        throw error;
      }
    }
  }, []);

  const startFreshDraft = useCallback(async () => {
    provenanceEpochRef.current += 1;
    streamingRef.current?.clear();
    const epoch = ++restoreEpochRef.current;
    snapshotAuthoritativeRef.current = false;
    setIsSnapshotAuthoritative(false);
    setDiscussionStarted(null, "");
    setMaterial("");
    setMaterialType("document");
    setTargetLanguage(readPreferredTargetLanguage());
    setTargetLanguageError(false);
    setSessionInputDrafts({});
    setSessionInputSnapshots({});
    setSequentialMode(true);
    setRoundProviderProvenance([]);
    const preferredHost = defaultHostSelection();
    setSynthesis({ ...DEFAULT_SYNTHESIS, ...preferredHost });
    setAgents(createDefaultAgents().map((agent) => ({ ...agent, ...preferredHost })));
    onNavigateToSetup();

    const selectedType = sessionTypeRef.current;
    try {
      const [nextMaterial, defaultRoles] = await Promise.all([
        getDefaultMaterial(),
        getDefaultAgents(selectedType),
      ]);
      setDefaultMaterial(nextMaterial.material);
      setDefaultMaterialType(nextMaterial.material_type || "document");
      if (restoreEpochRef.current !== epoch || snapshotAuthoritativeRef.current) return;
      const validRoles = new Set(perspectivesRef.current.map((role) => role.id));
      setMaterial(nextMaterial.material);
      setMaterialType(nextMaterial.material_type || "document");
      setAgents(
        createDefaultAgents().map((agent, index) => {
          const promptId = defaultRoles[index] ?? null;
          const validPromptId = promptId && validRoles.has(promptId) ? promptId : null;
          const name = perspectivesRef.current.find((role) => role.id === validPromptId)?.label;
          return {
            ...agent,
            ...preferredHost,
            prompt_id: validPromptId,
            enabled: Boolean(validPromptId),
            ...(name ? { name } : {}),
          };
        }),
      );
    } catch (error) {
      if (restoreEpochRef.current === epoch) {
        setError(translateClientError(error, "errors.defaultsLoad"));
      }
    }
  }, [defaultHostSelection, onNavigateToSetup, setDiscussionStarted, setError, streamingRef]);

  const handleActiveSessionDeleted = useCallback(
    async (wasOpen: boolean, deletedFileIds: readonly string[] = []) => {
      if (
        lastActiveDiscussionId !== null &&
        (deletedFileIds.length === 0 || deletedFileIds.includes(lastActiveDiscussionId))
      ) {
        clearLastActiveDiscussionId();
        setLastActiveDiscussionId(null);
      }
      if (!wasOpen) return;
      await startFreshDraft();
      setSessionsNotice(t("sessions.openDeleted"));
    },
    [lastActiveDiscussionId, startFreshDraft, t],
  );

  const validateStart = useCallback((): SetupFocusTarget => {
    if (!material.trim()) return { kind: "material" };
    if (!targetLanguage.trim()) return { kind: "target-language" };
    const missingInput = activeSessionInputs.find(
      (input) => input.required && !currentSessionInputValues[input.key]?.trim(),
    );
    return missingInput ? { kind: "session-input", key: missingInput.key } : null;
  }, [activeSessionInputs, currentSessionInputValues, material, targetLanguage]);

  const clearSessionsNotice = useCallback(() => setSessionsNotice(null), []);

  useEffect(() => {
    let cancelled = false;
    const epoch = restoreEpochRef.current;
    void getDefaultMaterial()
      .then((defaults) => {
        if (cancelled) return;
        setDefaultMaterial(defaults.material);
        setDefaultMaterialType(defaults.material_type || "document");
        if (restoreEpochRef.current !== epoch || snapshotAuthoritativeRef.current) return;
        setMaterial((previous) => previous || defaults.material);
        if (defaults.material_type) setMaterialType(defaults.material_type);
      })
      .catch((error: unknown) => {
        if (!cancelled) console.error("Failed to load default material:", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const epoch = restoreEpochRef.current;
    void getDefaultAgents(sessionType)
      .then((defaults) => {
        if (cancelled || restoreEpochRef.current !== epoch || snapshotAuthoritativeRef.current)
          return;
        setAgents((previous) =>
          previous.map((agent, index) => {
            const promptId = defaults[index] ?? null;
            const name = perspectivesRef.current.find((role) => role.id === promptId)?.label;
            return {
              ...agent,
              enabled: Boolean(promptId),
              prompt_id: promptId,
              ...(name ? { name } : {}),
            };
          }),
        );
      })
      .catch((error: unknown) => {
        if (!cancelled) console.error("Failed to load default agents:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionType]);

  useEffect(() => {
    if (startupRestoreAttemptedRef.current) return;
    startupRestoreAttemptedRef.current = true;
    let cancelled = false;
    const attemptEpoch = restoreEpochRef.current;
    void (async () => {
      try {
        const sessions = await listSessions();
        const storedId = readLastActiveDiscussionId();
        if (!storedId) {
          clearLastActiveDiscussionId();
        } else {
          const target = sessions.find((session) => session.file_id === storedId);
          if (!target) {
            clearLastActiveDiscussionId();
            void updateApplicationPreferences({ last_active_discussion_id: null }).catch(
              () => undefined,
            );
            if (!cancelled) setLastActiveDiscussionId(null);
          } else if (!cancelled && restoreEpochRef.current === attemptEpoch) {
            void updateApplicationPreferences({ last_active_discussion_id: target.file_id }).catch(
              () => undefined,
            );
            setLastActiveDiscussionId(target.file_id);
          }
        }
        const open = sessions.find((session) => session.is_open);
        if (!open || cancelled || restoreEpochRef.current !== attemptEpoch) return;
        const snapshot = await openAndHydrate(
          open.file_id,
          () => !cancelled && restoreEpochRef.current === attemptEpoch,
        );
        if (!snapshot || cancelled || restoreEpochRef.current !== attemptEpoch) return;
        if (!startupViewWasRestored) onNavigateToDiscussion();
      } catch (error) {
        if (!cancelled) setError(translateClientError(error, "errors.sessionOpen"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onNavigateToDiscussion, openAndHydrate, setError, startupViewWasRestored]);

  return useMemo(
    () => ({
      activeSessionFileId,
      lastActiveDiscussionId,
      activeSessionInputs,
      agents,
      beginDiscussionTitleEdit,
      cancelDiscussionTitleEdit,
      clearSessionsNotice,
      clearTargetLanguageError,
      currentSessionInputValues,
      defaultMaterial,
      defaultMaterialType,
      discussionTitle,
      discussionTitleDraft,
      discussionTitleSaveFailed,
      handleActiveSessionDeleted,
      invalidatePendingRestore,
      awaitPendingSessionOpen,
      isEditingDiscussionTitle,
      isSavingDiscussionTitle,
      isSnapshotAuthoritative,
      material,
      materialType,
      markTargetLanguageInvalid,
      openSavedSession,
      refreshProviderProvenance,
      optionalSessionInputs,
      requiredSessionInputs,
      researchMaterialContextInput,
      roundProviderProvenance,
      saveDiscussionTitle,
      selectMaterialType,
      selectSequentialMode,
      selectSessionType,
      sequentialMode,
      sessionInputDrafts,
      sessionInputSnapshots,
      sessionType,
      sessionsNotice,
      setDiscussionStarted,
      startFreshDraft,
      synthesis,
      targetLanguage,
      targetLanguageError,
      updateAgentConfiguration,
      updateDiscussionAgents,
      updateDiscussionSynthesis,
      updateDiscussionTitleDraft,
      updateSessionInputValue,
      updateDraftAgents,
      updateDraftSynthesis,
      updateMaterial,
      updateSynthesisConfiguration,
      updateTargetLanguage,
      validateStart,
    }),
    [
      activeSessionFileId,
      lastActiveDiscussionId,
      activeSessionInputs,
      agents,
      beginDiscussionTitleEdit,
      cancelDiscussionTitleEdit,
      clearSessionsNotice,
      clearTargetLanguageError,
      currentSessionInputValues,
      defaultMaterial,
      defaultMaterialType,
      discussionTitle,
      discussionTitleDraft,
      discussionTitleSaveFailed,
      handleActiveSessionDeleted,
      invalidatePendingRestore,
      awaitPendingSessionOpen,
      isEditingDiscussionTitle,
      isSavingDiscussionTitle,
      isSnapshotAuthoritative,
      material,
      materialType,
      markTargetLanguageInvalid,
      openSavedSession,
      refreshProviderProvenance,
      optionalSessionInputs,
      requiredSessionInputs,
      researchMaterialContextInput,
      roundProviderProvenance,
      saveDiscussionTitle,
      selectMaterialType,
      selectSequentialMode,
      selectSessionType,
      sequentialMode,
      sessionInputDrafts,
      sessionInputSnapshots,
      sessionType,
      sessionsNotice,
      setDiscussionStarted,
      startFreshDraft,
      updateAgentConfiguration,
      updateDiscussionAgents,
      updateDiscussionSynthesis,
      updateDiscussionTitleDraft,
      synthesis,
      targetLanguage,
      targetLanguageError,
      updateDraftAgents,
      updateDraftSynthesis,
      updateMaterial,
      updateSessionInputValue,
      updateSynthesisConfiguration,
      updateTargetLanguage,
      validateStart,
    ],
  );
}
