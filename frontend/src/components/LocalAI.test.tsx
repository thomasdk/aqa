import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createRoot } from "react-dom/client";
import LocalAI, { validContextTokens } from "./LocalAI";
import i18n from "../i18n";
import type { LocalAIStatus } from "./types";
import type { LocalAIDiagnostics } from "./types";

function statusFixture(overrides: Partial<LocalAIStatus> = {}): LocalAIStatus {
  return {
    state: "not_installed",
    model_id: null,
    model_name: null,
    preferred_model_id: null,
    download_bytes: 0,
    download_total: 0,
    context_tokens: 32_768,
    mtp_enabled: false,
    mtp_draft_tokens: 4,
    job_id: null,
    host_ready: false,
    message: null,
    integrity: "unknown",
    os_label: "macOS",
    cpu_label: "Apple M2",
    logical_cpu_count: 8,
    gpu_label: "Metal",
    ram_gb: 16,
    inference_memory_gb: 16,
    inference_memory_kind: "unified",
    runtime_installed: true,
    models: [
      { model_id: "gemma-4-e2b", installed: false, integrity: "unknown" },
      { model_id: "gemma-4-e4b", installed: false, integrity: "unknown" },
      { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
    ],
    runtime_selection: {
      acceleration_confirmed: false,
      runtime_profile: "macos-arm64-metal",
      accelerator_label: "Metal (GPU)",
      engine_name: "llama-server",
      decision_basis: "detected compatible runtime",
      runtime_installed: true,
    },
    ...overrides,
  };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
  } as Response;
}

function installFetch(
  initial: LocalAIStatus,
  delayedStatus?: Promise<LocalAIStatus>,
  runtimeDelete?: Promise<Response>,
  contextTokens = 32_768,
  statusAfterImport?: LocalAIStatus,
  diagnostics: Partial<LocalAIDiagnostics> = {},
) {
  let statusCalls = 0;
  let importRequested = false;
  let savedContextTokens = contextTokens;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/api/local-ai/status")) {
        statusCalls += 1;
        if (delayedStatus && statusCalls > 1) return delayedStatus.then((value) => response(value));
        return Promise.resolve(
          response(importRequested && statusAfterImport ? statusAfterImport : initial),
        );
      }
      if (url.endsWith("/api/local-ai/diagnostics")) return Promise.resolve(response(diagnostics));
      if (url.endsWith("/api/application/preferences")) {
        if (init?.method === "PUT") {
          savedContextTokens =
            JSON.parse(String(init.body)).local_ai_context_tokens ?? savedContextTokens;
        }
        return Promise.resolve(
          response({
            local_ai_context_tokens: savedContextTokens,
            local_ai_context_default_tokens: 32_768,
            local_ai_mtp_enabled: false,
          }),
        );
      }
      if (url.endsWith("/api/local-ai/preferred-model"))
        return Promise.resolve(response({ ok: true }));
      if (url.endsWith("/api/local-ai/models/import-from-directory")) {
        importRequested = true;
        return Promise.resolve(response({ job_id: "job-import", model_id: "gemma-4-e4b" }));
      }
      if (url.endsWith("/api/local-ai/install"))
        return Promise.resolve(response({ job_id: "job-1" }));
      if (url.endsWith("/api/local-ai/runtime") && init?.method === "DELETE") {
        return runtimeDelete ?? Promise.resolve(response(initial));
      }
      return Promise.resolve(response({}));
    }),
  );
  return requests;
}

async function renderLocalAI() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<LocalAI onHostsChanged={vi.fn()} />);
    await Promise.resolve();
    await Promise.resolve();
  });
  return { container, root };
}

function click(element: Element) {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
  void i18n.changeLanguage("de");
});

