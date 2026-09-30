import { describe, expect, it } from "vitest";
import {
  acceleratorLabel,
  describeDecisionBasis,
  runtimeRationaleState,
  canStart,
  getStartableLocalAIModelId,
  nextPollDelay,
  isInstalledState,
  isModelOperation,
  isOperationActive,
  isServiceState,
  isDownloadModel,
  getModelCardAction,
  getModelCardVisualState,
  getRuntimeUninstallControl,
  shouldInviteE4B,
} from "./localAIState";
import type { LocalAIModelInventory, LocalAIStatus } from "./types";

describe("Local AI state helpers", () => {
  it("allows start only after a verified installation is inactive", () => {
    expect(canStart({ state: "installed", integrity: "verified" })).toBe(true);
    expect(canStart({ state: "error", integrity: "verified" })).toBe(true);
    expect(canStart({ state: "cancelled", integrity: "verified" })).toBe(true);
    expect(canStart({ state: "downloading", integrity: "unknown" })).toBe(false);
  });

  it("polls active jobs but not stable idle state", () => {
    expect(nextPollDelay("downloading")).toBe(500);
    expect(nextPollDelay("running")).toBe(2000);
    expect(nextPollDelay("not_installed")).toBeNull();
  });

  it("does not allow starting a running or unverified installation", () => {
    expect(canStart({ state: "running", integrity: "verified" })).toBe(false);
    expect(canStart({ state: "installed", integrity: "unknown" })).toBe(false);
    expect(canStart({ state: "stopped", integrity: "verified" })).toBe(true);
    expect(canStart({ state: "error", integrity: "unknown" })).toBe(false);
    expect(canStart({ state: "error", integrity: "failed" })).toBe(false);
  });

  it("lets Prepare start the verified preferred model when its runtime is installed", () => {
    const idleStatus = {
      state: "installed",
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "verified" }],
    } as LocalAIStatus;

    expect(getStartableLocalAIModelId(idleStatus)).toBe("gemma-4-e2b");
    expect(getStartableLocalAIModelId({ ...idleStatus, runtime_installed: false })).toBeNull();
    expect(
      getStartableLocalAIModelId({
        ...idleStatus,
        models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "failed" }],
      }),
    ).toBeNull();
  });

  it("falls back from a missing or unusable preference to another verified installed model", () => {
    const idleStatus = {
      state: "stopped",
      model_id: "gemma-4-e4b",
      preferred_model_id: null,
      integrity: "verified",
      runtime_installed: true,
      models: [
        { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
        { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
        { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
      ],
    } as LocalAIStatus;

    expect(getStartableLocalAIModelId(idleStatus)).toBe("gemma-4-e4b");
    expect(
      getStartableLocalAIModelId({
        ...idleStatus,
        preferred_model_id: "gemma-4-12b",
      }),
    ).toBe("gemma-4-e4b");
    expect(
      getStartableLocalAIModelId({
        ...idleStatus,
        model_id: null,
        preferred_model_id: "gemma-4-12b",
      }),
    ).toBe("gemma-4-e2b");
  });

  it("never falls back to an installed model whose integrity is not verified", () => {
    const idleStatus = {
      state: "installed",
      model_id: "gemma-4-e4b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      models: [
        { model_id: "gemma-4-e2b", installed: true, integrity: "failed" },
        { model_id: "gemma-4-e4b", installed: true, integrity: "unknown" },
      ],
    } as LocalAIStatus;

    expect(getStartableLocalAIModelId(idleStatus)).toBeNull();
  });

  it("polls while starting or sleeping and stops polling terminal states", () => {
    expect(nextPollDelay("starting")).toBe(500);
    expect(nextPollDelay("cancelling")).toBe(500);
    expect(nextPollDelay("sleeping")).toBe(2000);
    expect(nextPollDelay("stopped")).toBeNull();
    expect(nextPollDelay("error")).toBeNull();
  });
});

