import { afterEach, describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import NetworkConfig, { type HostDraftDependencies } from "./NetworkConfig";
import type { HostInfo } from "../api";
import i18n from "../i18n";

type Mounted = { container: HTMLDivElement; root: Root };

function response(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

function errorResponse(code: string, status = 409): Response {
  const body = { error: { code, params: {} } };
  return {
    ok: false,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
} {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

function mount(
  props: {
    onHostsChanged?: () => void | Promise<void>;
    getDraftDependencies?: (host: HostInfo) => HostDraftDependencies;
  } = {},
): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(createElement(NetworkConfig, props)));
  return { container, root };
}

function change(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  act(() => input.dispatchEvent(new Event("input", { bubbles: true })));
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("NetworkConfig model editor", () => {
  it("uses the shared editor shell with one direct body and a fixed footer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/hosts" ? Promise.resolve(response([])) : Promise.resolve(response({})),
      ),
    );
    const mounted = mount();
    try {
      await settle();
      act(() =>
        (mounted.container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();

      const editor = mounted.container.querySelector<HTMLElement>(
        ".nc-modal.modal-content--editor",
      );
      expect(editor).not.toBeNull();
      expect(editor?.querySelector(":scope > .ds-editor-dialog-body.nc-form")).not.toBeNull();
      expect(editor?.querySelector(":scope > .ds-dialog-footer.nc-modal-actions")).not.toBeNull();
      expect(editor?.querySelector(".nc-model-rows .ds-editor-dialog-body")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("toggles the preferred external host from the list without opening the editor", async () => {
    let preferred = false;
    const host = () => ({
      configuration_id: "Remote",
      label: "Remote",
      url: "http://remote",
      model: "alpha",
      models: ["alpha"],
      kind: null,
      has_api_key: false,
      is_favorite: preferred,
      model_context_tokens: {},
    });
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts" && !init) return Promise.resolve(response([host()]));
      if (url === "/api/hosts/0" && init?.method === "PUT") {
        preferred = Boolean(JSON.parse(String(init.body)).is_favorite);
        return Promise.resolve(response(host()));
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onHostsChanged = vi.fn();
    const mounted = mount({ onHostsChanged });
    try {
      await settle();
      const preference = mounted.container.querySelector<HTMLButtonElement>(
        "button.nc-host-preference-toggle",
      )!;
      expect(preference.getAttribute("aria-pressed")).toBe("false");
      expect(preference.getAttribute("aria-label")).toContain("Remote");
      act(() => preference.click());
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ configuration_id: "Remote", is_favorite: true }),
        }),
      );
      expect(
        mounted.container
          .querySelector("button.nc-host-preference-toggle")
          ?.getAttribute("aria-pressed"),
      ).toBe("true");
      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
      expect(onHostsChanged).toHaveBeenCalledOnce();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("keeps invalid URL feedback inside the dialog and does not submit it", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/hosts") return Promise.resolve(response([]));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        (mounted.container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();
      const urlInput = mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!;
      change(urlInput, "not a URL");
      const saveButton = Array.from(mounted.container.querySelectorAll("button")).find(
        (button) => button.textContent === "Speichern",
      ) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(false);
      act(() => saveButton.click());
      await settle();
      expect(mounted.container.querySelector('[role="dialog"]')).not.toBeNull();
      expect(mounted.container.querySelector(".network-config > .error-banner")).toBeNull();
      expect(fetchMock).not.toHaveBeenCalledWith(
        "/api/hosts",
        expect.objectContaining({ method: "POST" }),
      );
      expect(mounted.container.querySelector("#nc-host-url-error")?.textContent).toContain(
        "gültige URL",
      );
      expect(document.activeElement).toBe(urlInput);
      expect(fetchMock).not.toHaveBeenCalledWith("/api/hosts/test-connection", expect.anything());
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses the concise empty External AI guidance", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/hosts" ? Promise.resolve(response([])) : Promise.resolve(response({})),
      ),
    );
    const mounted = mount();
    try {
      await settle();
      expect(mounted.container.querySelector(".nc-empty")?.textContent).toBe(
        "Einen Host hinzufügen, um externe KI-Dienste zu nutzen.",
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("discloses host-test and discussion transmission without exposing a credential", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/hosts" ? Promise.resolve(response([])) : Promise.resolve(response({})),
      ),
    );
    const mounted = mount();
    try {
      await settle();
      act(() =>
        (mounted.container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();
      const disclosure = mounted.container.querySelector(".nc-connection-disclosure");
      expect(disclosure?.textContent).toContain("Verbindungstest kontaktiert");
      expect(disclosure?.textContent).toContain("API-Schlüssel");
      expect(disclosure?.textContent).toContain("Diskussion ausgewählten Inhalte");
      expect(disclosure?.textContent).not.toContain("secret");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses concise model-editor labels and the Integrated AI examples", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/hosts" ? Promise.resolve(response([])) : Promise.resolve(response({})),
      ),
    );
    const mounted = mount();
    try {
      await settle();
      act(() =>
        (mounted.container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();

      const modelInput = mounted.container.querySelector<HTMLInputElement>("#nc-model-id-0")!;
      const contextInput =
        mounted.container.querySelector<HTMLInputElement>("#nc-model-context-0")!;
      expect(mounted.container.querySelector('label[for="nc-model-id-0"]')?.textContent).toBe(
        "Modell-ID",
      );
      expect(modelInput.getAttribute("aria-label")).toBe("Modell-ID 1");
      expect(mounted.container.querySelector('label[for="nc-model-context-0"]')?.textContent).toBe(
        "Maximales Kontextfenster (optional)",
      );
      expect(modelInput.placeholder).toBe("z.B. gemma-4-26B-A4B-it");
      expect(contextInput.placeholder).toBe("z.B. 32.768");
      expect(mounted.container.textContent).not.toContain("vorausgewählt");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("saves an optional context window for each external model", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "http://remote",
              model: "model-a",
              models: ["model-a"],
              kind: null,
              has_api_key: false,
              is_favorite: false,
              model_context_tokens: {},
            },
          ]),
        );
      if (url === "/api/hosts/0" && init?.method === "PUT") return Promise.resolve(response({}));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      const contextInput = mounted.container.querySelector<HTMLInputElement>(
        'input[aria-label="Maximales Kontextfenster für Modell 1 (optional)"]',
      )!;
      change(contextInput, "32768");
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Speichern")!
          .click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            configuration_id: "Remote",
            model_context_tokens: { "model-a": 32768 },
          }),
        }),
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it.each([
    ["en", "32,768"],
    ["de", "32.768"],
  ])("saves %s grouped context as an exact numeric API value", async (language, grouped) => {
    await act(async () => i18n.changeLanguage(language));
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts") return Promise.resolve(response([]));
      if (url === "/api/hosts" && init?.method === "POST") return Promise.resolve(response({}));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container, root } = mount();
    try {
      await settle();
      act(() =>
        (container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();
      change(container.querySelector("#nc-host-label") as HTMLInputElement, "Synthetic");
      change(
        container.querySelector("#nc-host-url") as HTMLInputElement,
        "https://example.invalid",
      );
      change(container.querySelector("#nc-model-id-0") as HTMLInputElement, "model-a");
      const input = container.querySelector("#nc-model-context-0") as HTMLInputElement;
      change(input, grouped);
      expect(input.value).toBe(grouped);
      const save = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === (language === "de" ? "Speichern" : "Save"),
      )!;
      act(() => save.click());
      await settle();
      const post = fetchMock.mock.calls.find(
        ([url, init]) => url === "/api/hosts" && init?.method === "POST",
      );
      expect(JSON.parse(String(post?.[1]?.body)).model_context_tokens).toEqual({
        "model-a": 32768,
      });
    } finally {
      act(() => root.unmount());
      await act(async () => i18n.changeLanguage("de"));
    }
  });

  it("keeps malformed and ambiguous external drafts visible without changing the saved limit", async () => {
    await act(async () => i18n.changeLanguage("en"));
    const host = {
      configuration_id: "Remote",
      label: "Remote",
      url: "https://example.invalid",
      model: "model-a",
      models: ["model-a"],
      kind: null,
      has_api_key: false,
      is_favorite: false,
      model_context_tokens: { "model-a": 8192 },
    };
    const fetchMock = vi.fn((url: string, _init?: RequestInit) =>
      Promise.resolve(response(url === "/api/hosts" ? [host] : {})),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container, root } = mount();
    try {
      await settle();
      expect(container.textContent).toContain("8,192 tokens");
      act(() =>
        Array.from(container.querySelectorAll("button"))
          .find((button) => button.textContent === "Edit")!
          .click(),
      );
      await settle();
      const input = container.querySelector("#nc-model-context-0") as HTMLInputElement;
      expect(input.value).toBe("8,192");
      change(input, "8.192");
      expect(input.value).toBe("8.192");
      expect(input.getAttribute("aria-invalid")).toBe("true");
      const save = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "Save",
      )!;
      act(() => save.click());
      await settle();
      expect(document.activeElement).toBe(input);
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
      change(input, "8193");
      act(() => save.click());
      await settle();
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
      expect(JSON.parse(String(put?.[1]?.body)).model_context_tokens).toEqual({ "model-a": 8193 });
    } finally {
      act(() => root.unmount());
      await act(async () => i18n.changeLanguage("de"));
    }
  });

  it("keeps the model input focused while its value changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/hosts")
          return Promise.resolve(
            response([
              {
                configuration_id: "Remote",
                label: "Remote",
                url: "http://remote",
                model: "old",
                models: ["old"],
                kind: null,
                has_api_key: false,
                is_favorite: false,
              },
            ]),
          );
        if (url === "/api/hosts/0/key") return Promise.resolve(response({ api_key: "" }));
        return Promise.resolve(response({}));
      }),
    );
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      const input = mounted.container.querySelector<HTMLInputElement>(
        'input[aria-label="Modell-ID 1"]',
      )!;
      input.focus();
      change(input, "o");
      expect(document.activeElement).toBe(input);
      change(input, "old-model");
      expect(document.activeElement).toBe(input);
      expect(input.value).toBe("old-model");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("shows only external hosts and retains their original API indices", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Lokale KI",
              label: "Integrierte KI",
              url: "http://127.0.0.1:8080",
              model: "gemma-4-E2B-it",
              models: ["gemma-4-E2B-it", "gemma-4-E4B-it"],
              kind: "local_ai",
              has_api_key: false,
              is_favorite: false,
            },
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "https://remote.example/v1",
              model: "remote-model",
              models: ["remote-model"],
              kind: null,
              has_api_key: true,
              is_favorite: true,
            },
          ]),
        );
      if (url === "/api/hosts/1/test")
        return Promise.resolve(
          response({ ok: true, message: "connection_established", models: ["remote-model"] }),
        );
      if (url === "/api/hosts/delete-preview" && init?.method === "POST")
        return Promise.resolve(
          response({
            label: "Remote",
            revision: "rev-1",
            is_preferred: false,
            credential_will_be_removed: true,
            saved_sessions: [],
          }),
        );
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      expect(mounted.container.textContent).toContain("Remote");
      expect(mounted.container.textContent).not.toContain("127.0.0.1:8080");
      expect(mounted.container.textContent).not.toContain("Integrierte KI zurücksetzen");
      const deleteButton = mounted.container.querySelector(
        "button.ds-icon-button--danger",
      ) as HTMLButtonElement;
      expect(deleteButton.getAttribute("aria-label")).toBe("Host „Remote“ löschen");
      expect(deleteButton.textContent).toContain("delete");
      act(() => deleteButton.click());
      await settle();
      expect(mounted.container.querySelector('[role="dialog"] h2')?.textContent).toBe(
        "Host löschen?",
      );
      const calmImpact = mounted.container.querySelector(".nc-delete-impact");
      expect(calmImpact?.textContent).toContain("gegebenenfalls gespeicherter API-Schlüssel");
      expect(calmImpact?.querySelector("ul")).toBeNull();
      expect(calmImpact?.querySelector(".nc-delete-summary")).toBeNull();
      expect(calmImpact?.textContent).not.toContain("Vor dem Löschen");
      expect(calmImpact?.textContent).toContain("Bei bestehenden Diskussionen");
      expect(calmImpact?.textContent).toContain("bisherige Verläufe und Anbieterangaben");
      expect(calmImpact?.textContent).toContain("neu konfiguriert");
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Abbrechen")!
          .click(),
      );
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      expect(mounted.container.textContent).toContain("Host bearbeiten: Remote");
      act(() =>
        (
          mounted.container.querySelector("button.nc-test-connection-btn") as HTMLButtonElement
        ).click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith("/api/hosts/1/test", expect.anything());
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("resolves an edited host by stable identity after the host list is reordered", async () => {
    const alpha = {
      configuration_id: "Alpha",
      label: "Alpha",
      url: "https://alpha.example/v1",
      model: "alpha-model",
      models: ["alpha-model"],
      kind: null,
      has_api_key: false,
      is_favorite: false,
    };
    const beta = {
      configuration_id: "Beta",
      label: "Beta",
      url: "https://beta.example/v1",
      model: "beta-model",
      models: ["beta-model"],
      kind: null,
      has_api_key: false,
      is_favorite: false,
    };
    let list = [alpha, beta];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts" && !init) return Promise.resolve(response(list));
      if (url === "/api/hosts/0" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        if (payload.is_favorite === true) {
          list = [beta, { ...alpha, is_favorite: true }];
        }
        return Promise.resolve(response({}));
      }
      if (url === "/api/hosts/1" && init?.method === "PUT") {
        return Promise.resolve(response({}));
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      const editButtons = Array.from(
        mounted.container.querySelectorAll<HTMLButtonElement>("button"),
      ).filter((button) => button.textContent === "Bearbeiten");
      act(() => editButtons[1].click());
      await settle();

      const backgroundPreference = mounted.container.querySelector<HTMLButtonElement>(
        "button.nc-host-preference-toggle",
      )!;
      act(() => backgroundPreference.click());
      await settle();
      expect(mounted.container.textContent).toContain("Host bearbeiten: Beta");

      change(mounted.container.querySelector<HTMLInputElement>("#nc-host-label")!, "Beta neu");
      act(() =>
        Array.from(mounted.container.querySelectorAll<HTMLButtonElement>("button"))
          .find((button) => button.textContent === "Speichern")!
          .click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ configuration_id: "Beta", label: "Beta neu" }),
        }),
      );
      expect(fetchMock).not.toHaveBeenCalledWith(
        "/api/hosts/1",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ label: "Beta neu" }),
        }),
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("shows one concise warning without dependency details and Cancel preserves the host", async () => {
    const host = {
      configuration_id: "Remote",
      label: "Remote",
      url: "https://remote.example/v1",
      model: "remote-model",
      models: ["remote-model"],
      kind: null,
      has_api_key: true,
      is_favorite: true,
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts") return Promise.resolve(response([host]));
      if (url === "/api/hosts/delete-preview" && init?.method === "POST") {
        return Promise.resolve(
          response({
            label: host.label,
            revision: "stable-revision",
            is_preferred: true,
            credential_will_be_removed: true,
            saved_sessions: [{ file_id: "session-1", title: "Saved Analysis" }],
          }),
        );
      }
      if (url === "/api/hosts/delete" && init?.method === "POST") {
        return Promise.resolve(
          response({ deleted: true, label: host.label, credential_removed: true }),
        );
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onHostsChanged = vi.fn();
    const mounted = mount({
      onHostsChanged,
      getDraftDependencies: () => ({
        defaultAssignments: ["Perspective 1"],
        explicitAssignments: ["Perspective 2"],
        defaultSynthesis: false,
        explicitSynthesis: true,
      }),
    });
    try {
      await settle();
      act(() =>
        mounted.container.querySelector<HTMLButtonElement>(".ds-icon-button--danger")!.click(),
      );
      await settle();
      const impact = mounted.container.querySelector(".nc-delete-impact")?.textContent ?? "";
      expect(impact).not.toContain("Perspective 1");
      expect(impact).not.toContain("Perspective 2");
      expect(impact).not.toContain("Saved Analysis");
      expect(impact).toContain("API-Schlüssel");
      expect(impact).toContain("„Aktivität“ > „Optionen“");
      expect(mounted.container.querySelector(".nc-delete-summary")).toBeNull();
      expect(impact).not.toContain("Vor dem Löschen");
      expect(impact).toContain("Bei bestehenden Diskussionen");
      expect(impact).not.toContain("stable-revision");
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Abbrechen")!
          .click(),
      );
      expect(fetchMock).not.toHaveBeenCalledWith(
        "/api/hosts/delete",
        expect.objectContaining({ method: "POST" }),
      );
      expect(mounted.container.textContent).toContain("Remote");

      act(() =>
        mounted.container.querySelector<HTMLButtonElement>(".ds-icon-button--danger")!.click(),
      );
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Löschen")!
          .click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/delete",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ label: "Remote", revision: "stable-revision" }),
        }),
      );
      expect(onHostsChanged).toHaveBeenCalledOnce();
      expect(document.activeElement?.textContent).toContain("Hinzufügen");
      expect(
        mounted.container.querySelector('.visually-hidden[role="status"]')?.textContent,
      ).toContain("Host „Remote“ gelöscht.");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("ignores an older deletion preview that finishes after a newer selection", async () => {
    const firstPreview = deferred<Response>();
    const secondPreview = deferred<Response>();
    const hosts = [
      {
        configuration_id: "Alpha",
        label: "Alpha",
        url: "https://alpha.example/v1",
        model: "alpha",
        models: ["alpha"],
        kind: null,
        has_api_key: false,
        is_favorite: false,
      },
      {
        configuration_id: "Beta",
        label: "Beta",
        url: "https://beta.example/v1",
        model: "beta",
        models: ["beta"],
        kind: null,
        has_api_key: false,
        is_favorite: false,
      },
    ];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts") return Promise.resolve(response(hosts));
      if (url === "/api/hosts/delete-preview") {
        const label = JSON.parse(String(init?.body)).label;
        return label === "Alpha" ? firstPreview.promise : secondPreview.promise;
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      const deleteButtons = mounted.container.querySelectorAll<HTMLButtonElement>(
        "button.ds-icon-button--danger",
      );
      act(() => {
        deleteButtons[0].click();
        deleteButtons[1].click();
      });
      secondPreview.resolve(
        response({
          label: "Beta",
          revision: "beta-revision",
          is_preferred: false,
          credential_will_be_removed: false,
          saved_sessions: [],
        }),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-delete-impact")?.textContent).toContain("Beta");

      firstPreview.resolve(
        response({
          label: "Alpha",
          revision: "alpha-revision",
          is_preferred: false,
          credential_will_be_removed: false,
          saved_sessions: [],
        }),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-delete-impact")?.textContent).toContain("Beta");
      expect(mounted.container.querySelector(".nc-delete-impact")?.textContent).not.toContain(
        "Alpha",
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("refreshes changed hosts and draft dependencies before a conflict retry", async () => {
    let deleteAttempts = 0;
    let previewAttempts = 0;
    const host = {
      configuration_id: "Remote",
      label: "Remote",
      url: "https://remote.example/v1",
      model: "remote-model",
      models: ["remote-model"],
      kind: null,
      has_api_key: false,
      is_favorite: false,
    };
    let currentHost = host;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts") return Promise.resolve(response([currentHost]));
      if (url === "/api/hosts/delete-preview") {
        previewAttempts += 1;
        return Promise.resolve(
          response({
            label: host.label,
            revision: `revision-${previewAttempts}`,
            is_preferred: false,
            credential_will_be_removed: false,
            saved_sessions: [],
          }),
        );
      }
      if (url === "/api/hosts/delete" && init?.method === "POST") {
        deleteAttempts += 1;
        if (deleteAttempts === 1) {
          currentHost = { ...host, url: "https://changed.example/v1" };
        }
        return Promise.resolve(
          deleteAttempts === 1
            ? errorResponse("host_catalog_changed")
            : response({ deleted: true, label: host.label, credential_removed: false }),
        );
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onHostsChanged = vi.fn();
    const mounted = mount({
      onHostsChanged,
      getDraftDependencies: (selected) => ({
        defaultAssignments: [
          selected.url.includes("changed") ? "Changed Assignment" : "Original Assignment",
        ],
        explicitAssignments: [],
        defaultSynthesis: false,
        explicitSynthesis: false,
      }),
    });
    try {
      await settle();
      act(() =>
        mounted.container.querySelector<HTMLButtonElement>(".ds-icon-button--danger")!.click(),
      );
      await settle();
      const confirm = () =>
        Array.from(mounted.container.querySelectorAll<HTMLButtonElement>("button")).find(
          (button) => button.textContent === "Löschen",
        )!;
      act(() => confirm().click());
      await settle();
      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
      expect(mounted.container.querySelector(".error-banner")?.textContent).toContain(
        "Host-Konfiguration hat sich geändert",
      );
      expect(onHostsChanged).toHaveBeenCalledOnce();
      act(() =>
        mounted.container.querySelector<HTMLButtonElement>(".ds-icon-button--danger")!.click(),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-delete-impact")?.textContent).not.toContain(
        "Changed Assignment",
      );
      act(() => confirm().click());
      await settle();
      expect(deleteAttempts).toBe(2);
      const deleteCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/hosts/delete");
      expect(JSON.parse(String(deleteCalls[1]?.[1]?.body))).toEqual({
        label: "Remote",
        revision: "revision-2",
      });
      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("tests a draft host and shows the reported model IDs before saving", async () => {
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url === "/api/hosts") return Promise.resolve(response([]));
      if (url === "/api/hosts/test-connection")
        return Promise.resolve(
          response({
            ok: true,
            code: "connection_established",
            message: "Connection established",
            models: ["gpt-4o", "gpt-4o-mini"],
          }),
        );
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        (mounted.container.querySelector("button.ds-button--primary") as HTMLButtonElement).click(),
      );
      await settle();
      const urlInput = mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!;
      expect(
        mounted.container.querySelector(".nc-connection-section.nc-editor-card"),
      ).not.toBeNull();
      expect(mounted.container.querySelectorAll(".nc-model-row.nc-editor-card")).toHaveLength(1);
      expect(
        mounted.container.querySelector<HTMLInputElement>('input[placeholder="z.B. LM Studio"]'),
      ).not.toBeNull();
      expect(urlInput.placeholder).toBe("http://localhost:1234/v1");
      change(urlInput, "https://api.example/v1");
      act(() =>
        (
          mounted.container.querySelector("button.nc-test-connection-btn") as HTMLButtonElement
        ).click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/test-connection",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ url: "https://api.example/v1", api_key: null }),
        }),
      );
      expect(mounted.container.querySelector(".nc-test-model-list")?.textContent).toContain(
        "gpt-4o",
      );
      expect(mounted.container.querySelector(".nc-test-model-list")?.textContent).toContain(
        "gpt-4o-mini",
      );
      expect(mounted.container.querySelector<HTMLElement>(".nc-test-model-list")?.tabIndex).toBe(0);
      expect(mounted.container.querySelector(".nc-test-result")?.getAttribute("role")).toBe(
        "status",
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("discards a pending connection result when the tested draft changes", async () => {
    const testResponse = deferred<Response>();
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/hosts") return Promise.resolve(response([]));
      if (url === "/api/hosts/test-connection") return testResponse.promise;
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        mounted.container.querySelector<HTMLButtonElement>("button.ds-button--primary")!.click(),
      );
      await settle();
      const urlInput = mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!;
      change(urlInput, "https://first.example/v1");
      act(() =>
        mounted.container
          .querySelector<HTMLButtonElement>("button.nc-test-connection-btn")!
          .click(),
      );
      await settle();
      expect(
        mounted.container
          .querySelector<HTMLButtonElement>("button.nc-test-connection-btn")!
          .getAttribute("aria-busy"),
      ).toBe("true");

      change(urlInput, "https://second.example/v1");
      expect(mounted.container.querySelector(".nc-test-result")).toBeNull();
      testResponse.resolve(
        response({
          ok: true,
          code: "connection_established",
          message: "ok",
          models: ["stale-model"],
        }),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-test-result")).toBeNull();
      expect(
        mounted.container
          .querySelector<HTMLButtonElement>("button.nc-test-connection-btn")!
          .getAttribute("aria-busy"),
      ).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("closes the editor while a connection test is pending and ignores its completion", async () => {
    const testResponse = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/hosts") return Promise.resolve(response([]));
        if (url === "/api/hosts/test-connection") return testResponse.promise;
        return Promise.resolve(response({}));
      }),
    );
    const mounted = mount();
    try {
      await settle();
      const addButton = mounted.container.querySelector<HTMLButtonElement>(
        "button.ds-button--primary",
      )!;
      addButton.focus();
      act(() => addButton.click());
      await settle();
      change(
        mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!,
        "https://example.test/v1",
      );
      act(() =>
        mounted.container
          .querySelector<HTMLButtonElement>("button.nc-test-connection-btn")!
          .click(),
      );
      await settle();
      const cancel = Array.from(
        mounted.container.querySelectorAll<HTMLButtonElement>("button"),
      ).find((button) => button.textContent === "Abbrechen")!;
      expect(cancel.disabled).toBe(false);
      act(() => cancel.click());
      await settle();
      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
      expect(document.activeElement).toBe(addButton);

      testResponse.resolve(
        response({ ok: true, code: "connection_established", message: "ok", models: ["late"] }),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-test-result")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("identifies and focuses missing label and model fields on save", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/hosts" ? Promise.resolve(response([])) : Promise.resolve(response({})),
      ),
    );
    const mounted = mount();
    try {
      await settle();
      act(() =>
        mounted.container.querySelector<HTMLButtonElement>("button.ds-button--primary")!.click(),
      );
      await settle();
      change(
        mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!,
        "https://example.test/v1",
      );
      const save = Array.from(mounted.container.querySelectorAll<HTMLButtonElement>("button")).find(
        (button) => button.textContent === "Speichern",
      )!;
      act(() => save.click());
      await settle();
      const labelInput = mounted.container.querySelector<HTMLInputElement>("#nc-host-label")!;
      expect(labelInput.getAttribute("aria-invalid")).toBe("true");
      expect(labelInput.getAttribute("aria-describedby")).toContain("nc-host-label-error");
      expect(document.activeElement).toBe(labelInput);

      change(labelInput, "Remote");
      act(() => save.click());
      await settle();
      const modelInput = mounted.container.querySelector<HTMLInputElement>("#nc-model-id-0")!;
      expect(modelInput.getAttribute("aria-invalid")).toBe("true");
      expect(modelInput.getAttribute("aria-describedby")).toContain("nc-model-id-error");
      expect(document.activeElement).toBe(modelInput);
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("tests an edited URL with the draft key without saving the edit", async () => {
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "https://saved.example/v1",
              model: "remote-model",
              models: ["remote-model"],
              kind: null,
              has_api_key: true,
              is_favorite: false,
            },
          ]),
        );
      if (url === "/api/hosts/0/test")
        return Promise.resolve(
          response({ ok: true, code: "connection_established", message: "ok", models: ["live"] }),
        );
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      const urlInput = mounted.container.querySelector<HTMLInputElement>("#nc-host-url")!;
      change(urlInput, "https://draft.example/v1");
      act(() =>
        (
          mounted.container.querySelector("button.nc-test-connection-btn") as HTMLButtonElement
        ).click(),
      );
      await settle();

      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0/test",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            configuration_id: "Remote",
            url: "https://draft.example/v1",
            api_key: null,
          }),
        }),
      );
      expect(fetchMock).not.toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({ method: "PUT" }),
      );
      expect(mounted.container.textContent).toContain("Verbindung hergestellt");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("keeps a custom model ID when discovery advertises different models", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "https://provider.example/v1",
              model: "@preset/custom-fast",
              models: ["@preset/custom-fast"],
              kind: null,
              has_api_key: true,
              is_favorite: false,
            },
          ]),
        );
      if (url === "/api/hosts/0/test")
        return Promise.resolve(
          response({
            ok: true,
            code: "connection_established",
            message: "ok",
            models: ["catalogued-model"],
          }),
        );
      if (url === "/api/hosts/0" && init?.method === "PUT") return Promise.resolve(response({}));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      const modelInput = mounted.container.querySelector<HTMLInputElement>("#nc-model-id-0")!;
      expect(modelInput.value).toBe("@preset/custom-fast");

      act(() =>
        (
          mounted.container.querySelector("button.nc-test-connection-btn") as HTMLButtonElement
        ).click(),
      );
      await settle();
      expect(mounted.container.querySelector(".nc-test-model-list")?.textContent).toContain(
        "catalogued-model",
      );
      expect(modelInput.value).toBe("@preset/custom-fast");

      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Speichern")!
          .click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ configuration_id: "Remote" }),
        }),
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses the session star treatment to choose a different default model", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "http://remote",
              model: "alpha",
              models: ["alpha", "beta"],
              kind: null,
              has_api_key: false,
              is_favorite: false,
              model_context_tokens: {},
            },
          ]),
        );
      if (url === "/api/hosts/0" && init?.method === "PUT") return Promise.resolve(response({}));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();
      const preferenceButton = mounted.container.querySelector(
        "button.nc-model-preference-toggle",
      ) as HTMLButtonElement;
      expect(preferenceButton.getAttribute("aria-pressed")).toBe("false");
      const defaultStatus = mounted.container.querySelector(
        ".nc-model-preference-status",
      ) as HTMLSpanElement;
      expect(defaultStatus.getAttribute("aria-label")).toBe("Standardmodell");
      expect(defaultStatus.getAttribute("title")).toBe("Standardmodell");
      expect(defaultStatus.textContent).toBe("star");
      expect(defaultStatus.querySelector(".favorite-star.is-active")).not.toBeNull();
      act(() => preferenceButton.click());
      expect(mounted.container.querySelectorAll(".nc-model-preference-status")).toHaveLength(1);
      expect(mounted.container.querySelectorAll(".nc-model-preference-toggle")).toHaveLength(1);
      expect(mounted.container.querySelector<HTMLInputElement>("#nc-model-id-1")!.value).toBe(
        "beta",
      );
      expect(
        mounted.container
          .querySelector("#nc-model-id-1")!
          .closest(".nc-model-row")!
          .querySelector(".nc-model-preference-status"),
      ).not.toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses accessible trash controls for saved keys and model rows", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/hosts")
        return Promise.resolve(
          response([
            {
              configuration_id: "Remote",
              label: "Remote",
              url: "http://remote",
              model: "alpha",
              models: ["alpha", "beta"],
              kind: null,
              has_api_key: true,
              is_favorite: false,
              model_context_tokens: {},
            },
          ]),
        );
      if (url === "/api/hosts/0" && init?.method === "PUT") return Promise.resolve(response({}));
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount();
    try {
      await settle();
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Bearbeiten")!
          .click(),
      );
      await settle();

      const clearKeyButton = mounted.container.querySelector(
        "button.nc-clear-key-control",
      ) as HTMLButtonElement;
      expect(clearKeyButton.getAttribute("aria-label")).toBe(
        "Gespeicherten API-Schlüssel entfernen",
      );
      expect(clearKeyButton.getAttribute("data-tooltip")).toBe(
        "Gespeicherten API-Schlüssel entfernen",
      );
      expect(clearKeyButton.textContent).toBe("delete");

      const removeModelButtons = mounted.container.querySelectorAll<HTMLButtonElement>(
        "button.nc-model-remove-btn",
      );
      expect(removeModelButtons).toHaveLength(2);
      expect(removeModelButtons[0].getAttribute("aria-label")).toBe("Modell 1 entfernen");
      expect(removeModelButtons[0].getAttribute("data-tooltip")).toBe("Modell 1 entfernen");
      expect(removeModelButtons[0].textContent).toBe("delete");

      act(() => clearKeyButton.click());
      expect(clearKeyButton.disabled).toBe(true);
      act(() =>
        Array.from(mounted.container.querySelectorAll("button"))
          .find((button) => button.textContent === "Speichern")!
          .click(),
      );
      await settle();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hosts/0",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ configuration_id: "Remote", api_key: null }),
        }),
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses the external-host empty state when only Integrated AI is configured", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/hosts") {
          return Promise.resolve(
            response([
              {
                configuration_id: "Lokale KI",
                label: "Integrierte KI",
                url: "http://127.0.0.1:8080",
                model: "gemma-4-E2B-it",
                models: ["gemma-4-E2B-it"],
                kind: "local_ai",
                has_api_key: false,
                is_favorite: false,
              },
            ]),
          );
        }
        return Promise.resolve(response({}));
      }),
    );
    const mounted = mount();
    try {
      await settle();
      expect(mounted.container.querySelector(".nc-empty")).not.toBeNull();
      expect(mounted.container.querySelector(".nc-table")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });
});
