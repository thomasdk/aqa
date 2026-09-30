import { act, useRef, useState, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import { ConfirmDialog, Modal } from "./Modal";
import { IconButton } from "./IconButton";

const mountedRoots: Root[] = [];

afterEach(() => {
  act(() => mountedRoots.splice(0).forEach((root) => root.unmount()));
  document.body.replaceChildren();
});

async function mount(element: ReactElement) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  await act(async () => root.render(element));
  return { container, root };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function keyDown(target: HTMLElement | Document, key: string, options: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", {
    bubbles: true,
    cancelable: true,
    key,
    ...options,
  });
  act(() => target.dispatchEvent(event));
  return event;
}

function BasicFixture() {
  const [isOpen, setIsOpen] = useState(false);
  const initialFocusRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>
        Open dialog
      </button>
      {isOpen && (
        <Modal label="Dialog" onClose={() => setIsOpen(false)} initialFocusRef={initialFocusRef}>
          <button ref={initialFocusRef} type="button">
            Safe action
          </button>
          <button type="button">Confirm action</button>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("isolates the background, focuses safely, closes on Escape, and restores exact state", async () => {
    const preserved = document.createElement("section");
    preserved.setAttribute("aria-hidden", "false");
    preserved.setAttribute("inert", "preserved");
    document.body.appendChild(preserved);
    const { container } = await mount(<BasicFixture />);

    const opener = container.querySelector("button") as HTMLButtonElement;
    opener.focus();
    act(() => opener.click());

    const dialog = container.querySelector('[role="dialog"]') as HTMLDivElement;
    const safeAction = dialog.querySelector("button") as HTMLButtonElement;
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(safeAction);
    expect(opener.inert).toBe(true);
    expect(opener.getAttribute("aria-hidden")).toBe("true");
    expect(preserved.getAttribute("inert")).toBe("");
    expect(preserved.getAttribute("aria-hidden")).toBe("true");

    keyDown(safeAction, "Escape");

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(opener.hasAttribute("inert")).toBe(false);
    expect(opener.hasAttribute("aria-hidden")).toBe(false);
    expect(preserved.getAttribute("inert")).toBe("preserved");
    expect(preserved.getAttribute("aria-hidden")).toBe("false");
  });

  it("contains forward and reverse focus from boundaries, the dialog, and the background", async () => {
    const { container } = await mount(<BasicFixture />);
    const opener = container.querySelector("button") as HTMLButtonElement;
    act(() => opener.click());

    const dialog = container.querySelector('[role="dialog"]') as HTMLDivElement;
    const controls = dialog.querySelectorAll<HTMLButtonElement>("button");

    controls[1].focus();
    expect(keyDown(controls[1], "Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(controls[0]);

    expect(keyDown(controls[0], "Tab", { shiftKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(controls[1]);

    controls[0].focus();
    expect(keyDown(controls[0], "Tab").defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(controls[0]);

    dialog.focus();
    keyDown(dialog, "Tab", { shiftKey: true });
    expect(document.activeElement).toBe(controls[1]);

    controls[0].focus();
    opener.focus();
    expect(document.activeElement).toBe(controls[0]);
  });

  it("falls back from invalid initial targets and excludes disabled and hidden controls", async () => {
    function InvalidInitialFixture() {
      const [isOpen, setIsOpen] = useState(false);
      const outsideRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={outsideRef} type="button" onClick={() => setIsOpen(true)}>
            Open
          </button>
          {isOpen && (
            <Modal label="Fallback" onClose={() => setIsOpen(false)} initialFocusRef={outsideRef}>
              <button type="button" hidden>
                Hidden
              </button>
              <button type="button" disabled>
                Disabled
              </button>
              <input type="hidden" />
              <button type="button">Available</button>
            </Modal>
          )}
        </>
      );
    }

    const { container } = await mount(<InvalidInitialFixture />);
    act(() => (container.querySelector("button") as HTMLButtonElement).click());
    expect(document.activeElement?.textContent).toBe("Available");
  });

  it("contains focus with zero or one available control", async () => {
    const zero = await mount(
      <Modal label="Empty" onClose={() => undefined}>
        <button type="button" disabled>
          Disabled
        </button>
        <button type="button" hidden>
          Hidden
        </button>
      </Modal>,
    );
    const emptyDialog = zero.container.querySelector('[role="dialog"]') as HTMLDivElement;
    expect(document.activeElement).toBe(emptyDialog);
    expect(keyDown(emptyDialog, "Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(emptyDialog);

    act(() => mountedRoots.shift()?.unmount());
    zero.container.remove();

    const one = await mount(
      <Modal label="One" onClose={() => undefined}>
        <button type="button">Only</button>
      </Modal>,
    );
    const only = one.container.querySelector("button") as HTMLButtonElement;
    expect(document.activeElement).toBe(only);
    expect(keyDown(only, "Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(only);
    expect(keyDown(only, "Tab", { shiftKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(only);
  });

  it("recovers focus when changing content disables or removes the focused control", async () => {
    function DynamicFixture() {
      const [disabled, setDisabled] = useState(false);
      const [shown, setShown] = useState(true);
      return (
        <Modal label="Dynamic" onClose={() => undefined}>
          <button type="button" disabled={disabled} onClick={() => setDisabled(true)}>
            Disable current
          </button>
          {shown && (
            <button type="button" onClick={() => setShown(false)}>
              Remove current
            </button>
          )}
          <button type="button">Remaining</button>
        </Modal>
      );
    }

    const { container } = await mount(<DynamicFixture />);
    const disable = container.querySelector("button") as HTMLButtonElement;
    act(() => disable.click());
    await settle();
    expect(document.activeElement?.textContent).toBe("Remove current");

    const remove = document.activeElement as HTMLButtonElement;
    act(() => remove.click());
    await settle();
    expect(document.activeElement?.textContent).toBe("Remaining");
  });

  it("uses an explicit surviving return target when the opener is removed", async () => {
    function ReturnFixture() {
      const [open, setOpen] = useState(false);
      const [showOpener, setShowOpener] = useState(true);
      const returnRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          {showOpener && (
            <button type="button" onClick={() => setOpen(true)}>
              Removable opener
            </button>
          )}
          <button ref={returnRef} type="button">
            Surviving action
          </button>
          {open && (
            <Modal
              label="Return"
              onClose={() => {
                setOpen(false);
                setShowOpener(false);
              }}
              returnFocusRef={returnRef}
            >
              <button type="button">Close me</button>
            </Modal>
          )}
        </>
      );
    }

    const { container } = await mount(<ReturnFixture />);
    const opener = container.querySelector("button") as HTMLButtonElement;
    opener.focus();
    act(() => opener.click());
    keyDown(document.activeElement as HTMLElement, "Escape");
    expect(container.textContent).not.toContain("Removable opener");
    expect(document.activeElement?.textContent).toBe("Surviving action");
  });

  it("keeps only the topmost nested dialog active", async () => {
    function NestedFixture() {
      const [outer, setOuter] = useState(false);
      const [inner, setInner] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOuter(true)}>
            Open outer
          </button>
          {outer && (
            <Modal label="Outer" onClose={() => setOuter(false)}>
              <button type="button" onClick={() => setInner(true)}>
                Open inner
              </button>
              <button type="button">Outer action</button>
              {inner && (
                <Modal label="Inner" onClose={() => setInner(false)}>
                  <button type="button">Inner action</button>
                </Modal>
              )}
            </Modal>
          )}
        </>
      );
    }

    const { container } = await mount(<NestedFixture />);
    const originalOpener = container.querySelector("button") as HTMLButtonElement;
    originalOpener.focus();
    act(() => originalOpener.click());
    const innerOpener = document.activeElement as HTMLButtonElement;
    act(() => innerOpener.click());

    let dialogs = container.querySelectorAll<HTMLDivElement>('[role="dialog"]');
    expect(dialogs).toHaveLength(2);
    expect(innerOpener.inert).toBe(true);
    expect(innerOpener.getAttribute("aria-hidden")).toBe("true");
    expect(document.activeElement?.textContent).toBe("Inner action");

    keyDown(document.activeElement as HTMLElement, "Escape");
    dialogs = container.querySelectorAll<HTMLDivElement>('[role="dialog"]');
    expect(dialogs).toHaveLength(1);
    expect(innerOpener.inert).not.toBe(true);
    expect(innerOpener.hasAttribute("aria-hidden")).toBe(false);
    expect(document.activeElement).toBe(innerOpener);

    keyDown(innerOpener, "Escape");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(originalOpener);
  });

  it("identifies the innermost dialog when nested dialogs mount together", async () => {
    const closeOuter = vi.fn();
    const closeInner = vi.fn();
    const { container } = await mount(
      <Modal label="Outer" onClose={closeOuter}>
        <button type="button">Outer action</button>
        <Modal label="Inner" onClose={closeInner}>
          <button type="button">Inner action</button>
        </Modal>
      </Modal>,
    );

    const innerAction = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Inner action",
    ) as HTMLButtonElement;
    expect(document.activeElement).toBe(innerAction);
    keyDown(innerAction, "Escape");
    expect(closeInner).toHaveBeenCalledTimes(1);
    expect(closeOuter).not.toHaveBeenCalled();
  });

  it("leaves an Escape consumed by dialog content alone", async () => {
    const onClose = vi.fn();
    const { container } = await mount(
      <Modal label="Escape hygiene" onClose={onClose}>
        <button type="button" onKeyDown={(event) => event.preventDefault()}>
          Local escape
        </button>
      </Modal>,
    );
    const local = container.querySelector("button") as HTMLButtonElement;
    const event = keyDown(local, "Escape");
    expect(event.defaultPrevented).toBe(true);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("lets a focused icon tooltip consume only the first Escape", async () => {
    const onClose = vi.fn();
    const { container } = await mount(
      <Modal label="Tooltip escape" onClose={onClose}>
        <IconButton label="More options">
          <span aria-hidden="true">more_horiz</span>
        </IconButton>
      </Modal>,
    );
    const iconButton = container.querySelector("button") as HTMLButtonElement;

    expect(document.activeElement).toBe(iconButton);
    const tooltipEscape = keyDown(iconButton, "Escape");
    expect(tooltipEscape.defaultPrevented).toBe(true);
    expect(iconButton.dataset.tooltipDismissed).toBe("true");
    expect(onClose).not.toHaveBeenCalled();

    keyDown(iconButton, "Escape");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the modal open for a hovered tooltip and preserves the focused handler", async () => {
    const onClose = vi.fn();
    const focusedHandler = vi.fn();
    const { container } = await mount(
      <Modal label="Hover tooltip escape" onClose={onClose}>
        <IconButton label="More options">
          <span aria-hidden="true">more_horiz</span>
        </IconButton>
        <button type="button" onKeyDown={focusedHandler}>
          Focused action
        </button>
      </Modal>,
    );
    const [iconButton, focusedAction] = container.querySelectorAll<HTMLButtonElement>("button");

    act(() => iconButton.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
    act(() => focusedAction.focus());
    const tooltipEscape = keyDown(focusedAction, "Escape");
    expect(tooltipEscape.defaultPrevented).toBe(true);
    expect(iconButton.dataset.tooltipDismissed).toBe("true");
    expect(focusedHandler).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();

    keyDown(focusedAction, "Escape");
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("ConfirmDialog", () => {
  it("forwards an explicit surviving return target", async () => {
    function ConfirmReturnFixture() {
      const [open, setOpen] = useState(false);
      const [showOpener, setShowOpener] = useState(true);
      const returnRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          {showOpener && (
            <button type="button" onClick={() => setOpen(true)}>
              Remove after close
            </button>
          )}
          <button ref={returnRef} type="button">
            Remaining delete action
          </button>
          {open && (
            <ConfirmDialog
              title="Delete?"
              message="Cannot be undone"
              cancelLabel="Cancel"
              confirmLabel="Delete"
              onCancel={() => {
                setOpen(false);
                setShowOpener(false);
              }}
              onConfirm={() => undefined}
              returnFocusRef={returnRef}
            />
          )}
        </>
      );
    }

    const { container } = await mount(<ConfirmReturnFixture />);
    const opener = container.querySelector("button") as HTMLButtonElement;
    opener.focus();
    act(() => opener.click());
    keyDown(document.activeElement as HTMLElement, "Escape");
    expect(document.activeElement?.textContent).toBe("Remaining delete action");
  });

  it("uses Cancel initially and blocks Escape and backdrop cancellation while disabled", async () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    const { container, root } = await mount(
      <ConfirmDialog
        title="Delete?"
        message="Cannot be undone"
        cancelLabel="Cancel"
        confirmLabel="Delete"
        onCancel={onCancel}
        onConfirm={onConfirm}
        disabled
      />,
    );
    const dialog = container.querySelector('[role="dialog"]') as HTMLDivElement;
    const overlay = container.querySelector(".modal-overlay") as HTMLDivElement;
    expect(document.activeElement).toBe(dialog);

    keyDown(dialog, "Escape");
    act(() => overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })));
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();

    await act(async () =>
      root.render(
        <ConfirmDialog
          title="Delete?"
          message="Cannot be undone"
          cancelLabel="Cancel"
          confirmLabel="Delete"
          onCancel={onCancel}
          onConfirm={onConfirm}
        />,
      ),
    );
    keyDown(dialog, "Tab");
    expect(document.activeElement?.textContent).toBe("Cancel");
    keyDown(document.activeElement as HTMLElement, "Escape");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("uses the canonical localized action and filled danger style for delete dialogs", async () => {
    await setLocale("en");
    const { container } = await mount(
      <ConfirmDialog
        variant="delete"
        title="Delete Item?"
        message="This cannot be undone."
        cancelLabel="Cancel"
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );

    const confirm = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent === "Delete",
    );
    expect(confirm?.classList.contains("ds-button--dangerPrimary")).toBe(true);
    expect(document.activeElement?.textContent).toBe("Cancel");
  });

  it("exposes a pending confirmation as busy and disables both actions", async () => {
    const { container } = await mount(
      <ConfirmDialog
        variant="delete"
        title="Delete Item?"
        message="This cannot be undone."
        cancelLabel="Cancel"
        pendingLabel="Deleting …"
        disabled
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>("button"));
    expect(buttons.every((button) => button.disabled)).toBe(true);
    const confirm = buttons.find((button) => button.textContent === "Deleting …");
    expect(confirm?.getAttribute("aria-busy")).toBe("true");
  });
});
