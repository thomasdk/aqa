import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import PromptConfigurationManager from "./PromptConfigurationManager";
import type { SessionTypeDetail, GlobalBlock, Role } from "./types";
import { setLocale } from "../i18n";

function makeRole(overrides: Partial<Role> = {}): Role {
  return {
    id: "alpha",
    label: "Rolle Alpha",
    role: "Du bist Rolle Alpha.",
    task: "",
    output_format: "",
    editable: true,
    is_shipped: true,
    origin: "shipped_default",
    ...overrides,
  };
}

function makeSessionType(overrides: Partial<SessionTypeDetail> = {}): SessionTypeDetail {
  return {
    key: "default",
    label: "Default",
    description: "Standard-Session-Typ",
    default_agent_prompt_ids: [],
    include_unchanged_research_material_context_in_prompt: false,
    body: "Body",
    inputs: [
      {
        key: "research_question",
        label: "Research question",
        prompt_heading: "Research question",
        required: true,
      },
    ],
    is_shipped: true,
    origin: "shipped_default",
    ...overrides,
  };
}

function makeGlobalBlock(overrides: Partial<GlobalBlock> = {}): GlobalBlock {
  return {
    id: "safety",
    label: "Sicherheitshinweise",
    scope: "immer aktiv",
    content: "Inhalt",
    is_shipped: true,
    origin: "shipped_default",
    ...overrides,
  };
}

const mountedTrees = new Set<{ container: HTMLDivElement; root: Root }>();

function mountIntoContainer(element: React.ReactElement): {
  container: HTMLDivElement;
  root: Root;
} {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(element);
  });
  const mounted = { container, root };
  mountedTrees.add(mounted);
  return mounted;
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await Promise.resolve();
  });
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    element.click();
    await Promise.resolve();
  });
}

afterEach(async () => {
  act(() => {
    for (const mounted of mountedTrees) {
      mounted.root.unmount();
      mounted.container.remove();
    }
  });
  mountedTrees.clear();
  await setLocale("de");
});

it("renders concise configuration headings, folder actions, provenance and form guidance in English", async () => {
  await setLocale("en");
  const { container } = await mountAndWaitForLoad([
    makeResponse({ jsonValue: [makeRole()] }),
    makeResponse({ jsonValue: [makeSessionType({ origin: "shipped_modified" })] }),
    makeResponse({ jsonValue: [makeGlobalBlock()] }),
  ]);
  expect(container.textContent).toContain("Session Types");
  expect(container.textContent).toContain("Open Folder");
  const provenance = container.querySelector(".pcm-badge--shipped-modified");
  expect(provenance?.textContent).toContain("Changed");
  expect(provenance?.getAttribute("title")).toBe("Bundled default configuration (edited)");
  const tableRegions = Array.from(container.querySelectorAll<HTMLElement>(".pcm-table-scroll"));
  expect(tableRegions.map((region) => region.getAttribute("aria-label"))).toEqual([
    "Session Types",
    "Global Prompt Blocks",
  ]);
  expect(tableRegions.every((region) => region.getAttribute("role") === "region")).toBe(true);
  expect(tableRegions.every((region) => region.tabIndex === 0)).toBe(true);

  const newButton = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("New Session Type"),
  );
  expect(newButton).toBeDefined();
  await click(newButton!);
  const sessionEditor = container.querySelector(".modal-content--editor.pcm-modal");
  expect(sessionEditor?.querySelector(":scope > .ds-editor-dialog-body.rm-form")).not.toBeNull();
  expect(sessionEditor?.querySelector(":scope > .ds-dialog-footer")).not.toBeNull();
  expect(container.querySelector('input[placeholder="e.g. coding_interview"]')).not.toBeNull();
  expect(container.textContent).toContain("Lower-case letters, numbers and underscores");
  expect(container.querySelector('label[for="pcm-session-key"]')?.textContent).toContain("ID");
  const saveButton = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent === "Save",
  ) as HTMLButtonElement;
  await click(saveButton);
  const keyInput = container.querySelector<HTMLInputElement>("#pcm-session-key")!;
  expect(keyInput.getAttribute("aria-invalid")).toBe("true");
  expect(keyInput.getAttribute("aria-describedby")).toContain("pcm-session-form-error");
  expect(document.activeElement).toBe(keyInput);
});

