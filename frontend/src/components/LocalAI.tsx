import { useCallback, useEffect, useRef, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import {
  formatNumber,
  parseLocalizedInteger,
  translateClientError,
  translateErrorCode,
} from "../i18n";
import {
  abortLocalAIModelImport,
  cancelLocalAIInstall,
  deleteLocalAIModel,
  deleteLocalAIRuntime,
  getApplicationPreferences,
  getLocalAIDiagnostics,
  getLocalAIStatus,
  importLocalAIModelFromDirectory,
  installLocalAI,
  revealLocalAIModelsDirectory,
  setLocalAIPreferredModel,
  startLocalAI,
  stopLocalAI,
  updateLocalAIRuntime,
  updateApplicationPreferences,
  type LocalAIModelCatalogEntry,
  type LocalAIStartPayload,
} from "../api";
import type { LocalAIDiagnostics, LocalAIModelId, LocalAIState, LocalAIStatus } from "./types";
import {
  hasNativeLocalAIImportPicker,
  hasNativeManagedPathReveal,
  pickLocalAIImportDirectory,
  revealManagedPath,
} from "../desktopBridge";
import {
  canStart,
  describeDecisionBasis,
  getRuntimeUninstallControl,
  getModelCardAction,
  getModelCardVisualState,
  isModelOperation,
  isOperationActive,
  isServiceState,
  nextPollDelay,
  runtimeRationaleState,
  shouldInviteE4B,
  type LocalAIOperationKind,
  type LocalAIOperationState,
} from "./localAIState";
import {
  LOCAL_AI_MODEL_CATALOG as MODEL_CATALOG,
  LOCAL_AI_MODEL_ORDER as MODEL_ORDER,
  LOCAL_AI_MODEL_MAX_CONTEXT,
} from "./localAIModels";
import { formatBytes } from "./LocalAITransferProgress";
import { MaterialSymbol } from "./MaterialSymbol";
import IconButton from "./IconButton";
import { ConfirmDialog } from "./Modal";
import { BlockedActionHint } from "./BlockedActionHint";
import { NoticeBanner } from "./NoticeBanner";
import {
  ActionGroup,
  Button,
  Card,
  ChoiceIndicator,
  Field,
  IntegerInput,
  PageHeader,
  SectionHeader,
  StatusBadge,
} from "./design-system";

type LocalAIProps = {
  onHostsChanged: () => void | Promise<void>;
  onStatusChanged?: (status: LocalAIStatus) => void;
};

const DEFAULT_CONTEXT_TOKENS = 32_768;
const MIN_CONTEXT_TOKENS = 8_192;
export function validContextTokens(
  value: string,
  maximum: number,
  language?: string,
): number | null {
  const parsed = parseLocalizedInteger(value, language);
  return parsed !== null && parsed >= MIN_CONTEXT_TOKENS && parsed <= maximum ? parsed : null;
}

type SetupStep = "loading" | "choose" | "download" | "start" | "ready";

type PendingAction =
  | "context"
  | "folder"
  | "lifecycle"
  | "model-delete"
  | "mtp"
  | "preferred-model"
  | "runtime"
  | "transfer";

function defaultStatusText(state: LocalAIState | null, t: TFunction): string {
  switch (state) {
    case "not_installed":
      return t("localAi.statusNotInstalled");
    case "importing":
      return t("localAi.statusImporting");
    case "installed":
      return t("localAi.statusInstalled");
    case "starting":
      return t("localAi.statusStarting");
    case "running":
      return t("localAi.statusRunning");
    case "sleeping":
      return t("localAi.statusSleeping");
    case "stopped":
      return t("localAi.statusStopped");
    case "cancelling":
      return t("localAi.statusCancelling");
    case "cancelled":
      return t("localAi.statusCancelled");
    case "error":
      return t("localAi.statusError");
    default:
      return t("localAi.statusLoading");
  }
}

function localAIStatusMessage(errorCode: string | null | undefined, fallback: string): string {
  return errorCode ? translateErrorCode(errorCode) : fallback;
}

function downloadPhaseText(phase: LocalAIStatus["download_phase"], t: TFunction): string {
  switch (phase) {
    case "preparing":
      return t("localAi.downloadPreparing");
    case "runtime":
      return t("localAi.downloadRuntime");
    case "main_model":
      return t("localAi.downloadMainModel");
    case "mtp_drafter":
      return t("localAi.downloadMtpDrafter");
    case "finalizing":
      return t("localAi.downloadFinalizing");
    default:
      return t("localAi.downloadHint");
  }
}

function modelDisplaySizes(
  model: LocalAIModelCatalogEntry,
  status: LocalAIStatus | null,
): { main: string; draft: string; total: string } {
  const source = status?.models.find((entry) => entry.model_id === model.id);
  const mainBytes = source?.model_bytes ?? model.model_bytes;
  const draftBytes = source?.draft_bytes ?? model.draft_bytes;
  return {
    main: formatBytes(mainBytes) ?? model.model_size,
    draft: formatBytes(draftBytes) ?? model.draft_size,
    total: formatBytes(mainBytes + draftBytes) ?? model.model_size,
  };
}

function modelCopyKey(modelId: LocalAIModelId): "E2b" | "E4b" | "12b" {
  if (modelId === "gemma-4-e4b") return "E4b";
  if (modelId === "gemma-4-12b") return "12b";
  return "E2b";
}

type SelectionRecord = NonNullable<LocalAIDiagnostics["runtime_selection_diagnostics"]["record"]>;

function runtimeProfileName(profile: string): string {
  // The diagnostics API validates recorded profiles against the runtime catalog.
  const match =
    /^(macos|windows|linux)-(arm64|x86_64)-(metal|cpu|cuda|rocm|vulkan|sycl|opencl)$/.exec(profile);
  if (!match) return profile;
  const [, platform, architecture, accelerator] = match;
  const runtime = {
    metal: "Metal",
    cpu: "CPU",
    cuda: "CUDA",
    rocm: "ROCm",
    vulkan: "Vulkan",
    sycl: "SYCL",
    opencl: "OpenCL",
  }[accelerator];
  const os = { macos: "macOS", windows: "Windows", linux: "Linux" }[platform];
  return `${runtime} (${os} ${architecture === "arm64" ? "ARM64" : "x86-64"})`;
}

function runtimeSelectionAttemptText(
  attempt: SelectionRecord["attempts"][number],
  t: TFunction,
): string {
  if (attempt.stage === "runtime_update") {
    return t(`localAi.selectionUpdate_${attempt.result}`);
  }
  return t(`localAi.selectionAttempt_${attempt.result}`, {
    stage: t(`localAi.selectionStage_${attempt.stage}`),
  });
}

function runtimeSelectionCopy(record: SelectionRecord): string {
  return [
    "Runtime selection diagnostics (last recorded selection)",
    `Version: ${record.version}`,
    `Operation: ${record.operation}`,
    `Outcome: ${record.outcome}`,
    ...(record.selected_profile ? [`Selected runtime: ${record.selected_profile}`] : []),
    ...record.attempts.map(
      (attempt, index) =>
        `${index + 1}. ${attempt.profile} | ${attempt.stage} | ${attempt.result}${attempt.reason ? ` | ${attempt.reason}` : ""}`,
    ),
  ].join("\n");
}

function setupStep(
  state: LocalAIState | null,
  hasInstalledModel: boolean,
  runtimeInstalled: boolean,
): SetupStep {
  if (state === null) return "loading";
  if (state === "running" || state === "sleeping") return "ready";
  if (state === "starting") return "start";
  if (state === "downloading" || state === "importing" || state === "cancelling") return "download";
  if (hasInstalledModel && runtimeInstalled) return "start";
  return "choose";
}

export default function LocalAI({ onHostsChanged, onStatusChanged }: LocalAIProps) {
  const { t, i18n: translation } = useTranslation();
  const [status, setStatus] = useState<LocalAIStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<LocalAIDiagnostics | null>(null);
  const [diagnosticsLoadState, setDiagnosticsLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [selectionCopyFeedback, setSelectionCopyFeedback] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<LocalAIModelId>("gemma-4-e2b");
  const [mtpEnabled, setMtpEnabled] = useState(false);
  const [contextTokens, setContextTokens] = useState(String(DEFAULT_CONTEXT_TOKENS));
  const [savedContextTokens, setSavedContextTokens] = useState(DEFAULT_CONTEXT_TOKENS);
  const [defaultContextTokens, setDefaultContextTokens] = useState<number | null>(null);
  const contextInputRef = useRef<HTMLInputElement>(null);
  const contextDirtyRef = useRef(false);
  const restoreContextFocusRef = useRef(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pendingActions, setPendingActions] = useState<ReadonlySet<PendingAction>>(() => new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [statusLoadFailed, setStatusLoadFailed] = useState(false);
  const [modelPendingDeletion, setModelPendingDeletion] = useState<LocalAIModelId | null>(null);
  const [runtimeUninstallPending, setRuntimeUninstallPending] = useState(false);
  const runtimeUninstallButtonRef = useRef<HTMLButtonElement>(null);
  const mountedRef = useRef(true);
  const pendingActionsRef = useRef<Set<PendingAction>>(new Set());
  const statusRequestRef = useRef(0);
  const selectionWasExplicitRef = useRef(false);

  const refreshStatus = useCallback(
    async (preserveNotice = false): Promise<void> => {
      const requestId = ++statusRequestRef.current;
      const statusRequest = getLocalAIStatus();
      const optionalInformation = Promise.allSettled([
        getLocalAIDiagnostics(),
        getApplicationPreferences(),
      ]);
      try {
        const next = await statusRequest;
        if (!mountedRef.current || statusRequestRef.current !== requestId) return;
        setStatusLoadFailed(false);
        setStatus(next);
        onStatusChanged?.(next);
        setJobId(
          next.state === "downloading" ||
            next.state === "importing" ||
            next.state === "cancelling" ||
            next.operation_state === "downloading" ||
            next.operation_state === "importing" ||
            next.operation_state === "cancelling"
            ? (next.job_id ?? null)
            : null,
        );

        void optionalInformation.then(([diagnosticsResult, preferencesResult]) => {
          if (!mountedRef.current || statusRequestRef.current !== requestId) return;
          if (diagnosticsResult.status === "fulfilled") {
            setDiagnostics(diagnosticsResult.value);
            setDiagnosticsLoadState("ready");
          } else {
            setDiagnostics(null);
            setDiagnosticsLoadState("error");
          }
          setSelectionCopyFeedback(null);
          if (preferencesResult.status === "fulfilled") {
            const preferences = preferencesResult.value;
            setDefaultContextTokens(preferences.local_ai_context_default_tokens);
            const nextContextTokens =
              Number.isInteger(preferences.local_ai_context_tokens) &&
              preferences.local_ai_context_tokens > 0
                ? preferences.local_ai_context_tokens
                : Number.isInteger(next.context_tokens) && (next.context_tokens ?? 0) > 0
                  ? next.context_tokens
                  : null;
            if (Number.isInteger(nextContextTokens) && (nextContextTokens ?? 0) > 0) {
              if (!contextDirtyRef.current) setContextTokens(String(nextContextTokens));
              setSavedContextTokens(nextContextTokens as number);
            }
            setMtpEnabled(preferences.local_ai_mtp_enabled === true);
          } else {
            if (Number.isInteger(next.context_tokens) && (next.context_tokens ?? 0) > 0) {
              if (!contextDirtyRef.current) setContextTokens(String(next.context_tokens));
              setSavedContextTokens(next.context_tokens as number);
            }
            setMtpEnabled(next.mtp_enabled === true);
          }
        });
      } catch {
        if (mountedRef.current && statusRequestRef.current === requestId && !preserveNotice) {
          setStatusLoadFailed(true);
        }
      }
    },
    [onStatusChanged],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setNotice(null);
    setSelectionCopyFeedback(null);
  }, [translation.resolvedLanguage]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (status === null) {
      const timer = window.setInterval(() => void refreshStatus(), 2000);
      return () => window.clearInterval(timer);
    }
    const delay =
      status.operation_state === "downloading" ||
      status.operation_state === "importing" ||
      status.operation_state === "cancelling"
        ? 500
        : nextPollDelay(status.state);
    if (delay === null) return;
    const timer = window.setTimeout(() => void refreshStatus(), delay);
    return () => window.clearTimeout(timer);
  }, [refreshStatus, status]);

  const hasInstalledModel = Boolean(status?.models.some((entry) => entry.installed));
  const needsRuntimeRecovery = hasInstalledModel && !status?.runtime_installed;

  useEffect(() => {
    if (!status || selectionWasExplicitRef.current) return;
    const preferredInstalled = status?.models.find(
      (entry) => entry.model_id === status.preferred_model_id && entry.installed,
    );
    if (preferredInstalled && selectedModel !== preferredInstalled.model_id) {
      setSelectedModel(preferredInstalled.model_id);
    }
  }, [selectedModel, status]);

  const currentState = status?.state ?? null;
  const requestedModel = selectedModel;
  const requestedInventory = status?.models.find((entry) => entry.model_id === requestedModel);
  const installedModel = MODEL_ORDER.find((modelId) =>
    status?.models.some((entry) => entry.model_id === modelId && entry.installed),
  );
  const operationKind: LocalAIOperationKind =
    status?.operation_kind ??
    (currentState === "importing"
      ? "model_import"
      : currentState === "downloading"
        ? "model_download"
        : currentState === "cancelling"
          ? status?.import_phase
            ? "model_import"
            : "model_download"
          : null);
  const operationState: LocalAIOperationState =
    status?.operation_state ??
    (currentState === "importing"
      ? "importing"
      : currentState === "downloading"
        ? "downloading"
        : currentState === "cancelling"
          ? "cancelling"
          : null);
  const transferModel =
    isModelOperation(operationKind) &&
    status?.operation_model_id &&
    status.operation_model_id in MODEL_CATALOG
      ? status.operation_model_id
      : (currentState === "downloading" ||
            currentState === "importing" ||
            currentState === "cancelling") &&
          status?.model_id &&
          status.model_id in MODEL_CATALOG
        ? status.model_id
        : null;
  const selected = requestedInventory?.installed
    ? requestedModel
    : (installedModel ?? requestedModel);
  const modelContextMaximum = LOCAL_AI_MODEL_MAX_CONTEXT[selected];
  const parsedContextTokens = validContextTokens(
    contextTokens,
    modelContextMaximum,
    translation.resolvedLanguage,
  );
  const contextError = parsedContextTokens === null;
  const contextUnsaved = parsedContextTokens !== null && parsedContextTokens !== savedContextTokens;
  const runningContextDiffers =
    (currentState === "running" || currentState === "sleeping") &&
    status?.context_tokens !== savedContextTokens;
  const selectedCard = MODEL_CATALOG[selected];
  const transferCard = transferModel ? MODEL_CATALOG[transferModel] : null;
  const selectedInventory = status?.models.find((entry) => entry.model_id === selected);
  const selectedInstalled = Boolean(selectedInventory?.installed);
  const operationActive = isOperationActive(operationState);
  const modelOperationActive = isModelOperation(operationKind) && operationActive;
  const isImportOperation = operationKind === "model_import";
  const stage = setupStep(currentState, hasInstalledModel, status?.runtime_installed ?? false);
  const visibleNotice = notice === t("localAi.modelCopying") && !isImportOperation ? null : notice;
  const defaultStateText =
    currentState === "downloading"
      ? downloadPhaseText(status?.download_phase, t)
      : defaultStatusText(currentState, t);
  const statusText =
    operationKind && operationState && currentState !== "error"
      ? defaultStateText
      : localAIStatusMessage(status?.error_code, defaultStateText);
  const operationErrorText =
    operationState === "error"
      ? localAIStatusMessage(status?.error_code, status?.message || t("localAi.statusError"))
      : null;
  const runtimeUninstallControl = getRuntimeUninstallControl({
    runtime_installed: status?.runtime_installed ?? false,
    state: currentState,
    models: status?.models ?? [],
  });
  const runtimeUninstallReason =
    runtimeUninstallControl.kind === "disabled" ? t(runtimeUninstallControl.reasonKey) : null;
  const selectedStartable = Boolean(
    selectedInstalled &&
    status?.runtime_installed &&
    canStart({
      state: currentState ?? "not_installed",
      integrity: selectedInventory?.integrity ?? "unknown",
    }),
  );
  const activeModel =
    status?.model_id && status.model_id in MODEL_CATALOG ? MODEL_CATALOG[status.model_id] : null;
  const runningAnotherModel =
    currentState === "running" && activeModel !== null && activeModel.id !== selectedCard.id;

  const isPending = (action: PendingAction): boolean => pendingActions.has(action);

  useEffect(() => {
    if (restoreContextFocusRef.current && !pendingActions.has("context")) {
      restoreContextFocusRef.current = false;
      contextInputRef.current?.focus();
    }
  }, [pendingActions]);

  const setPending = (action: PendingAction, value: boolean) => {
    if (value) pendingActionsRef.current.add(action);
    else pendingActionsRef.current.delete(action);
    if (mountedRef.current) setPendingActions(new Set(pendingActionsRef.current));
  };

  const runAction = async (
    pendingAction: PendingAction,
    action: () => Promise<void>,
    fallback: string,
  ) => {
    if (pendingActionsRef.current.has(pendingAction)) return;
    setPending(pendingAction, true);
    setNotice(null);
    try {
      await action();
      await refreshStatus();
    } catch (error) {
      if (mountedRef.current) setNotice(translateClientError(error, fallback));
      await refreshStatus(true);
    } finally {
      setPending(pendingAction, false);
    }
  };

  const chooseModel = (modelId: LocalAIModelId) => {
    const inventory = status?.models.find((entry) => entry.model_id === modelId);
    if (!inventory?.installed) return;
    selectionWasExplicitRef.current = true;
    setSelectedModel(modelId);
    setNotice(null);
    if (status?.preferred_model_id !== modelId) {
      void runAction(
        "preferred-model",
        async () => {
          await setLocalAIPreferredModel(modelId);
          await Promise.resolve(onHostsChanged());
        },
        t("localAi.preferredModelSaveError"),
      );
    }
  };

  const handleInstall = (modelId = requestedModel) => {
    void runAction(
      "transfer",
      async () => {
        const result = await installLocalAI({ model_id: modelId, start_after_install: false });
        setJobId(result.job_id);
      },
      t("localAi.downloadStartError"),
    );
  };

  const handleCancelDownload = () => {
    void runAction(
      "transfer",
      async () => {
        if (operationKind === "model_import") await abortLocalAIModelImport(jobId ?? "");
        else await cancelLocalAIInstall({ job_id: jobId ?? "" });
      },
      operationKind === "model_import"
        ? t("localAi.importCancelError")
        : t("localAi.downloadCancelError"),
    );
  };

  const handleStart = () => {
    if (parsedContextTokens === null || contextUnsaved || isPending("context")) return;
    const payload: LocalAIStartPayload = {
      model_id: selected,
      context_tokens: parsedContextTokens,
      mtp_enabled: mtpEnabled,
      ...(mtpEnabled ? { mtp_draft_tokens: 4 } : {}),
    };
    void runAction(
      "lifecycle",
      async () => {
        await updateApplicationPreferences({
          local_ai_context_tokens: parsedContextTokens,
          local_ai_context_model_id: selected,
          local_ai_mtp_enabled: mtpEnabled,
        });
        await startLocalAI(payload);
        await Promise.resolve(onHostsChanged());
      },
      t("localAi.startError"),
    );
  };

  const persistContextTokens = () => {
    if (parsedContextTokens === null || !contextUnsaved) return;
    void runAction(
      "context",
      () =>
        updateApplicationPreferences({
          local_ai_context_tokens: parsedContextTokens,
          local_ai_context_model_id: selected,
        }).then(() => {
          contextDirtyRef.current = false;
          setSavedContextTokens(parsedContextTokens);
        }),
      t("localAi.launchSettingsSaveError"),
    );
  };

  const resetContextTokens = () => {
    if (defaultContextTokens === null || isPending("context")) return;
    setContextTokens(String(defaultContextTokens));
    contextDirtyRef.current = false;
    if (savedContextTokens === defaultContextTokens) {
      contextInputRef.current?.focus();
      return;
    }
    restoreContextFocusRef.current = true;
    void runAction(
      "context",
      () =>
        updateApplicationPreferences({
          local_ai_context_tokens: defaultContextTokens,
          local_ai_context_model_id: selected,
        }).then(() => setSavedContextTokens(defaultContextTokens)),
      t("localAi.launchSettingsSaveError"),
    );
  };

  const setPersistedMtpEnabled = (enabled: boolean) => {
    setMtpEnabled(enabled);
    void runAction(
      "mtp",
      () => updateApplicationPreferences({ local_ai_mtp_enabled: enabled }).then(() => undefined),
      t("localAi.launchSettingsSaveError"),
    );
  };

  const handleStop = () => {
    void runAction(
      "lifecycle",
      async () => {
        await stopLocalAI();
        await Promise.resolve(onHostsChanged());
      },
      t("localAi.stopError"),
    );
  };

  const startDirectoryImport = async () => {
    await runAction(
      "transfer",
      async () => {
        const sourcePath = hasNativeLocalAIImportPicker()
          ? await pickLocalAIImportDirectory()
          : undefined;
        if (sourcePath === null) return;
        const result = await importLocalAIModelFromDirectory(sourcePath);
        if (!mountedRef.current) return;
        setSelectedModel(result.model_id);
        setJobId(result.job_id);
        setNotice(t("localAi.modelCopying"));
      },
      t("localAi.importError"),
    );
  };

  const revealModelsDirectory = async () => {
    if (pendingActionsRef.current.has("folder")) return;
    setPending("folder", true);
    setNotice(null);
    try {
      if (hasNativeManagedPathReveal()) {
        await revealManagedPath("local_ai_models");
      } else {
        await revealLocalAIModelsDirectory();
      }
    } catch (error) {
      if (mountedRef.current)
        setNotice(translateClientError(error, t("localAi.revealModelsFolderError")));
    } finally {
      setPending("folder", false);
    }
  };

  const hardwareOs = status?.os_label ?? t("localAi.notReported");
  const hardwareCpu = status?.cpu_label
    ? status.logical_cpu_count
      ? `${status.cpu_label} · ${t("localAi.logicalCores", { count: status.logical_cpu_count })}`
      : status.cpu_label
    : status?.logical_cpu_count
      ? t("localAi.logicalCores", { count: status.logical_cpu_count })
      : t("localAi.notReported");
  const hardwareMemory =
    status?.ram_gb && status.ram_gb > 0
      ? t("localAi.memoryRam", { memory: formatNumber(status.ram_gb) })
      : t("localAi.notReported");
  const dedicatedGpuMemory =
    status?.inference_memory_kind === "vram" &&
    status.inference_memory_gb &&
    status.inference_memory_gb > 0
      ? t("localAi.memoryVram", { memory: formatNumber(status.inference_memory_gb) })
      : null;
  const runtimeSelection = status?.runtime_selection ?? null;
  const selectionDiagnostics = diagnostics?.runtime_selection_diagnostics;
  const selectionRecord =
    selectionDiagnostics?.state === "available" ? (selectionDiagnostics.record ?? null) : null;
  const installedRuntimeProfile = status?.runtime_installed
    ? (runtimeSelection?.runtime_profile ?? null)
    : null;
  const inferenceBackend =
    runtimeSelection?.accelerator_label ??
    (status === null ? t("localAi.detectedByServer") : t("localAi.notReported"));
  const decisionBasis = describeDecisionBasis(runtimeSelection?.decision_basis ?? null);
  const rationaleState = runtimeRationaleState(status);

  const renderModelCard = (model: LocalAIModelCatalogEntry) => {
    const inventory = status?.models.find((entry) => entry.model_id === model.id);
    const installed = Boolean(inventory?.installed);
    const isSelected = installed && model.id === selected;
    const isRunning =
      (currentState === "running" || currentState === "sleeping") && status?.model_id === model.id;
    const isPreferred = status?.preferred_model_id === model.id;
    const transferringThisModel = modelOperationActive && transferModel === model.id;
    const failedTransfer =
      operationState === "error" && isModelOperation(operationKind) && transferModel === model.id;
    const action = getModelCardAction(
      inventory,
      isServiceState(currentState) ? (status?.model_id ?? null) : null,
    );
    const visualState = getModelCardVisualState({ isPreferred, isActive: isRunning, installed });
    const sizes = modelDisplaySizes(model, status);
    const key = modelCopyKey(model.id);
    const loaded = isImportOperation ? (status?.import_bytes ?? 0) : (status?.download_bytes ?? 0);
    const total = isImportOperation ? (status?.import_total ?? 0) : (status?.download_total ?? 0);
    const percent = total > 0 ? Math.round((loaded / total) * 100) : null;
    const transferText = isImportOperation
      ? status?.import_phase === "verifying"
        ? t("localAi.importVerifying", { model: model.label })
        : t("localAi.importCopying", { model: model.label })
      : downloadPhaseText(status?.download_phase, t);
    return (
      <Card
        role="group"
        aria-label={model.label}
        className={`local-ai-model-card${isSelected ? " is-selected" : ""}${visualState ? ` is-${visualState}` : ""}`}
        key={model.id}
      >
        <div className="local-ai-model-card-heading">
          <input
            className="choice-radio-input"
            id={`local-ai-model-${model.id}`}
            type="radio"
            name="local-ai-model"
            value={model.id}
            checked={isSelected}
            disabled={!installed || isPending("preferred-model")}
            onChange={() => chooseModel(model.id)}
          />
          <label htmlFor={`local-ai-model-${model.id}`}>
            <ChoiceIndicator selected={isSelected} />
            <span className="local-ai-model-card-copy">
              <strong>{model.label}</strong>
              <span>{t(`localAi.model${key}Title`)}</span>
            </span>
          </label>
        </div>
        <p className="local-ai-model-description">{t(`localAi.model${key}Description`)}</p>
        <p className="local-ai-model-choice-meta">
          {t("localAi.downloadSize", { size: sizes.total })}
        </p>
        {(installed || isRunning) && (
          <div className="local-ai-model-badges" aria-label={t("localAi.modelStatus")}>
            {installed && <StatusBadge tone="info">{t("localAi.downloaded")}</StatusBadge>}
            {isRunning && <StatusBadge tone="success">{t("localAi.running")}</StatusBadge>}
          </div>
        )}
        {model.id === "gemma-4-e4b" && shouldInviteE4B(status) && !installed && (
          <NoticeBanner className="local-ai-model-invitation" tone="info" role="note">
            {t("localAi.e4bInvitation")}
          </NoticeBanner>
        )}
        {transferringThisModel && (
          <div className="local-ai-model-transfer">
            <div className="local-ai-model-transfer-header">
              <span className="local-ai-model-transfer-status">{transferText}</span>
              <span className="local-ai-model-transfer-meta">
                <span>
                  {percent === null
                    ? t("localAi.progressPending")
                    : t("localAi.progressPercent", { percent })}
                </span>
                <span className="local-ai-model-transfer-separator" aria-hidden="true">
                  ·
                </span>
                <span className="local-ai-model-transfer-total">
                  {formatBytes(total) ?? sizes.total}
                </span>
              </span>
            </div>
            <progress
              className="local-ai-progress local-ai-model-transfer-progress"
              value={total > 0 ? Math.min(loaded, total) : undefined}
              max={total || undefined}
              aria-label={
                isImportOperation ? t("localAi.importProgress") : t("localAi.downloadProgress")
              }
              aria-valuetext={
                percent === null
                  ? t("localAi.progressPending")
                  : t("localAi.progressPercent", { percent })
              }
            />
          </div>
        )}
        {failedTransfer && operationErrorText && (
          <p className="local-ai-model-transfer-error" role="alert">
            {operationErrorText}
          </p>
        )}
        <div className="local-ai-model-card-footer">
          <ActionGroup className="local-ai-model-actions" align="start">
            {!installed && !transferringThisModel && (
              <Button
                onClick={() => handleInstall(model.id)}
                disabled={isPending("transfer") || operationActive}
              >
                {failedTransfer
                  ? t("localAi.retryDownload", { model: model.label })
                  : t("localAi.download")}
              </Button>
            )}
            {transferringThisModel && (
              <Button
                onClick={handleCancelDownload}
                disabled={isPending("transfer") || operationState === "cancelling" || !jobId}
              >
                {isImportOperation ? t("localAi.cancelImport") : t("common.cancel")}
              </Button>
            )}
            {installed && (
              <Button
                className="local-ai-delete-btn"
                variant="danger"
                disabled={
                  isPending("model-delete") ||
                  action.kind === "delete-disabled" ||
                  transferringThisModel
                }
                onClick={() => setModelPendingDeletion(model.id)}
                aria-describedby={
                  action.kind === "delete-disabled"
                    ? `local-ai-active-model-${model.id}`
                    : undefined
                }
              >
                <MaterialSymbol name="delete" decorative />
                {t("common.delete")}
              </Button>
            )}
          </ActionGroup>
          {action.kind === "delete-disabled" && (
            <BlockedActionHint id={`local-ai-active-model-${model.id}`}>
              {t(action.reasonKey)}
            </BlockedActionHint>
          )}
          <a className="local-ai-link" href={model.model_url} target="_blank" rel="noreferrer">
            {t("localAi.modelPage")}
          </a>
        </div>
      </Card>
    );
  };

  const renderHardware = () => (
    <section className="local-ai-hardware" aria-labelledby="local-ai-hardware-title">
      <h2 id="local-ai-hardware-title">{t("localAi.hardware")}</h2>
      <dl className="local-ai-details">
        <div>
          <dt>{t("localAi.operatingSystem")}</dt>
          <dd>{hardwareOs}</dd>
        </div>
        <div>
          <dt>{t("localAi.processor")}</dt>
          <dd>{hardwareCpu}</dd>
        </div>
        <div>
          <dt>{t("localAi.graphics")}</dt>
          <dd>{status?.gpu_label ?? t("localAi.notReported")}</dd>
        </div>
        <div>
          <dt>{t("localAi.systemMemory")}</dt>
          <dd>{hardwareMemory}</dd>
        </div>
        {dedicatedGpuMemory && (
          <div>
            <dt>{t("localAi.dedicatedGpuMemory")}</dt>
            <dd>{dedicatedGpuMemory}</dd>
          </div>
        )}
        <div>
          <dt>{t("localAi.inferenceBackend")}</dt>
          <dd>{inferenceBackend}</dd>
        </div>
      </dl>
      {runtimeSelection && (
        <p className="local-ai-runtime-summary" data-state={rationaleState ?? undefined}>
          {status?.runtime_installed ? t("localAi.installedRuntime") : t("localAi.plannedRuntime")}:{" "}
          <strong>{inferenceBackend}</strong>
          {runtimeSelection.runtime_profile && (
            <> · {t("localAi.profile", { profile: runtimeSelection.runtime_profile })}</>
          )}
          {decisionBasis.text && (
            <>
              {" "}
              ·{" "}
              {decisionBasis.kind === "compatible"
                ? t(
                    status?.runtime_installed
                      ? "localAi.decisionCompatibleInstalled"
                      : "localAi.decisionCompatible",
                  )
                : t("localAi.decisionCpuFallback")}
            </>
          )}
          .
        </p>
      )}
      {status?.inference_memory_kind === "unified" && (
        <p className="local-ai-runtime-summary">{t("localAi.sharedMemoryExplanation")}</p>
      )}
    </section>
  );

  return (
    <div className="local-ai" aria-labelledby="local-ai-title">
      <PageHeader
        className="local-ai-header"
        title={t("localAi.title")}
        titleId="local-ai-title"
        subtitle={t("localAi.setupIntro")}
      />

      <Card className={`local-ai-state-card local-ai-state-card--${stage}`} aria-live="polite">
        {status === null ? (
          <>
            <h2>{t("localAi.statusLoading")}</h2>
            <p>{t(statusLoadFailed ? "localAi.statusLoadError" : "localAi.loadingHint")}</p>
          </>
        ) : stage === "choose" ? (
          <>
            <h2>
              {needsRuntimeRecovery
                ? t("localAi.runtimeRecoveryTitle")
                : currentState === "error"
                  ? t("localAi.chooseRetryTitle")
                  : t("localAi.chooseTitle")}
            </h2>
            <p className="local-ai-status">
              {visibleNotice ??
                (currentState === "error"
                  ? statusText
                  : needsRuntimeRecovery
                    ? t("localAi.runtimeRecoveryHint")
                    : t("localAi.chooseFromModelsBelow"))}
            </p>
          </>
        ) : stage === "download" ? (
          <>
            <h2>{t("localAi.serviceStatus")}</h2>
            <p className="local-ai-status">
              {visibleNotice ??
                (isImportOperation ? t("localAi.importRunning") : t("localAi.downloadRunning"))}
            </p>
            <p className="local-ai-muted">
              {t("localAi.transferInModelCard", {
                model: transferCard?.label ?? selectedCard.label,
              })}
            </p>
          </>
        ) : stage === "start" ? (
          <>
            <h2>
              {currentState === "starting" ? t("localAi.starting") : t("localAi.readyToStartTitle")}
            </h2>
            <p className="local-ai-status">
              {visibleNotice ??
                (currentState === "error" || (status?.message && currentState !== "cancelled")
                  ? statusText
                  : t("localAi.readyToStartHint", { model: selectedCard.label }))}
            </p>
            {currentState !== "starting" && (
              <ActionGroup className="local-ai-actions" align="start">
                <Button
                  variant="primary"
                  onClick={handleStart}
                  disabled={
                    isPending("lifecycle") ||
                    isPending("context") ||
                    !selectedStartable ||
                    contextError ||
                    contextUnsaved
                  }
                >
                  {t("localAi.start")}
                </Button>
              </ActionGroup>
            )}
          </>
        ) : (
          <>
            <h2>{t("localAi.readyTitle")}</h2>
            <p className="local-ai-status">
              {visibleNotice ??
                (currentState === "sleeping"
                  ? t("localAi.readySleeping", { model: activeModel?.label ?? selectedCard.label })
                  : runningAnotherModel
                    ? t("localAi.runningModelChangeHint", {
                        active: activeModel.label,
                        next: selectedCard.label,
                      })
                    : t("localAi.readyRunning", {
                        model: activeModel?.label ?? selectedCard.label,
                      }))}
            </p>
            <ActionGroup className="local-ai-actions" align="start">
              <Button onClick={handleStop} disabled={isPending("lifecycle")}>
                {t("common.stop")}
              </Button>
            </ActionGroup>
          </>
        )}
      </Card>

      <section className="local-ai-models" aria-labelledby="local-ai-models-title">
        <SectionHeader title={t("localAi.modelsTitle")} titleId="local-ai-models-title" />
        <div className="local-ai-model-choice-grid">
          {MODEL_ORDER.map((id) => renderModelCard(MODEL_CATALOG[id]))}
        </div>
        <ActionGroup className="local-ai-model-directory-actions" align="start">
          <Button
            variant="secondary"
            onClick={() => void startDirectoryImport()}
            disabled={isPending("transfer") || operationActive}
          >
            {t("localAi.importFromFolder")}
          </Button>
          <Button disabled={isPending("folder")} onClick={() => void revealModelsDirectory()}>
            {isPending("folder") ? t("localAi.openingModelsFolder") : t("localAi.openModelsFolder")}
          </Button>
        </ActionGroup>
        {operationActive && (
          <BlockedActionHint id="local-ai-transfer-lane-reason">
            {t("localAi.transferLaneBlocked")}
          </BlockedActionHint>
        )}
      </section>

      <details className="local-ai-panel local-ai-advanced">
        <summary>{t("localAi.advancedSettings")}</summary>
        <div className="local-ai-launch-settings">
          <Card surface="recessed" className="local-ai-field">
            <Field
              htmlFor="local-ai-context"
              label={t("localAi.maximumContext")}
              description={
                <>
                  {t("localAi.contextWindowHint", {
                    minimum: formatNumber(MIN_CONTEXT_TOKENS),
                    maximum: formatNumber(modelContextMaximum),
                  })}
                  {runningContextDiffers && (
                    <>
                      <br />
                      {t("localAi.contextRestartRequired", {
                        effective: formatNumber(status?.context_tokens ?? 0),
                      })}
                    </>
                  )}
                </>
              }
              error={
                contextError
                  ? t("localAi.contextRange", {
                      minimum: formatNumber(MIN_CONTEXT_TOKENS),
                      maximum: formatNumber(modelContextMaximum),
                    })
                  : undefined
              }
              errorId="local-ai-context-error"
            >
              <div className="local-ai-context-control">
                <IntegerInput
                  ref={contextInputRef}
                  id="local-ai-context"
                  min={MIN_CONTEXT_TOKENS}
                  max={modelContextMaximum}
                  value={contextTokens}
                  onValueChange={(value) => {
                    contextDirtyRef.current = true;
                    setContextTokens(value);
                  }}
                  onBlur={(event) => {
                    if (parsedContextTokens !== null) setContextTokens(String(parsedContextTokens));
                    if (
                      event.relatedTarget instanceof Element &&
                      event.relatedTarget.closest(".local-ai-context-reset")
                    )
                      return;
                    persistContextTokens();
                  }}
                  disabled={isPending("context")}
                  aria-describedby={contextUnsaved ? "local-ai-context-unsaved" : undefined}
                />
                {defaultContextTokens !== null &&
                  (contextTokens !== String(defaultContextTokens) ||
                    savedContextTokens !== defaultContextTokens) && (
                    <IconButton
                      className="local-ai-context-reset"
                      label={t("setup.resetToDefault", { label: t("localAi.maximumContext") })}
                      disabled={isPending("context")}
                      onClick={resetContextTokens}
                    >
                      <MaterialSymbol name="refresh" decorative />
                    </IconButton>
                  )}
              </div>
              {contextUnsaved && (
                <BlockedActionHint id="local-ai-context-unsaved">
                  {t("localAi.contextUnsaved")}
                </BlockedActionHint>
              )}
            </Field>
          </Card>
          <Card
            surface="recessed"
            className="local-ai-field local-ai-mtp-field"
            role="group"
            aria-labelledby="local-ai-mtp-label"
          >
            <h3 id="local-ai-mtp-label" className="local-ai-field-label">
              {t("localAi.mtpAcceleration")}
            </h3>
            <label className="checkbox" htmlFor="local-ai-mtp">
              <input
                id="local-ai-mtp"
                type="checkbox"
                checked={mtpEnabled}
                onChange={(event) => setPersistedMtpEnabled(event.target.checked)}
                disabled={isPending("mtp")}
              />
              {t("localAi.enableMtp")}
            </label>
            <small>{t("localAi.mtpHint")}</small>
          </Card>
        </div>
      </details>

      <details className="local-ai-panel local-ai-maintenance">
        <summary>{t("localAi.maintenance")}</summary>
        {renderHardware()}
        <section className="local-ai-lifecycle" aria-labelledby="local-ai-lifecycle-title">
          <h2 id="local-ai-lifecycle-title">{t("localAi.lifecycle")}</h2>
          <p>{t("localAi.lifecycleDescription")}</p>
        </section>
        <section
          className="local-ai-runtime-maintenance"
          aria-labelledby="local-ai-maintenance-actions"
        >
          <h2 id="local-ai-maintenance-actions">{t("localAi.runtimeMaintenance")}</h2>
          <div className="local-ai-runtime-actions">
            <div className="local-ai-runtime-action">
              <ActionGroup className="local-ai-actions" align="start">
                <Button
                  onClick={() =>
                    void runAction(
                      "runtime",
                      async () => {
                        await updateLocalAIRuntime();
                      },
                      t("localAi.runtimeUpdateError"),
                    )
                  }
                  disabled={isPending("runtime") || isServiceState(currentState) || operationActive}
                  aria-describedby="local-ai-runtime-repair-description"
                >
                  {status?.runtime_installed
                    ? t("localAi.updateRuntime")
                    : t("localAi.installRuntime")}
                </Button>
                {status?.error_code === "accelerator_failed" && (
                  <Button
                    onClick={() =>
                      void runAction(
                        "runtime",
                        async () => {
                          await updateLocalAIRuntime(true);
                        },
                        t("localAi.cpuFallbackError"),
                      )
                    }
                    disabled={
                      isPending("runtime") || isServiceState(currentState) || operationActive
                    }
                    aria-describedby="local-ai-runtime-repair-description"
                  >
                    {t("localAi.useCpuRuntime")}
                  </Button>
                )}
              </ActionGroup>
              <p id="local-ai-runtime-repair-description" className="local-ai-runtime-summary">
                {t("localAi.runtimeUpdateDescription")}
              </p>
            </div>
            <div className="local-ai-runtime-action">
              <Button
                ref={runtimeUninstallButtonRef}
                variant="danger"
                className="local-ai-delete-btn"
                onClick={() => setRuntimeUninstallPending(true)}
                disabled={
                  isPending("runtime") ||
                  operationActive ||
                  runtimeUninstallControl.kind === "disabled"
                }
                aria-describedby={`local-ai-runtime-uninstall-description${
                  runtimeUninstallReason ? " local-ai-runtime-uninstall-reason" : ""
                }`}
                title={runtimeUninstallReason ?? undefined}
              >
                {t("localAi.uninstallRuntime")}
              </Button>
              <p id="local-ai-runtime-uninstall-description" className="local-ai-runtime-summary">
                {t("localAi.runtimeUninstallDescription")}
              </p>
              {runtimeUninstallReason && (
                <BlockedActionHint
                  id="local-ai-runtime-uninstall-reason"
                  className="local-ai-runtime-hint"
                >
                  {runtimeUninstallReason}
                </BlockedActionHint>
              )}
            </div>
          </div>
        </section>
        <details className="local-ai-diagnostics">
          <summary>{t("common.technicalDetails")}</summary>
          {diagnostics?.command_reference || diagnostics?.error_code ? (
            <>
              <dl>
                {diagnostics.command_reference && (
                  <div>
                    <dt>
                      {t(
                        diagnostics.command_kind === "active"
                          ? "localAi.currentCommand"
                          : diagnostics.command_kind === "last_attempt"
                            ? "localAi.lastAttemptCommand"
                            : "localAi.nextStartCommand",
                      )}
                    </dt>
                    <dd>
                      <code>{diagnostics.command_reference}</code>
                    </dd>
                  </div>
                )}
                {diagnostics.error_code && (
                  <div>
                    <dt>{t("localAi.diagnosticErrorCode")}</dt>
                    <dd>
                      <code>{diagnostics.error_code}</code>
                    </dd>
                  </div>
                )}
                {diagnostics.exit_code !== null && diagnostics.exit_code !== undefined && (
                  <div>
                    <dt>{t("localAi.diagnosticExitCode")}</dt>
                    <dd>
                      <code>{diagnostics.exit_code}</code>
                    </dd>
                  </div>
                )}
              </dl>
              {(diagnostics.log_tail?.length ?? 0) > 0 && (
                <>
                  <p className="local-ai-diagnostic-label">{t("localAi.diagnosticLogTail")}</p>
                  <ul className="local-ai-diagnostic-log">
                    {(diagnostics.log_tail ?? []).map((line, index) => (
                      <li key={`${index}-${line}`}>
                        <code>{line}</code>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <p>{t("localAi.noDiagnostics")}</p>
          )}
          <section
            className="local-ai-selection-diagnostics"
            aria-labelledby="local-ai-selection-title"
          >
            <div className="local-ai-selection-heading">
              <h3 id="local-ai-selection-title">{t("localAi.selectionDiagnosticsTitle")}</h3>
              <Button
                variant="secondary"
                size="small"
                disabled={!selectionRecord}
                onClick={async () => {
                  if (!selectionRecord) return;
                  try {
                    await navigator.clipboard.writeText(runtimeSelectionCopy(selectionRecord));
                    setSelectionCopyFeedback(t("localAi.selectionCopySuccess"));
                  } catch {
                    setSelectionCopyFeedback(t("localAi.selectionCopyFailure"));
                  }
                }}
              >
                {t("localAi.selectionCopy")}
              </Button>
            </div>
            <p className="local-ai-runtime-summary">
              {t("localAi.selectionHistorical")}
              <br />
              {t("localAi.selectionNotLive")}
            </p>
            {selectionRecord ? (
              <>
                <dl>
                  <div>
                    <dt>{t("localAi.selectionOperation")}</dt>
                    <dd>{t(`localAi.selectionOperation_${selectionRecord.operation}`)}</dd>
                  </div>
                  <div>
                    <dt>{t("localAi.selectionOutcome")}</dt>
                    <dd>{t(`localAi.selectionOutcome_${selectionRecord.outcome}`)}</dd>
                  </div>
                  {selectionRecord.selected_profile && (
                    <div>
                      <dt>{t("localAi.selectionSelectedRuntime")}</dt>
                      <dd>{runtimeProfileName(selectionRecord.selected_profile)}</dd>
                    </div>
                  )}
                </dl>
                {selectionRecord.selected_profile &&
                  installedRuntimeProfile &&
                  selectionRecord.selected_profile !== installedRuntimeProfile && (
                    <p className="local-ai-runtime-summary">
                      {t("localAi.selectionInstalledDiffers", {
                        profile: runtimeProfileName(installedRuntimeProfile),
                      })}
                    </p>
                  )}
                {selectionRecord.selected_profile && status?.runtime_installed === false && (
                  <p className="local-ai-runtime-summary">
                    {t("localAi.selectionNoInstalledRuntime")}
                  </p>
                )}
                <h4>{t("localAi.selectionCandidates")}</h4>
                {selectionRecord.attempts.length ? (
                  <ol className="local-ai-selection-attempts">
                    {selectionRecord.attempts.map((attempt, index) => (
                      <li key={`${index}-${attempt.profile}-${attempt.stage}`}>
                        <span>{runtimeProfileName(attempt.profile)}</span>
                        <span>{runtimeSelectionAttemptText(attempt, t)}</span>
                        {attempt.reason && (
                          <span>
                            {t("localAi.selectionReason", {
                              reason: t(`localAi.selectionReason_${attempt.reason}`),
                            })}
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>{t("localAi.selectionNoCandidates")}</p>
                )}
              </>
            ) : (
              <p>
                {t(
                  diagnosticsLoadState === "loading"
                    ? "localAi.selectionLoading"
                    : diagnosticsLoadState === "error"
                      ? "localAi.selectionUnavailable"
                      : selectionDiagnostics?.state === "invalid"
                        ? "localAi.selectionInvalid"
                        : "localAi.selectionMissing",
                )}
              </p>
            )}
            <p role="status" aria-live="polite" className="local-ai-selection-feedback">
              {selectionCopyFeedback}
            </p>
          </section>
        </details>
      </details>
      {modelPendingDeletion && (
        <ConfirmDialog
          title={t("localAi.deleteModelTitle")}
          message={t("localAi.deleteModelConfirm", {
            model: MODEL_CATALOG[modelPendingDeletion].label,
          })}
          cancelLabel={t("common.cancel")}
          variant="delete"
          onCancel={() => setModelPendingDeletion(null)}
          onConfirm={() => {
            const modelId = modelPendingDeletion;
            setModelPendingDeletion(null);
            void runAction(
              "model-delete",
              async () => {
                await deleteLocalAIModel({ model_id: modelId });
              },
              t("localAi.deleteFilesError"),
            );
          }}
          disabled={isPending("model-delete")}
        />
      )}
      {runtimeUninstallPending && (
        <ConfirmDialog
          title={t("localAi.uninstallRuntimeTitle")}
          message={t("localAi.uninstallRuntimeConfirm")}
          cancelLabel={t("common.cancel")}
          variant="delete"
          pendingLabel={t("localAi.uninstallingRuntime")}
          disabled={isPending("runtime")}
          onCancel={() => setRuntimeUninstallPending(false)}
          onConfirm={() => {
            void (async () => {
              await runAction(
                "runtime",
                async () => {
                  await deleteLocalAIRuntime();
                },
                t("localAi.runtimeDeleteError"),
              );
              if (mountedRef.current) setRuntimeUninstallPending(false);
            })();
          }}
          returnFocusRef={runtimeUninstallButtonRef}
        />
      )}
    </div>
  );
}