describe("runtime selection diagnostics", () => {
  const record = {
    version: 1 as const,
    operation: "model_install" as const,
    outcome: "selected" as const,
    selected_profile: "windows-x86_64-cpu",
    attempts: [
      {
        profile: "windows-x86_64-sycl",
        stage: "runtime_preflight" as const,
        result: "rejected" as const,
        reason: "driver_unavailable" as const,
      },
      {
        profile: "windows-x86_64-cpu",
        stage: "model_readiness" as const,
        result: "selected" as const,
      },
    ],
  };

  it("shows ordered historical results, installed difference, and copies only the record", async () => {
    await i18n.changeLanguage("en");
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    installFetch(statusFixture(), undefined, undefined, 32_768, undefined, {
      runtime_selection_diagnostics: { state: "available", record },
      log_tail: ["PRIVATE LOG"],
      command_reference: "PRIVATE COMMAND",
    });
    const { container, root } = await renderLocalAI();
    const section = container.querySelector(".local-ai-selection-diagnostics")!;
    expect(section.textContent).toContain(
      "Results recorded during the last installation or update.",
    );
    expect(section.textContent).toContain("Runtime selected successfully");
    expect(section.textContent).toContain("Currently installed runtime: Metal (macOS ARM64)");
    expect(
      Array.from(section.querySelectorAll("ol > li > span:first-child")).map(
        (node) => node.textContent,
      ),
    ).toEqual(["SYCL (Windows x86-64)", "CPU (Windows x86-64)"]);
    expect(section.textContent).toContain("Runtime check did not pass; candidate rejected.");
    expect(section.textContent).toContain("Model startup check passed; runtime selected.");
    await act(async () => click(section.querySelector("button")!));
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("driver_unavailable");
    expect(copied).not.toContain("PRIVATE");
    expect(copied).not.toContain("macos-arm64-metal");
    expect(section.querySelector('[role="status"]')?.textContent).toContain("Diagnostics copied");
    await act(async () => root.unmount());
  });

  it("presents a successful Metal selection as separate recorded checks", async () => {
    await i18n.changeLanguage("en");
    installFetch(statusFixture(), undefined, undefined, 32_768, undefined, {
      runtime_selection_diagnostics: {
        state: "available",
        record: {
          ...record,
          selected_profile: "macos-arm64-metal",
          attempts: [
            { profile: "macos-arm64-metal", stage: "device_probe", result: "accepted" },
            { profile: "macos-arm64-metal", stage: "model_readiness", result: "selected" },
          ],
        },
      },
    });
    const { container, root } = await renderLocalAI();
    const section = container.querySelector(".local-ai-selection-diagnostics")!;
    expect(section.textContent).toContain("Checked duringModel installation");
    expect(section.textContent).toContain("Selected runtimeMetal (macOS ARM64)");
    expect(
      Array.from(section.querySelectorAll("ol > li > span:nth-child(2)")).map(
        (node) => node.textContent,
      ),
    ).toEqual(["Device check passed.", "Model startup check passed; runtime selected."]);
    await act(async () => root.unmount());
  });

  it("does not call a failed historical selection successful", async () => {
    await i18n.changeLanguage("en");
    installFetch(
      statusFixture({ runtime_installed: false }),
      undefined,
      undefined,
      32_768,
      undefined,
      {
        runtime_selection_diagnostics: {
          state: "available",
          record: {
            ...record,
            operation: "runtime_update",
            outcome: "incomplete",
            selected_profile: null,
            attempts: [
              {
                profile: "windows-x86_64-sycl",
                stage: "runtime_update",
                result: "rejected",
                reason: "runtime_launch_failed",
              },
              {
                profile: "windows-x86_64-vulkan",
                stage: "runtime_update",
                result: "rejected",
                reason: "probe_timeout",
              },
            ],
          },
        },
      },
    );
    const { container, root } = await renderLocalAI();
    const section = container.querySelector(".local-ai-selection-diagnostics")!;
    expect(section.textContent).toContain("No runtime selected in this record");
    expect(section.textContent).not.toContain("Runtime selected successfully");
    expect(section.textContent).toContain("Runtime update attempt failed; candidate rejected.");
    expect(
      Array.from(section.querySelectorAll("ol > li > span:first-child")).map(
        (node) => node.textContent,
      ),
    ).toEqual(["SYCL (Windows x86-64)", "Vulkan (Windows x86-64)"]);
    await act(async () => root.unmount());
  });

  it("disables copy for missing and invalid records and reports a failed copy", async () => {
    await i18n.changeLanguage("en");
    for (const state of ["missing", "invalid"] as const) {
      installFetch(statusFixture(), undefined, undefined, 32_768, undefined, {
        runtime_selection_diagnostics: { state, record: null },
      });
      const { container, root } = await renderLocalAI();
      const section = container.querySelector(".local-ai-selection-diagnostics")!;
      expect((section.querySelector("button") as HTMLButtonElement).disabled).toBe(true);
      expect(section.textContent).toContain(
        state === "missing" ? "No runtime selection diagnostics" : "could not be read",
      );
      await act(async () => root.unmount());
    }
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    installFetch(statusFixture(), undefined, undefined, 32_768, undefined, {
      runtime_selection_diagnostics: { state: "available", record },
    });
    const { container, root } = await renderLocalAI();
    const section = container.querySelector(".local-ai-selection-diagnostics")!;
    await act(async () => click(section.querySelector("button")!));
    expect(section.querySelector('[role="status"]')?.textContent).toContain("could not be copied");
    await act(async () => root.unmount());
  });
});

