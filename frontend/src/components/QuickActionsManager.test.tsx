import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "../i18n";
import QuickActionsManager, { type QuickActionsApi } from "./QuickActionsManager";

const shippedAction = {
  id: "debate",
  label: "Debate",
  prompt: "Continue the discussion by responding to the contributions of the previous round.",
  is_shipped: true,
  origin: "shipped_default" as const,
};

async function mount(api: QuickActionsApi): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<QuickActionsManager api={api} />);
    await Promise.resolve();
  });
  return { container, root };
}

function setInputValue(input: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(prototype.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("QuickActionsManager", () => {
  it("lets the user dismiss a load error", async () => {
    await setLocale("en");
    const api: QuickActionsApi = {
      list: vi.fn(async () => {
        throw new Error("failed");
      }),
      reveal: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      restore: vi.fn(),
      restoreAll: vi.fn(),
    };
    const { container, root } = await mount(api);

    const banner = container.querySelector('.qam-feedback[role="alert"]');
    expect(banner).not.toBeNull();
    const close = banner?.querySelector<HTMLButtonElement>('button[aria-label="Close Error"]');
    const restoreDefaultsButton = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent?.includes("Restore Default Quick Actions"),
    )!;
    expect(restoreDefaultsButton.disabled).toBe(true);
    expect(restoreDefaultsButton.title).toBe("");
    act(() => close?.click());
    expect(container.querySelector(".qam-feedback")).toBeNull();
    act(() => root.unmount());
  });

  it("shows configured labels and creates a generic text-only action", async () => {
    await setLocale("en");
    const create = vi.fn(async (action: { id: string; label: string; prompt: string }) => ({
      ...action,
      is_shipped: false,
      origin: "custom" as const,
    }));
    const api: QuickActionsApi = {
      list: vi.fn(async () => ({ actions: [shippedAction], can_restore_defaults: false })),
      reveal: vi.fn(async () => ({ status: "ok" as const })),
      create,
      update: vi.fn(),
      remove: vi.fn(),
      restore: vi.fn(),
      restoreAll: vi.fn(),
    };
    const { container, root } = await mount(api);

    expect(container.textContent).toContain("Debate");
    const tableRegion = container.querySelector<HTMLElement>(".pcm-table-scroll");
    expect(tableRegion?.getAttribute("role")).toBe("region");
    expect(tableRegion?.getAttribute("aria-label")).toBe("Quick Actions");
    expect(tableRegion?.tabIndex).toBe(0);
    const restoreDefaultsButton = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent?.includes("Restore Default Quick Actions"),
    )!;
    expect(restoreDefaultsButton.disabled).toBe(true);
    expect(restoreDefaultsButton.title).toBe(
      "All default Quick Actions are present and unchanged.",
    );
    restoreDefaultsButton.click();
    expect(api.restoreAll).not.toHaveBeenCalled();
    expect(container.querySelector(".qam-section")?.classList.contains("pcm-section")).toBe(true);
    expect(container.querySelector(".qam-section > .pcm-section-header")).not.toBeNull();
    expect(container.querySelector(".qam-section .pcm-section-header p")?.textContent).toContain(
      "Reusable directions",
    );
    const openFolderButton = container.querySelector(
      'button[aria-label="Open Folder"]',
    ) as HTMLButtonElement;
    expect(openFolderButton.textContent).toContain("folder_open");
    await act(async () => openFolderButton.click());
    expect(api.reveal).toHaveBeenCalledOnce();
    const deleteButton = container.querySelector(
      "button.ds-icon-button--danger",
    ) as HTMLButtonElement;
    expect(deleteButton.getAttribute("aria-label")).toBe("Delete Quick Action “Debate”");
    expect(deleteButton.textContent).toContain("delete");
    await act(async () => deleteButton.click());
    expect(container.querySelector('[role="dialog"] h2')?.textContent).toBe("Delete Quick Action?");
    const cancelDelete = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Cancel",
    );
    await act(async () => cancelDelete?.click());

    const newButton = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("New Quick Action"),
    );
    await act(async () => newButton?.click());

    const modal = container.querySelector(".modal-content.qam-modal");
    expect(modal?.classList.contains("modal-content")).toBe(true);
    expect(modal?.getAttribute("role")).toBe("dialog");
    expect(modal?.getAttribute("aria-modal")).toBe("true");
    expect(modal?.querySelector("#qam-modal-title")?.textContent).toContain("New Quick Action");
    expect(modal?.querySelector(":scope > form.rm-form#qam-editor-form")).not.toBeNull();
    expect(modal?.querySelectorAll(".rm-form-row")).toHaveLength(3);
    const footer = modal?.querySelector(":scope > .ds-dialog-footer");
    expect(footer).not.toBeNull();
    expect(footer?.querySelector('button[type="submit"]')?.getAttribute("form")).toBe(
      "qam-editor-form",
    );

    const [id, label] = [...container.querySelectorAll("input")] as HTMLInputElement[];
    const prompt = container.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      setInputValue(id, "revisit_evidence");
      setInputValue(label, "Revisit Evidence");
      setInputValue(prompt, "Return to the cited evidence.");
    });
    const form = container.querySelector("form") as HTMLFormElement;
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(create).toHaveBeenCalledWith({
      id: "revisit_evidence",
      label: "Revisit Evidence",
      prompt: "Return to the cited evidence.",
    });
    expect(container.querySelector('.visually-hidden[role="status"]')?.textContent).toContain(
      "Quick Action “Revisit Evidence” saved.",
    );
    expect(container.querySelector(".qam-notice")).toBeNull();
    act(() => root.unmount());
    await setLocale("de");
  });

  it("offers the bulk restore when a default is edited or missing", async () => {
    await setLocale("en");
    let canRestoreDefaults = true;
    const restoreAll = vi.fn(async () => {
      canRestoreDefaults = false;
      return { restored: ["debate", "focus"] };
    });
    const api: QuickActionsApi = {
      list: vi.fn(async () => ({
        actions: [shippedAction],
        can_restore_defaults: canRestoreDefaults,
      })),
      reveal: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      restore: vi.fn(),
      restoreAll,
    };
    const { container, root } = await mount(api);
    const restoreDefaultsButton = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent?.includes("Restore Default Quick Actions"),
    )!;

    expect(restoreDefaultsButton.disabled).toBe(false);
    await act(async () => restoreDefaultsButton.click());
    const confirm = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent === "Restore Now",
    )!;
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });

    expect(restoreAll).toHaveBeenCalledOnce();
    expect(restoreDefaultsButton.disabled).toBe(true);
    expect(container.querySelector('.visually-hidden[role="status"]')?.textContent).toContain(
      "Default Quick Actions restored.",
    );
    act(() => root.unmount());
    await setLocale("de");
  });

  it("keeps a save failure inside the open dialog", async () => {
    await setLocale("en");
    const api: QuickActionsApi = {
      list: vi.fn(async () => ({ actions: [], can_restore_defaults: true })),
      reveal: vi.fn(),
      create: vi.fn(async () => {
        throw new Error("failed");
      }),
      update: vi.fn(),
      remove: vi.fn(),
      restore: vi.fn(),
      restoreAll: vi.fn(),
    };
    const { container, root } = await mount(api);
    const newButton = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("New Quick Action"),
    )!;
    await act(async () => newButton.click());
    const [id, label] = [...container.querySelectorAll("input")] as HTMLInputElement[];
    const prompt = container.querySelector("textarea")!;
    await act(async () => {
      setInputValue(id, "retry_action");
      setInputValue(label, "Retry Action");
      setInputValue(prompt, "Try the analysis again.");
    });
    await act(async () => {
      container
        .querySelector("form")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    const dialog = container.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector('[role="alert"]')?.textContent).toContain(
      "Quick Action could not be saved.",
    );
    expect(container.querySelector(".qam-section > .qam-feedback")).toBeNull();
    expect(dialog.contains(document.activeElement)).toBe(true);
    act(() => root.unmount());
    await setLocale("de");
  });

  it("returns focus to New Quick Action after deleting an action", async () => {
    await setLocale("en");
    let actions = [shippedAction];
    const remove = vi.fn(async () => {
      actions = [];
    });
    const api: QuickActionsApi = {
      list: vi.fn(async () => ({ actions, can_restore_defaults: actions.length === 0 })),
      reveal: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove,
      restore: vi.fn(),
      restoreAll: vi.fn(),
    };
    const { container, root } = await mount(api);
    const newButton = [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
      button.textContent?.includes("New Quick Action"),
    )!;

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('button[aria-label="Delete Quick Action “Debate”"]')!
        .click();
    });
    const dialog = container.querySelector('[role="dialog"]')!;
    const confirm = [...dialog.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent === "Delete",
    )!;
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });

    expect(remove).toHaveBeenCalledWith("debate");
    expect(document.activeElement).toBe(newButton);
    expect(container.querySelector('.visually-hidden[role="status"]')?.textContent).toContain(
      "Quick Action “Debate” deleted.",
    );
    act(() => root.unmount());
    await setLocale("de");
  });
});
