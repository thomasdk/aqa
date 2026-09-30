import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import RoleManager from "./RoleManager";
import type { Role } from "./types";
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

it("renders perspective-management controls and provenance in English", async () => {
  await setLocale("en");
  const { container } = await mountAndWaitForList(makeRole({ origin: "shipped_modified" }));
  expect(container.textContent).toContain("Perspectives");
  const provenance = container.querySelector(".rm-badge--shipped-modified");
  expect(provenance?.textContent).toContain("Changed");
  expect(provenance?.getAttribute("title")).toBe("Bundled default perspective (edited)");
  const tableRegion = container.querySelector<HTMLElement>(".rm-table-scroll");
  expect(tableRegion?.getAttribute("role")).toBe("region");
  expect(tableRegion?.getAttribute("aria-label")).toBe("Perspectives");
  expect(tableRegion?.tabIndex).toBe(0);

  const newButton = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("New Perspective"),
  );
  expect(newButton).toBeDefined();
  await click(newButton!);
  const editor = container.querySelector(".modal-content--editor.rm-modal");
  expect(editor?.querySelector(":scope > .ds-editor-dialog-body.rm-form")).not.toBeNull();
  expect(editor?.querySelector(":scope > .ds-dialog-footer")).not.toBeNull();
  expect(container.querySelector('input[placeholder="e.g. assistant"]')).not.toBeNull();
  expect(container.querySelector('input[placeholder="e.g. Assistant"]')).not.toBeNull();
});

it("shows accessible field-local validation and blocks an invalid perspective ID", async () => {
  const { container } = await mountAndWaitForList(makeRole());
  const newButton = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Neue Perspektive"),
  );
  expect(newButton).toBeDefined();
  await click(newButton!);

  const idInput = container.querySelector<HTMLInputElement>("#perspective-id");
  expect(idInput).not.toBeNull();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(idInput, "Bad ID");
  await act(async () => {
    idInput!.dispatchEvent(new Event("input", { bubbles: true }));
    await Promise.resolve();
  });

  expect(idInput?.getAttribute("aria-invalid")).toBe("true");
  expect(idInput?.getAttribute("aria-describedby")).toBe(
    "perspective-id-hint perspective-id-error",
  );
  expect(container.querySelector("#perspective-id-error")?.textContent).toContain(
    "Eingaben sind ungültig",
  );
  const saveButton = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent === "Speichern",
  ) as HTMLButtonElement;
  expect(saveButton.disabled).toBe(true);
  expect(container.querySelectorAll("table.rm-table tbody tr")).toHaveLength(1);
});

it("associates every perspective field and focuses the first invalid required field", async () => {
  const { container } = await mountAndWaitForList(makeRole());
  const newButton = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Neue Perspektive"),
  )!;
  await click(newButton);

  for (const id of [
    "perspective-id",
    "perspective-label",
    "perspective-description",
    "perspective-role",
    "perspective-task",
    "perspective-output-format",
  ]) {
    expect(container.querySelector(`label[for="${id}"]`)).not.toBeNull();
  }

  const idInput = container.querySelector<HTMLInputElement>("#perspective-id")!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(idInput, "valid_id");
  await act(async () => {
    idInput.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const saveButton = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent === "Speichern",
  ) as HTMLButtonElement;
  await click(saveButton);

  const labelInput = container.querySelector<HTMLInputElement>("#perspective-label")!;
  expect(labelInput.getAttribute("aria-invalid")).toBe("true");
  expect(labelInput.getAttribute("aria-describedby")).toBe("perspective-label-error");
  expect(document.activeElement).toBe(labelInput);
});