describe("unified UI state predicates", () => {
  it("treats installed, stopped, running and sleeping as installed states", () => {
    expect(isInstalledState("installed")).toBe(true);
    expect(isInstalledState("stopped")).toBe(true);
    expect(isInstalledState("running")).toBe(true);
    expect(isInstalledState("sleeping")).toBe(true);
    expect(isInstalledState("not_installed")).toBe(false);
    expect(isInstalledState("downloading")).toBe(false);
    expect(isInstalledState("starting")).toBe(false);
    expect(isInstalledState("error")).toBe(false);
    expect(isInstalledState(null)).toBe(false);
  });

  it("treats starting, running and sleeping as service states", () => {
    expect(isServiceState("starting")).toBe(true);
    expect(isServiceState("running")).toBe(true);
    expect(isServiceState("sleeping")).toBe(true);
    expect(isServiceState("installed")).toBe(false);
    expect(isServiceState("stopped")).toBe(false);
    expect(isServiceState("not_installed")).toBe(false);
    expect(isServiceState("downloading")).toBe(false);
    expect(isServiceState("error")).toBe(false);
    expect(isServiceState(null)).toBe(false);
  });

  it("keeps the operation lane distinct from the service lifecycle", () => {
    expect(isOperationActive("downloading")).toBe(true);
    expect(isOperationActive("importing")).toBe(true);
    expect(isOperationActive("cancelling")).toBe(true);
    expect(isOperationActive("error")).toBe(false);
    expect(isOperationActive(null)).toBe(false);
    expect(isModelOperation("model_download")).toBe(true);
    expect(isModelOperation("model_import")).toBe(true);
    expect(isModelOperation("runtime_update")).toBe(false);
    expect(isModelOperation(null)).toBe(false);
  });

  it("uses id equality to match a download model", () => {
    expect(isDownloadModel("gemma-4-e2b", "gemma-4-e2b")).toBe(true);
    expect(isDownloadModel("gemma-4-e2b", "gemma-4-e4b")).toBe(false);
    expect(isDownloadModel(null, "gemma-4-e2b")).toBe(false);
  });
});

describe("service-first Local AI controls", () => {
  const verifiedE2B: LocalAIModelInventory = {
    model_id: "gemma-4-e2b",
    installed: true,
    integrity: "verified",
  };

  it("limits model cards to artifact actions and protects a starting lifecycle model", () => {
    expect(getModelCardAction(undefined, "gemma-4-e2b")).toEqual({ kind: "install" });
    expect(getModelCardAction(verifiedE2B, "gemma-4-e4b")).toEqual({ kind: "delete" });
    expect(getModelCardAction(verifiedE2B, "gemma-4-e2b")).toEqual({
      kind: "delete-disabled",
      reasonKey: "localAi.activeModelDeleteDisabled",
    });
  });

  it("gives active outline priority when a card is both active and preferred", () => {
    expect(getModelCardVisualState({ isPreferred: true, isActive: true, installed: true })).toBe(
      "active",
    );
  });

  it("uses preferred outline only when preferred but inactive", () => {
    expect(getModelCardVisualState({ isPreferred: true, isActive: false, installed: true })).toBe(
      "preferred",
    );
  });

  it("falls back to installed outline when installed but neither active nor preferred", () => {
    expect(getModelCardVisualState({ isPreferred: false, isActive: false, installed: true })).toBe(
      "installed",
    );
  });

  it("has no primary outline when the model is not installed", () => {
    expect(
      getModelCardVisualState({ isPreferred: true, isActive: false, installed: false }),
    ).toBeNull();
    expect(
      getModelCardVisualState({ isPreferred: true, isActive: true, installed: false }),
    ).toBeNull();
    expect(
      getModelCardVisualState({ isPreferred: false, isActive: false, installed: false }),
    ).toBeNull();
  });
});

