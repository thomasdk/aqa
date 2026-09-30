import type {
  LocalAIIntegrity,
  LocalAIModelId,
  LocalAIModelInventory,
  LocalAIState,
  LocalAIStatus,
  LocalAIRuntimeSelection,
} from "./types";

export type LocalAIStartableStatus = Pick<
  { state: LocalAIState; integrity: LocalAIIntegrity },
  "state" | "integrity"
>;

export type DecisionBasisCopy =
  | { kind: "compatible"; text: string }
  | { kind: "cpu-fallback"; text: string }
  | { kind: "unknown"; text: null };

/** Missing decision data remains distinguishable from an incompatible runtime. */
export function describeDecisionBasis(
  basis: LocalAIRuntimeSelection["decision_basis"],
): DecisionBasisCopy {
  if (basis === "detected compatible runtime") {
    return { kind: "compatible", text: "kompatible Laufzeit erkannt" };
  }
  if (basis === "safe CPU fallback") {
    return { kind: "cpu-fallback", text: "sichere CPU-Auswahl" };
  }
  return { kind: "unknown", text: null };
}

export function acceleratorLabel(status: LocalAIStatus | null): string | null {
  return status?.runtime_selection?.accelerator_label ?? null;
}

export function runtimeRationaleState(
  status: LocalAIStatus | null,
): "installed" | "candidate" | null {
  if (!status?.runtime_selection) return null;
  return status.runtime_installed ? "installed" : "candidate";
}

/**
 * A local server may only be started after its artifacts have been verified.
 * Installed, stopped, a cancelled installation, and a failed previous start
 * are idle actions. A failed or cancelled action does not invalidate already
 * verified artifacts, so users can adjust the launch configuration and
 * explicitly try again.
 */
export function canStart(status: LocalAIStartableStatus): boolean {
  return (
    (status.state === "installed" ||
      status.state === "stopped" ||
      status.state === "error" ||
      status.state === "cancelled") &&
    status.integrity === "verified"
  );
}

/**
 * Return the model that Prepare may start automatically.  The managed
 * preference wins, with the model recorded by the idle status as a fallback
 * for a freshly downloaded installation that has not yet registered a host.
 * If either reference is stale or absent, another verified installed model
 * keeps Prepare recoverable.
 */
export function getStartableLocalAIModelId(status: LocalAIStatus | null): LocalAIModelId | null {
  if (!status?.runtime_installed) return null;
  if (!canStart({ state: status.state, integrity: "verified" })) return null;

  const verifiedModels = status.models.filter(
    (model) => model.installed && model.integrity === "verified",
  );
  const preferredModel = verifiedModels.find(
    (model) => model.model_id === status.preferred_model_id,
  );
  const statusModel = verifiedModels.find((model) => model.model_id === status.model_id);

  return preferredModel?.model_id ?? statusModel?.model_id ?? verifiedModels[0]?.model_id ?? null;
}

/** Stable and terminal states stop polling. */
export function nextPollDelay(state: LocalAIState | null): number | null {
  switch (state) {
    case "downloading":
    case "importing":
    case "starting":
    case "cancelling":
      return 500;
    case "running":
    case "sleeping":
      return 2000;
    default:
      return null;
  }
}

/**
 * True when the model files for at least one catalog variant are present and
 * verified enough to start/stop the runtime. This mirrors the backend's
 * integrity heuristic: installed, stopped, running, and sleeping all mean the
 * artifacts exist.
 */
export function isInstalledState(state: LocalAIState | null): boolean {
  return (
    state === "installed" || state === "stopped" || state === "running" || state === "sleeping"
  );
}

export function isServiceState(state: LocalAIState | null): boolean {
  return state === "starting" || state === "running" || state === "sleeping";
}

export type LocalAIOperationKind = NonNullable<LocalAIStatus["operation_kind"]> | null;

export type LocalAIOperationState = NonNullable<LocalAIStatus["operation_state"]> | null;

export function isOperationActive(state: LocalAIOperationState): boolean {
  return state === "downloading" || state === "importing" || state === "cancelling";
}

export function isModelOperation(kind: LocalAIOperationKind): boolean {
  return kind === "model_download" || kind === "model_import";
}

export function isDownloadModel(
  activeModelId: LocalAIModelId | null,
  candidateId: LocalAIModelId,
): boolean {
  return activeModelId === candidateId;
}

/** The managed host preference is the only valid lifecycle start target. */
export type ModelCardAction =
  | { kind: "install" }
  | { kind: "delete" }
  | { kind: "delete-disabled"; reasonKey: "localAi.activeModelDeleteDisabled" };

export type ModelCardVisualState = "active" | "preferred" | "installed" | null;

/**
 * Determine the single primary model-card outline state.
 *
 * Active is the operational state and wins over preferred. Preferred wins
 * over the plain installed outline. Uninstalled models have no primary
 * outline. Callers still render `Bevorzugt`/`Aktiv` badges as secondary cues.
 */
export function getModelCardVisualState({
  isPreferred,
  isActive,
  installed,
}: {
  isPreferred: boolean;
  isActive: boolean;
  installed: boolean;
}): ModelCardVisualState {
  if (!installed) return null;
  if (isActive) return "active";
  if (isPreferred) return "preferred";
  return "installed";
}

/**
 * Offer E4B only after the backend has explicitly confirmed working GPU
 * acceleration and the machine reports enough system memory.
 */
export function shouldInviteE4B(status: LocalAIStatus | null): boolean {
  if (!status?.runtime_installed || (status.ram_gb ?? 0) < 16) return false;
  return status.runtime_selection.acceleration_confirmed === true;
}

/** Model cards manage artifacts only; every model owned by a live lifecycle is protected. */
export function getModelCardAction(
  inventory: LocalAIModelInventory | undefined,
  lifecycleModelId: LocalAIModelId | null,
): ModelCardAction {
  if (!inventory?.installed) return { kind: "install" };
  if (inventory.model_id === lifecycleModelId) {
    return { kind: "delete-disabled", reasonKey: "localAi.activeModelDeleteDisabled" };
  }
  return { kind: "delete" };
}

export type RuntimeUninstallControl =
  | { kind: "enabled" }
  | {
      kind: "disabled";
      reasonKey:
        | "localAi.runtimeNotInstalled"
        | "localAi.stopBeforeRuntimeDelete"
        | "localAi.deleteModelsBeforeRuntime";
    };

export type RuntimeUninstallStatus = Pick<LocalAIStatus, "runtime_installed" | "models"> & {
  /** `null` is preflight, not an active service state. */
  state: LocalAIState | null;
};

/**
 * Mirror the backend removal guard: a live service blocks removal before
 * installed models do because stopping it is the reversible prerequisite.
 */
export function getRuntimeUninstallControl(
  status: RuntimeUninstallStatus,
): RuntimeUninstallControl {
  if (!status.runtime_installed) {
    return { kind: "disabled", reasonKey: "localAi.runtimeNotInstalled" };
  }
  if (isServiceState(status.state)) {
    return { kind: "disabled", reasonKey: "localAi.stopBeforeRuntimeDelete" };
  }
  const hasInstalledModel = status.models.some((entry) => entry.installed);
  if (hasInstalledModel) {
    return { kind: "disabled", reasonKey: "localAi.deleteModelsBeforeRuntime" };
  }
  return { kind: "enabled" };
}