it("uses the shared editor body and footer for global prompt blocks", async () => {
  const globalBlock = makeGlobalBlock({ id: "safety", label: "Sicherheitshinweise" });
  const { container } = await mountAndWaitForLoad([
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [globalBlock] }),
  ]);
  const globalRow = Array.from(container.querySelectorAll("tr")).find((row) =>
    row.textContent?.includes("Sicherheitshinweise"),
  );
  const editButton = Array.from(globalRow?.querySelectorAll("button") ?? []).find(
    (button) => button.textContent === "Bearbeiten",
  );
  expect(editButton).toBeDefined();
  await click(editButton!);

  const editor = container.querySelector(".modal-content--editor.pcm-modal");
  expect(editor?.querySelector(":scope > .ds-editor-dialog-body.rm-form")).not.toBeNull();
  expect(editor?.querySelector(":scope > .ds-dialog-footer")).not.toBeNull();
  expect(container.querySelector("#pcm-global-content")).not.toBeNull();
});

it("opens the session-types and global-blocks folders through central path-redacted endpoints", async () => {
  const { container, fetchMock } = await mountAndWaitForLoad([
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [] }),
  ]);

  const sessionTypesFolder = container.querySelector(
    'button[aria-label="Sitzungsartenordner öffnen"]',
  ) as HTMLButtonElement;
  const globalBlocksFolder = container.querySelector(
    'button[aria-label="Prompt-Blöcke-Ordner öffnen"]',
  ) as HTMLButtonElement;
  expect(sessionTypesFolder).not.toBeNull();
  expect(globalBlocksFolder).not.toBeNull();

  await click(sessionTypesFolder);
  await click(globalBlocksFolder);

  const sessionTypesRequest = fetchMock.mock.calls.find(
    ([url]) => String(url) === "/api/prompts/session-types/reveal-directory",
  );
  const globalBlocksRequest = fetchMock.mock.calls.find(
    ([url]) => String(url) === "/api/prompts/globals/reveal-directory",
  );
  expect((sessionTypesRequest?.[1] as RequestInit).method).toBe("POST");
  expect((globalBlocksRequest?.[1] as RequestInit).method).toBe("POST");
});