describe("runtime uninstall control", () => {
  it("keeps uninstall visible and explains when no runtime is installed", () => {
    expect(
      getRuntimeUninstallControl({ runtime_installed: false, state: "stopped", models: [] }),
    ).toEqual({ kind: "disabled", reasonKey: "localAi.runtimeNotInstalled" });
    expect(
      getRuntimeUninstallControl({ runtime_installed: false, state: "not_installed", models: [] }),
    ).toEqual({ kind: "disabled", reasonKey: "localAi.runtimeNotInstalled" });
  });

  it("enables the button when the runtime is installed, the service is stopped, and no models are installed", () => {
    const control = getRuntimeUninstallControl({
      runtime_installed: true,
      state: "stopped",
      models: [],
    });
    expect(control).toEqual({ kind: "enabled" });
  });

  it("treats the verified-installed idle state as a safe moment to uninstall", () => {
    const control = getRuntimeUninstallControl({
      runtime_installed: true,
      state: "installed",
      models: [],
    });
    expect(control).toEqual({ kind: "enabled" });
  });

  it("disables the button with a stop-service hint when the service is starting, running, or sleeping", () => {
    const expected = { kind: "disabled", reasonKey: "localAi.stopBeforeRuntimeDelete" } as const;
    expect(
      getRuntimeUninstallControl({ runtime_installed: true, state: "starting", models: [] }),
    ).toEqual(expected);
    expect(
      getRuntimeUninstallControl({ runtime_installed: true, state: "running", models: [] }),
    ).toEqual(expected);
    expect(
      getRuntimeUninstallControl({ runtime_installed: true, state: "sleeping", models: [] }),
    ).toEqual(expected);
  });

  it("disables the button with a delete-models hint when at least one model is installed", () => {
    const expected = { kind: "disabled", reasonKey: "localAi.deleteModelsBeforeRuntime" } as const;
    expect(
      getRuntimeUninstallControl({
        runtime_installed: true,
        state: "stopped",
        models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "verified" }],
      }),
    ).toEqual(expected);
    expect(
      getRuntimeUninstallControl({
        runtime_installed: true,
        state: "installed",
        models: [
          { model_id: "gemma-4-e2b", installed: false, integrity: "unknown" },
          { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
        ],
      }),
    ).toEqual(expected);
  });

  it("prefers the stop-service hint when both service and models are blocking the uninstall", () => {
    const control = getRuntimeUninstallControl({
      runtime_installed: true,
      state: "running",
      models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "verified" }],
    });
    expect(control).toEqual({ kind: "disabled", reasonKey: "localAi.stopBeforeRuntimeDelete" });
  });
});

describe("runtime selection rationale", () => {
  const baseStatus: LocalAIStatus = {
    state: "not_installed",
    model_id: null,
    model_name: null,
    download_bytes: 0,
    download_total: 0,
    context_tokens: null,
    host_ready: false,
    message: null,
    integrity: "unknown",
    models: [],
    runtime_selection: {
      acceleration_confirmed: false,
      runtime_profile: "macos-arm64-metal",
      accelerator_label: "Metal",
      engine_name: "llama-server",
      decision_basis: "detected compatible runtime",
    },
  };

  it("translates the decision basis to localised German copy", () => {
    expect(describeDecisionBasis("detected compatible runtime")).toEqual({
      kind: "compatible",
      text: "kompatible Laufzeit erkannt",
    });
    expect(describeDecisionBasis("safe CPU fallback")).toEqual({
      kind: "cpu-fallback",
      text: "sichere CPU-Auswahl",
    });
    expect(describeDecisionBasis(null)).toEqual({ kind: "unknown", text: null });
  });

  it("uses the accelerator label from the runtime selection", () => {
    const status: LocalAIStatus = {
      ...baseStatus,
      runtime_selection: {
        acceleration_confirmed: false,
        runtime_profile: "windows-x86_64-cpu",
        accelerator_label: "CPU",
        engine_name: "llama-server.exe",
        decision_basis: "safe CPU fallback",
      },
    };
    expect(acceleratorLabel(status)).toBe("CPU");
  });

  it("reports the installed-vs-candidate rationale state for the UI", () => {
    expect(runtimeRationaleState(baseStatus)).toBe("candidate");
    expect(runtimeRationaleState({ ...baseStatus, runtime_installed: true })).toBe("installed");
    expect(runtimeRationaleState(null)).toBeNull();
  });

  it("keeps candidate rationale separate from verified installed wording", () => {
    expect(runtimeRationaleState(baseStatus)).toBe("candidate");
    expect(runtimeRationaleState({ ...baseStatus, runtime_installed: true })).toBe("installed");
  });
});

describe("E4B invitation", () => {
  const base = {
    runtime_installed: true,
    ram_gb: 16,
    runtime_selection: {
      acceleration_confirmed: true,
      runtime_profile: "macos-arm64-metal",
      accelerator_label: "Metal (GPU)",
      engine_name: "llama-server",
      decision_basis: "detected compatible runtime",
      runtime_installed: true,
    },
  } as LocalAIStatus;

  it("requires at least 16 GB RAM and explicit working GPU confirmation", () => {
    expect(shouldInviteE4B(base)).toBe(true);
    expect(shouldInviteE4B({ ...base, ram_gb: 15 })).toBe(false);
    expect(
      shouldInviteE4B({
        ...base,
        runtime_selection: { ...base.runtime_selection, acceleration_confirmed: false },
      }),
    ).toBe(false);
  });

  it("stays quiet for planned or missing runtime data", () => {
    expect(shouldInviteE4B({ ...base, runtime_installed: false })).toBe(false);
    expect(shouldInviteE4B({ ...base, ram_gb: null })).toBe(false);
    expect(shouldInviteE4B(null)).toBe(false);
  });
});