it("uses a structured API error code without exposing the raw detail", async () => {
  const fetchMock = makeFetchImpl([
    makeResponse({
      status: 404,
      ok: false,
      textValue: JSON.stringify({
        detail: "Role source at /private/path was not found",
        error: { code: "not_found", params: {} },
      }),
    }),
  ]);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  const { container } = mountIntoContainer(<RoleManager onRolesChanged={() => undefined} />);
  await settle();
  expect(container.textContent).toContain("Die angeforderte Ressource wurde nicht gefunden.");
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

function makeFetchImpl(responses: MockResponse[]) {
  const fetchMock = vi.fn((_input: unknown, _init?: RequestInit) => {
    if (responses.length === 0) {
      return Promise.resolve(makeFetchImplResponse(makeResponse({ status: 200 })));
    }
    const resp = responses.shift()!;
    return Promise.resolve(makeFetchImplResponse(resp));
  });
  return fetchMock;
}

function makeFetchImplResponse(resp: MockResponse): Response {
  return {
    ok: resp.ok,
    status: resp.status,
    text: () => Promise.resolve(resp.textValue),
    json: () => Promise.resolve(resp.jsonValue),
  } as unknown as Response;
}

async function mountAndWaitForList(
  role: Role,
  extraResponses: MockResponse[] = [],
  onRolesChanged: () => void | Promise<void> = () => undefined,
): Promise<{ container: HTMLDivElement; root: Root; fetchMock: ReturnType<typeof vi.fn> }> {
  const fetchMock = makeFetchImpl([makeResponse({ jsonValue: [role] }), ...extraResponses]);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  const { container, root } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
  await settle();
  return { container, root, fetchMock };
}

describe("RoleManager roles-directory reveal", () => {
  it("shows one central roles-folder action and no row-level file actions", async () => {
    const { container } = await mountAndWaitForList(makeRole({ label: "Rolle Alpha" }));
    const button = container.querySelector(
      'button[aria-label="Perspektivenordner öffnen"]',
    ) as HTMLButtonElement | null;
    expect(button).not.toBeNull();
    expect(button?.textContent).toContain("Perspektivenordner öffnen");
    expect(button?.innerHTML).toContain("folder_open");
    expect(container.querySelector(".rm-reveal-btn")).toBeNull();
    expect(container.textContent).not.toContain("Datei anzeigen");
  });

  it("POSTs to the roles-directory endpoint without exposing a path", async () => {
    const { container, fetchMock } = await mountAndWaitForList(makeRole(), [
      makeResponse({ jsonValue: { status: "ok" } }),
    ]);
    const button = container.querySelector(
      'button[aria-label="Perspektivenordner öffnen"]',
    ) as HTMLButtonElement;
    await click(button);
    await settle();

    expect(fetchMock.mock.calls).toHaveLength(2);
    const revealCall = fetchMock.mock.calls[1];
    expect(String(revealCall?.[0])).toMatch(/\/api\/prompts\/roles\/reveal-directory$/);
    expect(String((revealCall?.[1] as RequestInit | undefined)?.method).toUpperCase()).toBe("POST");
    expect(container.textContent).not.toContain(".poml");
  });

  it("shows the localized folder error and re-enables the central action", async () => {
    const { container } = await mountAndWaitForList(makeRole(), [
      makeResponse({ status: 500, ok: false, textValue: "Reveal failed" }),
    ]);
    const button = container.querySelector(
      'button[aria-label="Perspektivenordner öffnen"]',
    ) as HTMLButtonElement;
    await click(button);
    await settle();

    expect(container.querySelector(".error-banner")?.textContent).toContain(
      "Der Perspektivenordner konnte nicht angezeigt werden.",
    );
    expect(button.disabled).toBe(false);
  });
});

describe("RoleManager cross-tab synchronization", () => {
  beforeEach(() => {
    window.confirm = () => true;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function getDeleteButton(container: HTMLElement, label: string): HTMLButtonElement {
    const rows = Array.from(container.querySelectorAll("table.rm-table tbody tr"));
    const target = rows.find((row) => {
      const cells = row.querySelectorAll("td");
      return cells[1]?.textContent?.trim() === label;
    });
    const button = target?.querySelector(
      "button.ds-icon-button--danger",
    ) as HTMLButtonElement | null;
    if (!button) {
      throw new Error(`Delete button for role "${label}" not found`);
    }
    return button;
  }

  function getSingleResetButton(container: HTMLElement, label: string): HTMLButtonElement {
    const button = container.querySelector(
      `button.ds-button--text[aria-label="Standard wiederherstellen — ${label}"]`,
    ) as HTMLButtonElement | null;
    if (!button) {
      throw new Error(`Single-reset button for role "${label}" not found`);
    }
    return button;
  }

  it("calls onRolesChanged after a successful delete and the list is reloaded before the callback", async () => {
    const onRolesChanged = vi.fn(async () => undefined);
    const fetchMock = makeFetchImpl([
      makeResponse({ jsonValue: [makeRole({ id: "alpha", label: "Rolle Alpha" })] }),
      makeResponse({ jsonValue: { status: "ok" } }),
      makeResponse({ jsonValue: [] }),
    ]);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { container } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
    await settle();

    const deleteBtn = getDeleteButton(container, "Rolle Alpha");
    expect(deleteBtn.getAttribute("aria-label")).toBe("Perspektive „Rolle Alpha“ löschen");
    expect(deleteBtn.textContent).toContain("delete");
    await click(deleteBtn);
    expect(container.querySelector('[role="dialog"] h2')?.textContent).toBe("Perspektive löschen?");
    await click(container.querySelector("button.ds-button--dangerPrimary") as HTMLButtonElement);

    await settle();

    expect(fetchMock.mock.calls.length).toBe(3);
    const urls = fetchMock.mock.calls.map((args) => String(args[0]));
    expect(urls[0]).toMatch(/\/api\/prompts\/roles$/);
    expect(urls[0].endsWith("/roles")).toBe(true);
    expect(urls[1]).toMatch(/\/api\/prompts\/roles\/alpha$/);
    const deleteInit = fetchMock.mock.calls[1]?.[1] as RequestInit | undefined;
    expect(String(deleteInit?.method).toUpperCase()).toBe("DELETE");
    expect(urls[2]).toMatch(/\/api\/prompts\/roles$/);
    expect(onRolesChanged).toHaveBeenCalledTimes(1);
    expect(document.activeElement?.textContent).toContain("Neue Perspektive");
    expect(container.querySelector('.visually-hidden[role="status"]')?.textContent).toContain(
      "Perspektive „Rolle Alpha“ gelöscht.",
    );
  });

  it("locks the confirmation while a perspective deletion is pending", async () => {
    let resolveDelete!: (response: Response) => void;
    const pendingDelete = new Promise<Response>((resolve) => {
      resolveDelete = resolve;
    });
    let calls = 0;
    const fetchMock = vi.fn((_input: unknown, init?: RequestInit) => {
      calls += 1;
      if (calls === 1) {
        return Promise.resolve(makeFetchImplResponse(makeResponse({ jsonValue: [makeRole()] })));
      }
      if (init?.method === "DELETE") return pendingDelete;
      return Promise.resolve(makeFetchImplResponse(makeResponse({ jsonValue: [] })));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { container } = mountIntoContainer(<RoleManager onRolesChanged={vi.fn()} />);
    await settle();

    await click(getDeleteButton(container, "Rolle Alpha"));
    const confirm = container.querySelector("button.ds-button--dangerPrimary") as HTMLButtonElement;
    await click(confirm);
    expect(confirm.disabled).toBe(true);
    expect(confirm.getAttribute("aria-busy")).toBe("true");
    expect(confirm.textContent).toBe("Wird gelöscht …");
    confirm.click();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    resolveDelete(makeFetchImplResponse(makeResponse({ jsonValue: { status: "ok" } })));
    await settle();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("does not call onRolesChanged when the delete backend call fails", async () => {
    const onRolesChanged = vi.fn(async () => undefined);
    const fetchMock = makeFetchImpl([
      makeResponse({ jsonValue: [makeRole({ label: "Rolle Alpha" })] }),
      makeResponse({
        status: 500,
        ok: false,
        textValue: "Löschen fehlgeschlagen",
        jsonValue: undefined,
      }),
    ]);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { container } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
    await settle();

    await click(getDeleteButton(container, "Rolle Alpha"));
    await click(container.querySelector("button.ds-button--dangerPrimary") as HTMLButtonElement);
    await settle();

    expect(fetchMock.mock.calls.length).toBe(2);
    expect(onRolesChanged).not.toHaveBeenCalled();
  });

  it.each([
    [
      "de",
      "Diese Perspektive wird von folgenden Sitzungsarten verwendet:",
      "Entfernen oder ersetzen Sie die Referenzen zuerst.",
    ],
    [
      "en",
      "This perspective is used by the following Session Types:",
      "Remove or replace the references first.",
    ],
  ])(
    "shows referenced Session Types accessibly and keeps the role after a dependency conflict (%s)",
    async (locale, expectedPrefix, expectedSuffix) => {
      await setLocale(locale as "de" | "en");
      const onRolesChanged = vi.fn(async () => undefined);
      const fetchMock = makeFetchImpl([
        makeResponse({ jsonValue: [makeRole({ label: "Alpha" })] }),
        makeResponse({
          status: 409,
          ok: false,
          textValue: JSON.stringify({
            detail: "Dependency at /private/session-types/alpha.md",
            error: {
              code: "role_referenced_by_session_types",
              params: {
                session_types: [
                  { key: "zeta_review", label: "Zeta Review" },
                  { key: "alpha_review", label: "Alpha Review" },
                  { key: "unsafe-key", label: "Do not show" },
                  { key: "hidden_review", label: "Hidden\nReview" },
                ],
              },
            },
          }),
        }),
      ]);
      globalThis.fetch = fetchMock as unknown as typeof fetch;
      const { container } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
      await settle();

      await click(getDeleteButton(container, "Alpha"));
      await click(container.querySelector("button.ds-button--dangerPrimary") as HTMLButtonElement);
      await settle();

      const banner = container.querySelector('[role="alert"]') as HTMLElement | null;
      expect(banner).not.toBeNull();
      expect(banner?.textContent).toContain(expectedPrefix);
      expect(banner?.textContent).toContain("Alpha Review (alpha_review)");
      expect(banner?.textContent).toContain("Zeta Review (zeta_review)");
      expect(banner?.textContent).toContain(expectedSuffix);
      expect(banner?.textContent).not.toContain("/private/session-types");
      expect(banner?.textContent).not.toContain("Hidden");
      expect(document.activeElement).toBe(banner);
      expect(container.querySelector('[role="dialog"]')).toBeNull();
      expect(container.querySelectorAll("table.rm-table tbody tr")).toHaveLength(1);
      expect(onRolesChanged).not.toHaveBeenCalled();
    },
  );

  it("preserves the freshly reloaded local table and surfaces the German sync error when the parent callback rejects after a successful delete", async () => {
    const onRolesChanged = vi.fn(async () => {
      throw new Error("Layout refresh failed");
    });
    const fetchMock = makeFetchImpl([
      makeResponse({ jsonValue: [makeRole({ id: "alpha", label: "Rolle Alpha" })] }),
      makeResponse({ jsonValue: { status: "ok" } }),
      makeResponse({ jsonValue: [] }),
    ]);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { container } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
    await settle();

    await click(getDeleteButton(container, "Rolle Alpha"));
    await click(container.querySelector("button.ds-button--dangerPrimary") as HTMLButtonElement);
    await settle();

    expect(container.textContent).toContain("Keine Perspektiven vorhanden.");
    const syncBanner = container.querySelector(".rm-parent-sync-error");
    expect(syncBanner).not.toBeNull();
    expect(syncBanner?.textContent).toContain(
      "Gespeichert; die Setup-Auswahl konnte nicht aktualisiert werden.",
    );
    expect(container.querySelector(".error-banner:not(.rm-parent-sync-error)")).toBeNull();
    expect(onRolesChanged).toHaveBeenCalledTimes(1);
  });

  it("calls onRolesChanged after a successful single restore and surfaces the sync error if it rejects", async () => {
    const onRolesChanged = vi.fn(async () => {
      throw new Error("Layout refresh failed");
    });
    const restoredRole = makeRole({
      id: "alpha",
      label: "Rolle Alpha",
      origin: "shipped_modified",
      is_shipped: true,
    });
    const fetchMock = makeFetchImpl([
      makeResponse({ jsonValue: [restoredRole] }),
      makeResponse({ jsonValue: { restored: ["alpha"] } }),
      makeResponse({ jsonValue: [restoredRole] }),
    ]);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { container } = mountIntoContainer(<RoleManager onRolesChanged={onRolesChanged} />);
    await settle();

    const resetBtn = getSingleResetButton(container, "Rolle Alpha");
    expect(resetBtn.disabled).toBe(false);
    await click(resetBtn);
    await settle();
    const singleResetModal = Array.from(
      container.querySelectorAll(".modal-content.confirm-dialog"),
    ).find((el) => el.textContent?.includes("Standard wiederherstellen"));
    expect(singleResetModal).toBeDefined();
    const confirmSingleReset = singleResetModal?.querySelector(
      "button.ds-button--primary",
    ) as HTMLButtonElement;
    expect(confirmSingleReset).not.toBeNull();
    await click(confirmSingleReset);

    await settle();

    expect(fetchMock.mock.calls.length).toBe(3);
    const singleRestoreCall = fetchMock.mock.calls[1];
    expect(String(singleRestoreCall?.[0])).toMatch(
      /\/api\/prompts\/roles\/alpha\/restore-default$/,
    );
    expect(String((singleRestoreCall?.[1] as RequestInit | undefined)?.method).toUpperCase()).toBe(
      "POST",
    );
    expect(container.querySelector(".rm-parent-sync-error")?.textContent).toContain(
      "Gespeichert; die Setup-Auswahl konnte nicht aktualisiert werden.",
    );
    expect(container.textContent).not.toContain("Standard wiederhergestellt: alpha");
    expect(onRolesChanged).toHaveBeenCalledTimes(1);
  });
});