it("shows and persists the Research Material Context template policy only when a template exists", async () => {
  const session = makeSessionType({
    key: "configured",
    origin: "custom",
    is_shipped: false,
    inputs: [
      {
        key: "research_material_context",
        label: "Research Material Context",
        default_text: "**Case**\nDescribe the case.",
        prompt_heading: "RESEARCH MATERIAL CONTEXT",
        required: false,
      },
      {
        key: "main_input",
        label: "User input",
        prompt_heading: "USER INPUT",
        required: true,
      },
      {
        key: "additional_instructions",
        label: "Additional instructions",
        prompt_heading: "ADDITIONAL USER INSTRUCTIONS",
        required: false,
      },
    ],
  });
  const { container, fetchMock } = await mountAndWaitForLoad([
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [session] }),
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: session }),
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [session] }),
    makeResponse({ jsonValue: [] }),
  ]);

  const row = Array.from(container.querySelectorAll("tr")).find(
    (candidate) => candidate.querySelector("td.pcm-cell-key")?.textContent === "configured",
  );
  const editButton = row?.querySelector("button.ds-button--secondary") as HTMLButtonElement;
  await click(editButton);
  await settle();

  const checkbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
  expect(checkbox).not.toBeNull();
  expect(container.textContent).toContain("Unveränderte Vorlage einbeziehen");
  expect(container.querySelector(".pcm-input-section")).not.toBeNull();
  expect(container.querySelectorAll(".pcm-input-item")).toHaveLength(3);
  expect(container.querySelector(".pcm-input-card")).toBeNull();
  const firstInput = container.querySelector(".pcm-input-item")!;
  const inputLabels = Array.from(firstInput.querySelectorAll(".pcm-input-grid > label"));
  expect(inputLabels[0].classList.contains("pcm-input-full")).toBe(false);
  expect(inputLabels[1].classList.contains("pcm-input-full")).toBe(false);
  expect(inputLabels[2].classList.contains("pcm-input-full")).toBe(true);
  expect(firstInput.querySelector(".pcm-input-key")?.textContent).toBe("research_material_context");
  expect(firstInput.querySelector("strong")?.textContent).toBe("Research Material Context");
  expect(checkbox.closest("label")?.querySelector("small")).toBeNull();
  expect(container.querySelector(".pcm-role-section")).not.toBeNull();
  expect(container.querySelector(".pcm-role-fieldset")).toBeNull();
  const instructions = container.querySelector("#pcm-session-body")!;
  const setupInputs = container.querySelector(".pcm-input-section")!;
  expect(
    instructions.compareDocumentPosition(setupInputs) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  await click(checkbox);
  expect(checkbox.checked).toBe(true);

  const save = Array.from(container.querySelectorAll("button.ds-button--primary")).find(
    (button) => button.textContent === "Speichern",
  ) as HTMLButtonElement;
  await click(save);
  await settle();

  const update = fetchMock.mock.calls.find(
    ([url]) => String(url) === "/api/prompts/session-types/configured",
  );
  expect(JSON.parse(String((update?.[1] as RequestInit).body))).toEqual({
    include_unchanged_research_material_context_in_prompt: true,
  });
});

it("uses a structured API error code without exposing the raw detail", async () => {
  const { container } = await mountAndWaitForLoad([
    makeResponse({
      status: 403,
      ok: false,
      textValue: JSON.stringify({
        detail: "Blocked configuration at /private/path",
        error: { code: "forbidden", params: {} },
      }),
    }),
    makeResponse({ jsonValue: [] }),
    makeResponse({ jsonValue: [] }),
  ]);
  expect(container.textContent).toContain("Diese Aktion ist nicht erlaubt.");
  expect(container.textContent).not.toContain("/private/path");
});

interface MockResponse {
  ok: boolean;
  status: number;
  textValue: string;
  jsonValue: unknown;
}

function makeResponse(resp: Partial<MockResponse> = {}): MockResponse {
  const status = resp.status ?? 200;
  const ok = resp.ok ?? (status >= 200 && status < 300);
  const textValue = resp.textValue ?? JSON.stringify(resp.jsonValue ?? { status: "ok" });
  const jsonValue = resp.jsonValue;
  return { ok, status, textValue, jsonValue };
}

function makeFetchImplResponse(resp: MockResponse): Response {
  return {
    ok: resp.ok,
    status: resp.status,
    text: () => Promise.resolve(resp.textValue),
    json: () => Promise.resolve(resp.jsonValue),
  } as unknown as Response;
}

function makeFetchRouter(responses: MockResponse[]) {
  const fetchMock = vi.fn((_input: unknown) => {
    if (String(_input).includes("/api/quick-actions")) {
      return Promise.resolve(
        makeFetchImplResponse(
          makeResponse({ jsonValue: { actions: [], can_restore_defaults: false } }),
        ),
      );
    }
    if (responses.length === 0) {
      return Promise.resolve(makeFetchImplResponse(makeResponse({ status: 200 })));
    }
    const resp = responses.shift()!;
    return Promise.resolve(makeFetchImplResponse(resp));
  });
  return fetchMock;
}

async function mountAndWaitForLoad(
  responses: MockResponse[],
  onConfigurationChanged: () => void | Promise<void> = () => undefined,
): Promise<{ container: HTMLDivElement; root: Root; fetchMock: ReturnType<typeof vi.fn> }> {
  const fetchMock = makeFetchRouter(responses);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  const { container, root } = mountIntoContainer(
    <PromptConfigurationManager onConfigurationChanged={onConfigurationChanged} />,
  );
  await settle();
  return { container, root, fetchMock };
}