describe("Integrated AI model cards", () => {
  it("resets the saved context through preferences without restarting a running model", async () => {
    await i18n.changeLanguage("en");
    const requests = installFetch(
      statusFixture({ state: "running", context_tokens: 49_152 }),
      undefined,
      undefined,
      49_152,
    );
    const { container, root } = await renderLocalAI();
    const reset = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Reset Maximum Discussion Context (Tokens) to default"]',
    );
    expect(reset).not.toBeNull();
    await act(async () => click(reset!));
    expect((container.querySelector("#local-ai-context") as HTMLInputElement).value).toBe("32,768");
    expect(document.activeElement).toBe(container.querySelector("#local-ai-context"));
    expect(
      requests.some(
        ({ url, init }) =>
          url.endsWith("/api/application/preferences") &&
          init?.method === "PUT" &&
          String(init.body).includes('"local_ai_context_tokens":32768'),
      ),
    ).toBe(true);
    expect(requests.some(({ url }) => url.endsWith("/api/local-ai/start"))).toBe(false);
    expect(container.textContent).toContain("Restart Integrated AI to apply the saved value.");
    expect(
      container.querySelector(
        'button[aria-label="Reset Maximum Discussion Context (Tokens) to default"]',
      ),
    ).toBeNull();
    await act(async () => root.unmount());
  });
  it("accepts exact integer context bounds without rounding and rejects invalid drafts", () => {
    expect(validContextTokens("8192", 131_072)).toBe(8_192);
    expect(validContextTokens("8193", 131_072)).toBe(8_193);
    expect(validContextTokens("131072", 131_072)).toBe(131_072);
    expect(validContextTokens("262144", 262_144)).toBe(262_144);
    expect(validContextTokens("8,192", 131_072, "en")).toBe(8_192);
    expect(validContextTokens("131,072", 131_072, "en")).toBe(131_072);
    expect(validContextTokens("8.192", 131_072, "de")).toBe(8_192);
    expect(validContextTokens("131.072", 131_072, "de")).toBe(131_072);
    expect(validContextTokens("8,192", 131_072, "de")).toBeNull();
    expect(validContextTokens("8.192", 131_072, "en")).toBeNull();
    for (const draft of ["", "8191", "131073", "8.5", "abc", " 8192", "9007199254740993"]) {
      expect(validContextTokens(draft, 131_072)).toBeNull();
    }
  });
  it("saves a grouped context on blur as an exact number and leaves invalid drafts unsaved", async () => {
    await act(async () => i18n.changeLanguage("en"));
    const requests = installFetch(statusFixture());
    const { container, root } = await renderLocalAI();
    const input = container.querySelector("#local-ai-context") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    const enter = (value: string) => {
      setter.call(input, value);
      act(() => input.dispatchEvent(new Event("input", { bubbles: true })));
    };
    expect(input.value).toBe("32,768");
    act(() => input.focus());
    enter("8,00");
    act(() => input.blur());
    expect(input.value).toBe("8,00");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(requests.some(({ init }) => init?.method === "PUT")).toBe(false);
    act(() => input.focus());
    enter("8,192");
    await act(async () => input.blur());
    expect(input.value).toBe("8,192");
    const writes = requests.filter(
      ({ url, init }) => url.endsWith("/api/application/preferences") && init?.method === "PUT",
    );
    expect(JSON.parse(String(writes[writes.length - 1]?.init?.body)).local_ai_context_tokens).toBe(
      8192,
    );
    await act(async () => root.unmount());
  });
  it("confirms runtime uninstall and locks the dialog while deletion is pending", async () => {
    await i18n.changeLanguage("en");
    let resolveDelete!: (value: Response) => void;
    const pendingDelete = new Promise<Response>((resolve) => {
      resolveDelete = resolve;
    });
    const requests = installFetch(statusFixture(), undefined, pendingDelete);
    const { container, root } = await renderLocalAI();

    const uninstall = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Uninstall Runtime",
    ) as HTMLButtonElement;
    await act(async () => click(uninstall));
    expect(
      requests.filter(
        ({ url, init }) => url.endsWith("/api/local-ai/runtime") && init?.method === "DELETE",
      ),
    ).toHaveLength(0);

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.querySelector("h2")?.textContent).toBe("Uninstall Runtime?");
    const cancel = Array.from(dialog.querySelectorAll("button")).find(
      (button) => button.textContent === "Cancel",
    ) as HTMLButtonElement;
    const confirm = Array.from(dialog.querySelectorAll("button")).find(
      (button) => button.textContent === "Delete",
    ) as HTMLButtonElement;
    expect(document.activeElement).toBe(cancel);

    await act(async () => click(confirm));
    expect(confirm.disabled).toBe(true);
    expect(confirm.getAttribute("aria-busy")).toBe("true");
    expect(confirm.textContent).toBe("Uninstalling …");
    expect(
      requests.filter(
        ({ url, init }) => url.endsWith("/api/local-ai/runtime") && init?.method === "DELETE",
      ),
    ).toHaveLength(1);

    await act(async () => {
      resolveDelete(response(statusFixture({ runtime_installed: false })));
      await pendingDelete;
      await Promise.resolve();
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => root.unmount());
  });

  it("shows all three models in the blank state but disables selection until download", async () => {
    installFetch(statusFixture());
    const { container, root } = await renderLocalAI();

    expect(container.querySelectorAll(".local-ai-model-card")).toHaveLength(3);
    expect(container.textContent).toContain("Gemma 4 E2B");
    expect(container.textContent).toContain("Gemma 4 E4B");
    expect(container.textContent).toContain("Gemma 4 12B");
    const modelChoices = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[name="local-ai-model"]'),
    );
    expect(modelChoices.every((choice) => choice.disabled)).toBe(true);
    expect(modelChoices.every((choice) => !choice.checked)).toBe(true);
    expect(container.querySelector(".local-ai-storage")).toBeNull();

    await act(async () => root.unmount());
  });

  it("explains runtime repair when a verified model remains but the runtime is unavailable", async () => {
    installFetch(
      statusFixture({
        runtime_installed: false,
        runtime_selection: {
          ...statusFixture().runtime_selection,
          runtime_installed: false,
        },
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: false, integrity: "unknown" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
    );
    const { container, root } = await renderLocalAI();

    expect(container.textContent).toContain("Laufzeit installieren");
    expect(container.textContent).toContain(
      "Das Modell ist bereits vorhanden. Öffne die Systemkonfiguration und wähle „Laufzeit installieren“.",
    );
    const e2b = container.querySelector("#local-ai-model-gemma-4-e2b") as HTMLInputElement;
    expect(e2b.disabled).toBe(false);
    expect(e2b.checked).toBe(true);
    expect(e2b.closest(".local-ai-model-card")?.textContent).toContain("Heruntergeladen");
    expect(container.textContent).toContain("Laufzeit installieren");
    expect(container.textContent).toContain("Modelle und Einstellungen bleiben erhalten.");

    await act(async () => root.unmount());
  });

  it("uses the shared blocked-action treatment while the transfer lane is occupied", async () => {
    installFetch(
      statusFixture({
        operation_kind: "model_download",
        operation_state: "downloading",
        operation_model_id: "gemma-4-e4b",
        job_id: "download-e4b",
      }),
    );
    const { container, root } = await renderLocalAI();

    const hint = container.querySelector("#local-ai-transfer-lane-reason");
    expect(hint?.className).toBe("blocked-action-hint");
    expect(hint?.textContent).toContain(
      "Warten Sie, bis die aktuelle Hintergrundaufgabe der integrierten KI abgeschlossen ist",
    );

    await act(async () => root.unmount());
  });

  it("keeps an explicit installed-model selection when a delayed refresh reports another preference", async () => {
    let resolve!: (status: LocalAIStatus) => void;
    const delayed = new Promise<LocalAIStatus>((done) => (resolve = done));
    const requests = installFetch(
      statusFixture({
        preferred_model_id: "gemma-4-e2b",
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
      delayed,
    );
    const { container, root } = await renderLocalAI();

    await act(async () => click(container.querySelector("#local-ai-model-gemma-4-e4b")!));
    resolve(
      statusFixture({
        preferred_model_id: "gemma-4-e4b",
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
    );
    await act(async () => await Promise.resolve());

    const explicitlySelectedModel = container.querySelector(
      "#local-ai-model-gemma-4-e4b",
    ) as HTMLInputElement;
    expect(explicitlySelectedModel.checked).toBe(true);
    expect(explicitlySelectedModel.disabled).toBe(false);
    const preferenceRequest = requests.find(({ url }) =>
      url.endsWith("/api/local-ai/preferred-model"),
    );
    expect(preferenceRequest?.init?.method).toBe("PUT");
    expect(preferenceRequest?.init?.body).toBe(JSON.stringify({ model_id: "gemma-4-e4b" }));
    await act(async () => root.unmount());
  });

  it("keeps models unavailable for generation until they are downloaded", async () => {
    installFetch(
      statusFixture({
        preferred_model_id: "gemma-4-e2b",
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: false, integrity: "unknown" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
    );
    const { container, root } = await renderLocalAI();
    const e2b = container.querySelector("#local-ai-model-gemma-4-e2b") as HTMLInputElement;
    const b12 = container.querySelector("#local-ai-model-gemma-4-12b") as HTMLInputElement;
    expect(e2b.checked).toBe(true);
    expect(e2b.disabled).toBe(false);
    expect(b12.checked).toBe(false);
    expect(b12.disabled).toBe(true);
    await act(async () => click(b12));
    expect(e2b.checked).toBe(true);
    expect(b12.checked).toBe(false);
    await act(async () => root.unmount());
  });

  it("distinguishes downloaded, selected for next start, and running", async () => {
    installFetch(
      statusFixture({
        state: "running",
        model_id: "gemma-4-e2b",
        preferred_model_id: "gemma-4-e4b",
        host_ready: true,
        integrity: "verified",
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
    );
    const { container, root } = await renderLocalAI();

    const e2b = container
      .querySelector("#local-ai-model-gemma-4-e2b")!
      .closest(".local-ai-model-card")!;
    const e4b = container
      .querySelector("#local-ai-model-gemma-4-e4b")!
      .closest(".local-ai-model-card")!;
    expect(e2b.textContent).toContain("Heruntergeladen");
    expect(e2b.textContent).toContain("Läuft");
    expect(e2b.querySelector(".ds-status-badge--info")?.textContent).toBe("Heruntergeladen");
    expect(e2b.querySelector(".ds-status-badge--success")?.textContent).toBe("Läuft");
    expect(e4b.querySelector(".ds-status-badge--info")?.textContent).toBe("Heruntergeladen");
    expect(e4b.querySelector(".ds-status-badge--success")).toBeNull();
    expect((e2b.querySelector('input[type="radio"]') as HTMLInputElement).checked).toBe(false);
    expect((e4b.querySelector('input[type="radio"]') as HTMLInputElement).checked).toBe(true);
    expect(container.querySelector(".sessions-favorite-toggle")).toBeNull();

    await act(async () => root.unmount());
  });

  it("offers one model-detecting folder import instead of one import per card", async () => {
    const requests = installFetch(statusFixture());
    const { container, root } = await renderLocalAI();
    const importButtons = Array.from(container.querySelectorAll("button")).filter(
      (button) => button.textContent === "Aus Ordner importieren",
    );

    expect(importButtons).toHaveLength(1);
    await act(async () => click(importButtons[0]));
    expect(
      requests.some(({ url }) => url.endsWith("/api/local-ai/models/import-from-directory")),
    ).toBe(true);
    const importingModel = container.querySelector(
      "#local-ai-model-gemma-4-e4b",
    ) as HTMLInputElement;
    expect(importingModel.checked).toBe(false);
    expect(importingModel.disabled).toBe(true);

    await act(async () => root.unmount());
  });

  it("replaces completed import progress with the missing-runtime action", async () => {
    await i18n.changeLanguage("en");
    const imported = statusFixture({
      state: "installed",
      runtime_installed: false,
      runtime_selection: { ...statusFixture().runtime_selection, runtime_installed: false },
      preferred_model_id: "gemma-4-e4b",
      models: [
        { model_id: "gemma-4-e2b", installed: false, integrity: "unknown" },
        { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
        { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
      ],
    });
    installFetch(statusFixture(), undefined, undefined, 32_768, imported);
    const { container, root } = await renderLocalAI();
    const importButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Import From Folder",
    );
    await act(async () => click(importButton!));

    expect(container.textContent).toContain(
      "Open System Configuration and choose Install Runtime.",
    );
    expect(container.textContent).not.toContain(
      "The model is being copied from the earlier version",
    );
    expect(container.textContent).toContain("Downloaded");
    await act(async () => root.unmount());
  });

  it.each([
    { ram: null, confirmed: true, runtimeInstalled: true, expected: false },
    { ram: 15, confirmed: true, runtimeInstalled: true, expected: false },
    { ram: 16, confirmed: false, runtimeInstalled: true, expected: false },
    { ram: 16, confirmed: true, runtimeInstalled: false, expected: false },
    { ram: 16, confirmed: true, runtimeInstalled: true, expected: true },
    { ram: 32, confirmed: true, runtimeInstalled: true, expected: true },
  ])(
    "gates the quiet E4B invitation by confirmed acceleration and RAM",
    async ({ ram, confirmed, runtimeInstalled, expected }) => {
      installFetch(
        statusFixture({
          ram_gb: ram,
          runtime_installed: runtimeInstalled,
          runtime_selection: {
            ...statusFixture().runtime_selection,
            acceleration_confirmed: confirmed,
          },
        }),
      );
      const { container, root } = await renderLocalAI();
      const e4b = container
        .querySelector("#local-ai-model-gemma-4-e4b")!
        .closest(".local-ai-model-card")!;
      const b12 = container
        .querySelector("#local-ai-model-gemma-4-12b")!
        .closest(".local-ai-model-card")!;
      expect(e4b.textContent?.includes("Du kannst E4B auf diesem System ausprobieren.")).toBe(
        expected,
      );
      expect(Boolean(e4b.querySelector(".notice-banner--info"))).toBe(expected);
      expect(b12.textContent).not.toContain("Du kannst E4B auf diesem System ausprobieren.");
      await act(async () => root.unmount());
    },
  );

  it.each(["vram", "unified"] as const)(
    "does not apply a VRAM threshold to confirmed %s acceleration",
    async (memoryKind) => {
      installFetch(
        statusFixture({
          ram_gb: 16,
          inference_memory_kind: memoryKind,
          inference_memory_gb: 1,
          runtime_selection: {
            ...statusFixture().runtime_selection,
            acceleration_confirmed: true,
          },
        }),
      );
      const { container, root } = await renderLocalAI();
      expect(container.textContent).toContain("Du kannst E4B auf diesem System ausprobieren.");
      await act(async () => root.unmount());
    },
  );

  it("keeps transfer progress and cancellation inside the affected model card", async () => {
    installFetch(
      statusFixture({
        state: "downloading",
        model_id: "gemma-4-e4b",
        operation_kind: "model_download",
        operation_state: "downloading",
        operation_model_id: "gemma-4-e4b",
        job_id: "job-1",
        download_bytes: 500,
        download_total: 1000,
        download_phase: "main_model",
      }),
    );
    const { container, root } = await renderLocalAI();
    const e4b = container
      .querySelector("#local-ai-model-gemma-4-e4b")!
      .closest(".local-ai-model-card")!;
    expect(container.textContent).toContain("Modell wird heruntergeladen");
    expect(container.textContent).not.toContain("Status der integrierten KI wird geladen");
    expect(e4b.querySelector("progress")).not.toBeNull();
    expect(e4b.textContent).toContain("50 %");
    expect(e4b.textContent).toContain("1,00 KB");
    expect(e4b.textContent).toContain("Abbrechen");
    expect(
      container
        .querySelector("#local-ai-model-gemma-4-e2b")!
        .closest(".local-ai-model-card")!
        .querySelector("progress"),
    ).toBeNull();
    await act(async () => root.unmount());
  });

  it("shows failed transfer retry in the affected card and protects the active model", async () => {
    installFetch(
      statusFixture({
        state: "running",
        model_id: "gemma-4-e2b",
        operation_kind: "model_download",
        operation_state: "error",
        operation_model_id: "gemma-4-e4b",
        error_code: "download_failed",
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: false, integrity: "failed" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
      }),
    );
    const { container, root } = await renderLocalAI();
    const e2b = container
      .querySelector("#local-ai-model-gemma-4-e2b")!
      .closest(".local-ai-model-card")!;
    const e4b = container
      .querySelector("#local-ai-model-gemma-4-e4b")!
      .closest(".local-ai-model-card")!;
    expect(e2b.classList.contains("is-active")).toBe(true);
    expect(e4b.querySelector('[role="alert"]')).not.toBeNull();
    expect(e4b.textContent).toContain("erneut herunterladen");
    expect(e4b.textContent).toContain("Gemma 4 E4B erneut herunterladen");
    expect(e4b.textContent).not.toContain("{{model}}");
    expect((e2b.querySelector(".local-ai-delete-btn") as HTMLButtonElement).disabled).toBe(true);
    expect(e2b.textContent).toContain("Stoppe");
    const deleteButton = e2b.querySelector(".local-ai-delete-btn")!;
    const blockedHint = e2b.querySelector(".blocked-action-hint")!;
    expect(blockedHint.className).toBe("blocked-action-hint");
    expect(blockedHint.getAttribute("role")).toBeNull();
    expect(
      deleteButton.compareDocumentPosition(blockedHint) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    const runtimeHint = container.querySelector("#local-ai-runtime-uninstall-reason")!;
    expect(runtimeHint.classList.contains("blocked-action-hint")).toBe(true);
    expect(runtimeHint.classList.contains("local-ai-runtime-hint")).toBe(true);
    expect(runtimeHint.className).not.toMatch(/blocked-action-hint--/);
    await act(async () => root.unmount());
  });
});
