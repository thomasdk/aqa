import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { setLocale } from "../i18n";
import SessionsTab from "./SessionsTab";
import type { SessionSummary } from "./types";

type Mounted = { container: HTMLDivElement; root: Root };

const session: SessionSummary = {
  file_id: "alpha",
  title: "Alpha",
  created: "2026-07-31T10:00:00.000Z",
  updated: "2026-07-31T10:00:00.000Z",
  round_count: 2,
  session_type: "exploration",
  is_open: false,
  is_favorite: false,
};

function response(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
  } as Response;
}

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await Promise.resolve();
  });
}

function mount(
  onActiveSessionDeleted = vi.fn(),
  externalNotice: string | null = null,
  onMutationStart = vi.fn(),
  onNoticeDismiss = vi.fn(),
  onOpen: (fileId: string) => void | Promise<void> = () => undefined,
): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <SessionsTab
        onOpen={onOpen}
        onActiveSessionDeleted={onActiveSessionDeleted}
        externalNotice={externalNotice}
        onMutationStart={onMutationStart}
        onNoticeDismiss={onNoticeDismiss}
      />,
    );
  });
  return { container, root };
}

afterEach(async () => {
  vi.useRealTimers();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  await setLocale("de");
});

describe("SessionsTab actions", () => {
  it("guards a pending open request and exposes its busy state", async () => {
    await setLocale("en");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response([session]))),
    );
    let resolveOpen!: () => void;
    const pendingOpen = new Promise<void>((resolve) => {
      resolveOpen = resolve;
    });
    const onOpen = vi.fn(() => pendingOpen);
    const mounted = mount(vi.fn(), null, vi.fn(), vi.fn(), onOpen);
    try {
      await settle();
      const open = mounted.container.querySelector(".sessions-action-open") as HTMLButtonElement;
      expect(open.classList.contains("ds-button--primary")).toBe(true);
      act(() => {
        open.click();
        open.click();
      });
      expect(onOpen).toHaveBeenCalledOnce();
      expect(open.disabled).toBe(true);
      expect(open.getAttribute("aria-busy")).toBe("true");
      expect(open.textContent).toBe("Opening …");

      await act(async () => {
        resolveOpen();
        await pendingOpen;
      });
      await settle();
      expect(
        mounted.container.querySelector(".sessions-action-open")?.getAttribute("aria-busy"),
      ).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("dismisses an external notice through its parent callback", async () => {
    await setLocale("en");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response([session]))),
    );
    const onNoticeDismiss = vi.fn();
    const mounted = mount(vi.fn(), "Session “Alpha” opened.", vi.fn(), onNoticeDismiss);
    try {
      await settle();
      const close = mounted.container.querySelector<HTMLButtonElement>(
        'button[aria-label="Close Notice"]',
      );
      expect(close).not.toBeNull();
      act(() => close?.click());
      expect(onNoticeDismiss).toHaveBeenCalledOnce();
      expect(mounted.container.querySelector(".sessions-notice")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses the same parent-clearing path when an external notice expires", async () => {
    await setLocale("en");
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response([session]))),
    );
    const onNoticeDismiss = vi.fn();
    const mounted = mount(vi.fn(), "Session “Alpha” opened.", vi.fn(), onNoticeDismiss);
    try {
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(mounted.container.querySelector(".sessions-notice")).not.toBeNull();
      act(() => vi.advanceTimersByTime(4000));
      expect(onNoticeDismiss).toHaveBeenCalledOnce();
      expect(mounted.container.querySelector(".sessions-notice")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("replaces an obsolete opened notice with one localized deletion failure", async () => {
    await setLocale("en");
    const onMutationStart = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url === "/api/sessions" && !init) return Promise.resolve(response([session]));
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () =>
            Promise.resolve(
              JSON.stringify({
                detail: "bounded",
                error: { code: "session_deletion_failed", params: {} },
              }),
            ),
        } as Response);
      }),
    );
    const mounted = mount(vi.fn(), "Session “Alpha” opened.", onMutationStart);
    try {
      await settle();
      expect(mounted.container.textContent).toContain("opened");
      const deleteRow = mounted.container.querySelector(
        'button.sessions-action-delete[aria-label="Delete"]',
      ) as HTMLButtonElement;
      act(() => deleteRow.click());
      expect(onMutationStart).toHaveBeenCalledOnce();
      expect(mounted.container.textContent).not.toContain("opened");
      const dialog = mounted.container.querySelector('[role="dialog"]') as HTMLElement;
      const confirm = Array.from(dialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Delete",
      ) as HTMLButtonElement;
      act(() => confirm.click());
      await settle();
      expect(mounted.container.querySelectorAll('[role="alert"]')).toHaveLength(1);
      expect(mounted.container.textContent).toContain("selection is unchanged");
      expect(mounted.container.textContent).not.toContain("opened");
      const closeError = mounted.container.querySelector<HTMLButtonElement>(
        'button[aria-label="Close Error"]',
      );
      act(() => closeError?.click());
      expect(mounted.container.querySelector(".sessions-error")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("closes the bulk confirmation before showing a deletion failure", async () => {
    await setLocale("en");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url === "/api/sessions" && !init) return Promise.resolve(response([session]));
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () =>
            Promise.resolve(
              JSON.stringify({
                detail: "bounded",
                error: { code: "session_deletion_failed", params: {} },
              }),
            ),
        } as Response);
      }),
    );
    const mounted = mount();
    try {
      await settle();
      act(() => {
        (
          mounted.container.querySelector('button[aria-label="Delete All"]') as HTMLButtonElement
        ).click();
      });
      const dialog = mounted.container.querySelector('[role="dialog"]') as HTMLElement;
      const confirm = Array.from(dialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Delete",
      ) as HTMLButtonElement;
      act(() => confirm.click());
      await settle();

      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
      expect(mounted.container.querySelectorAll('[role="alert"]')).toHaveLength(1);
      expect(mounted.container.textContent).toContain("selection is unchanged");
      expect(mounted.container.textContent).toContain("Alpha");
      expect(mounted.container.textContent).not.toContain("Deleted 1 session");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("moves Save and Cancel into the row action group while a title is edited", async () => {
    await setLocale("en");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response([session]))),
    );
    const mounted = mount();
    try {
      await settle();
      const edit = mounted.container.querySelector(
        'button[aria-label="Edit Session Title: Alpha"]',
      ) as HTMLButtonElement;
      expect(edit).not.toBeNull();
      act(() => edit.click());

      const row = mounted.container.querySelector('[data-file-id="alpha"]') as HTMLElement;
      const form = row.querySelector(".sessions-title-form");
      const actions = row.querySelector(".sessions-row-actions") as HTMLElement;
      expect(row.classList.contains("is-editing")).toBe(true);
      expect(form?.querySelectorAll("button")).toHaveLength(0);
      expect(actions.textContent).toContain("Save");
      expect(actions.textContent).toContain("Cancel");
      expect(actions.textContent).not.toContain("Open Folder");
      expect(actions.querySelector('button[aria-label="Delete"]')).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("uses shared, keyboard-safe confirmation dialogs for destructive actions", async () => {
    await setLocale("en");
    const onActiveSessionDeleted = vi.fn();
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/sessions") return Promise.resolve(response([session]));
      if (url === "/api/sessions/bulk-delete" && init?.method === "POST") {
        return Promise.resolve(
          response({ deleted_count: 1, deleted_ids: ["alpha"], was_open: false }),
        );
      }
      return Promise.resolve(response([]));
    });
    vi.stubGlobal("fetch", fetchMock);
    const mounted = mount(onActiveSessionDeleted);
    try {
      await settle();
      expect(mounted.container.querySelector(".sessions-action-open")?.textContent).toBe("Open");
      const folder = mounted.container.querySelector(
        'button[aria-label="Open Folder"]',
      ) as HTMLButtonElement;
      expect(folder?.textContent).toContain("folder_open");
      expect(folder?.textContent).toContain("Open Folder");
      const deleteRow = mounted.container.querySelector(
        'button.sessions-action-delete[aria-label="Delete"]',
      ) as HTMLButtonElement;
      expect(deleteRow).not.toBeNull();
      deleteRow.focus();
      act(() => deleteRow.click());
      await settle();

      const rowDialog = mounted.container.querySelector('[role="dialog"]') as HTMLElement;
      expect(rowDialog).not.toBeNull();
      expect(rowDialog.getAttribute("aria-modal")).toBe("true");
      const rowCancel = Array.from(rowDialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Cancel",
      ) as HTMLButtonElement;
      expect(document.activeElement).toBe(rowCancel);
      act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
      await settle();
      expect(mounted.container.querySelector('[role="dialog"]')).toBeNull();
      expect(document.activeElement).toBe(deleteRow);

      const deleteAll = mounted.container.querySelector(
        'button[aria-label="Delete All"]',
      ) as HTMLButtonElement;
      expect(deleteAll.querySelector(".material-symbol")?.textContent).toBe("delete");
      expect(deleteAll.textContent).toBe("deleteAll");
      const deleteExceptFavorites = mounted.container.querySelector(
        'button[aria-label="Delete All Except Favorites"]',
      ) as HTMLButtonElement;
      expect(deleteExceptFavorites.textContent).toBe("deleteAll Except Favorites");
      act(() => deleteAll.click());
      expect(mounted.container.textContent).toContain("Delete 1 session, including favorites?");
      const bulkDialog = mounted.container.querySelector('[role="dialog"]') as HTMLElement;
      const confirm = Array.from(bulkDialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Delete",
      ) as HTMLButtonElement;
      expect(confirm).not.toBeNull();
      act(() => confirm.click());
      await settle();

      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/bulk-delete",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ mode: "all", expected_file_ids: ["alpha"] }),
        }),
      );
      expect(onActiveSessionDeleted).toHaveBeenCalledWith(false, ["alpha"]);
    } finally {
      act(() => mounted.root.unmount());
    }
  });
});