function getSessionDeleteButton(container: HTMLElement, key: string): HTMLButtonElement {
  const buttons = Array.from(container.querySelectorAll("button.ds-icon-button--danger"));
  const target = buttons.find((btn) => {
    const row = btn.closest("tr");
    return row?.querySelector("td.pcm-cell-key")?.textContent?.trim() === key;
  });
  if (!target) {
    throw new Error(`Delete button for session type "${key}" not found`);
  }
  return target as HTMLButtonElement;
}

describe("PromptConfigurationManager cross-tab synchronization", () => {
  beforeEach(() => {
    if (!window.confirm) {
      window.confirm = () => true;
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls onConfigurationChanged after a successful session-type delete and reloads before notifying", async () => {
    const onConfigurationChanged = vi.fn(async () => undefined);
    const customSession = makeSessionType({
      key: "custom_one",
      label: "Custom One",
      origin: "custom",
    });
    const { container, fetchMock } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [customSession] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: { deleted: "custom_one" } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
      ],
      onConfigurationChanged,
    );

    const rowDelete = getSessionDeleteButton(container, "custom_one");
    expect(rowDelete.getAttribute("aria-label")).toBe("Sitzungsart „Custom One“ löschen");
    expect(rowDelete.textContent).toContain("delete");
    await click(rowDelete);
    await settle();
    const confirmModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) => el.textContent?.includes("Sitzungsart löschen?"));
    expect(confirmModal).toBeDefined();
    const confirmDelete = Array.from(confirmModal?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent === "Löschen",
    ) as HTMLButtonElement;
    expect(confirmDelete).not.toBeNull();
    expect(confirmDelete.classList.contains("ds-button--dangerPrimary")).toBe(true);
    expect(document.activeElement?.textContent).toBe("Abbrechen");
    await click(confirmDelete);

    await settle();

    const deleteCall = fetchMock.mock.calls.find((args) =>
      String(args[0]).endsWith("/api/prompts/session-types/custom_one"),
    );
    expect(deleteCall).toBeTruthy();
    expect(String((deleteCall?.[1] as RequestInit | undefined)?.method).toUpperCase()).toBe(
      "DELETE",
    );
    expect(onConfigurationChanged).toHaveBeenCalledTimes(1);
    expect(document.activeElement?.textContent).toContain("Neue Sitzungsart");
    expect(container.querySelector('.visually-hidden[role="status"]')?.textContent).toContain(
      "Sitzungsart „Custom One“ gelöscht.",
    );
  });

  it("does not call onConfigurationChanged when the session-type delete backend call fails", async () => {
    const onConfigurationChanged = vi.fn(async () => undefined);
    const customSession = makeSessionType({
      key: "custom_one",
      label: "Custom One",
      origin: "custom",
    });
    const { container } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [customSession] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({
          status: 500,
          ok: false,
          textValue: "Löschen fehlgeschlagen",
          jsonValue: undefined,
        }),
      ],
      onConfigurationChanged,
    );

    await click(getSessionDeleteButton(container, "custom_one"));
    await settle();
    const confirmModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) => el.textContent?.includes("Sitzungsart löschen?"));
    const confirmDelete = Array.from(confirmModal?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent === "Löschen",
    ) as HTMLButtonElement;
    await click(confirmDelete);

    await settle();

    expect(onConfigurationChanged).not.toHaveBeenCalled();
    const feedback = container.querySelector(".pcm-feedback:not(.pcm-feedback--sync)");
    expect(feedback).not.toBeNull();
    expect(container.querySelector(".pcm-feedback--sync")).toBeNull();
  });

  it("preserves the freshly reloaded local data and surfaces the German sync error when the parent callback rejects after a successful session-type delete", async () => {
    const onConfigurationChanged = vi.fn(async () => {
      throw new Error("Layout refresh failed");
    });
    const customSession = makeSessionType({
      key: "custom_one",
      label: "Custom One",
      origin: "custom",
    });
    const { container } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [customSession] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: { deleted: "custom_one" } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
      ],
      onConfigurationChanged,
    );

    await click(getSessionDeleteButton(container, "custom_one"));
    await settle();
    const confirmModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) => el.textContent?.includes("Sitzungsart löschen?"));
    const confirmDelete = Array.from(confirmModal?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent === "Löschen",
    ) as HTMLButtonElement;
    await click(confirmDelete);

    await settle();

    expect(container.textContent).toContain("Noch keine Sitzungsarten vorhanden.");
    const syncFeedback = container.querySelector(".pcm-feedback--sync");
    expect(syncFeedback).not.toBeNull();
    expect(syncFeedback?.textContent).toContain(
      "Gespeichert; die Setup-Auswahl konnte nicht aktualisiert werden.",
    );
    expect(container.querySelector(".pcm-feedback:not(.pcm-feedback--sync)")).toBeNull();
    expect(onConfigurationChanged).toHaveBeenCalledTimes(1);
  });

  it("removes bulk reset controls while retaining per-row restores and user-facing scopes", async () => {
    const { container } = await mountAndWaitForLoad([
      makeResponse({ jsonValue: [] }),
      makeResponse({
        jsonValue: [makeSessionType({ key: "shipped_mod", origin: "shipped_modified" })],
      }),
      makeResponse({
        jsonValue: [
          makeGlobalBlock({ scope: "multi_agent", origin: "shipped_modified" }),
          makeGlobalBlock({ id: "always", scope: null, origin: "shipped_modified" }),
        ],
      }),
    ]);

    expect(
      container.querySelectorAll(".pcm-section:not(.qam-section) .ds-button--text"),
    ).toHaveLength(3);
    expect(container.textContent).toContain("Standard wiederherstellen");
    expect(container.textContent).toContain("Mehrere Perspektiven");
    expect(container.textContent).toContain("Immer aktiv");
    expect(container.textContent).not.toContain("multi_agent");
    expect(container.textContent).not.toContain("Alle mitgelieferten Standard-Sitzungsarten");
    expect(container.textContent).not.toContain("Alle mitgelieferten Standard-Globalblöcke");
  });

  it("calls onConfigurationChanged after a successful single global-block restore", async () => {
    const onConfigurationChanged = vi.fn(async () => undefined);
    const shippedModGlobal = makeGlobalBlock({
      id: "safety",
      label: "Sicherheitshinweise (mod)",
      origin: "shipped_modified",
    });
    const { container, fetchMock } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [shippedModGlobal] }),
        makeResponse({ jsonValue: { restored: ["safety"] } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [shippedModGlobal] }),
      ],
      onConfigurationChanged,
    );

    const resetButton = container.querySelector(
      'button.ds-button--text[aria-label="Standard wiederherstellen — Sicherheitshinweise (mod)"]',
    ) as HTMLButtonElement;
    expect(resetButton).not.toBeNull();
    expect(resetButton.disabled).toBe(false);
    await click(resetButton);
    await settle();

    const singleRestoreModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) =>
      el.textContent?.includes("Andere und eigene Konfigurationen bleiben unverändert"),
    );
    expect(singleRestoreModal).toBeDefined();
    const confirmSingleRestore = singleRestoreModal?.querySelector(
      "button.ds-button--primary",
    ) as HTMLButtonElement;
    expect(confirmSingleRestore).not.toBeNull();
    await click(confirmSingleRestore);

    await settle();

    const restoreCall = fetchMock.mock.calls.find((args) =>
      String(args[0]).endsWith("/api/prompts/globals/safety/restore-default"),
    );
    expect(restoreCall).toBeTruthy();
    expect(String((restoreCall?.[1] as RequestInit | undefined)?.method).toUpperCase()).toBe(
      "POST",
    );
    expect(onConfigurationChanged).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".pcm-form-success")).toBeNull();
  });

  it("preserves local data and surfaces the German sync error when the parent callback rejects after a successful single global restore", async () => {
    const onConfigurationChanged = vi.fn(async () => {
      throw new Error("Layout refresh failed");
    });
    const shippedModGlobal = makeGlobalBlock({ id: "safety", origin: "shipped_modified" });
    const { container } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [shippedModGlobal] }),
        makeResponse({ jsonValue: { restored: ["safety"] } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [makeGlobalBlock({ id: "safety", origin: "shipped_default" })] }),
      ],
      onConfigurationChanged,
    );

    const restoreButton = container.querySelector("button.ds-button--text") as HTMLButtonElement;
    expect(restoreButton).not.toBeNull();
    await click(restoreButton);
    await settle();
    const restoreModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) =>
      el.textContent?.includes("Andere und eigene Konfigurationen bleiben unverändert"),
    );
    expect(restoreModal).toBeDefined();
    const confirmRestore = restoreModal?.querySelector(
      "button.ds-button--primary",
    ) as HTMLButtonElement;
    expect(confirmRestore).not.toBeNull();
    await click(confirmRestore);

    await settle();

    expect(container.textContent).toContain("Sicherheitshinweise");
    const syncFeedback = container.querySelector(".pcm-feedback--sync");
    expect(syncFeedback).not.toBeNull();
    expect(syncFeedback?.textContent).toContain(
      "Gespeichert; die Setup-Auswahl konnte nicht aktualisiert werden.",
    );
    expect(container.querySelector(".pcm-feedback:not(.pcm-feedback--sync)")).toBeNull();
    expect(onConfigurationChanged).toHaveBeenCalledTimes(1);
  });

  it("clears the German sync error after a subsequent successful parent callback", async () => {
    let shouldReject = true;
    const onConfigurationChanged = vi.fn(async () => {
      if (shouldReject) {
        shouldReject = false;
        throw new Error("Layout refresh failed");
      }
    });
    const customSession = makeSessionType({
      key: "custom_one",
      label: "Custom One",
      origin: "custom",
    });
    const shippedModGlobal = makeGlobalBlock({ id: "safety", origin: "shipped_modified" });
    const { container } = await mountAndWaitForLoad(
      [
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [customSession] }),
        makeResponse({ jsonValue: [shippedModGlobal] }),
        makeResponse({ jsonValue: { deleted: "custom_one" } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [shippedModGlobal] }),
        makeResponse({ jsonValue: { restored: ["safety"] } }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [] }),
        makeResponse({ jsonValue: [makeGlobalBlock({ id: "safety", origin: "shipped_default" })] }),
      ],
      onConfigurationChanged,
    );

    await click(getSessionDeleteButton(container, "custom_one"));
    await settle();
    const confirmModal1 = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) => el.textContent?.includes("Sitzungsart löschen?"));
    const confirmDelete1 = Array.from(confirmModal1?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent === "Löschen",
    ) as HTMLButtonElement;
    await click(confirmDelete1);

    await settle();
    expect(container.querySelector(".pcm-feedback--sync")).not.toBeNull();
    expect(onConfigurationChanged).toHaveBeenCalledTimes(1);

    const restoreButton = container.querySelector("button.ds-button--text") as HTMLButtonElement;
    expect(restoreButton).not.toBeNull();
    await click(restoreButton);
    await settle();
    const restoreModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) =>
      el.textContent?.includes("Andere und eigene Konfigurationen bleiben unverändert"),
    );
    const confirmRestore = restoreModal?.querySelector(
      "button.ds-button--primary",
    ) as HTMLButtonElement;
    expect(confirmRestore).not.toBeNull();
    await click(confirmRestore);

    await settle();

    expect(onConfigurationChanged).toHaveBeenCalledTimes(2);
    expect(container.querySelector(".pcm-feedback--sync")).toBeNull();
  });
});
