import { act, createRef, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IconButton, type IconButtonVariant } from "./IconButton";

const roots: Root[] = [];

function mount(element: ReactElement): HTMLButtonElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  roots.push(root);
  return container.querySelector("button")!;
}

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount());
  document.body.replaceChildren();
});

describe("IconButton", () => {
  it.each<IconButtonVariant>(["secondary", "danger", "ghost"])(
    "keeps the %s variant a named native button",
    (variant) => {
      const button = mount(
        <IconButton label="Open Settings" variant={variant}>
          <span aria-hidden="true">settings</span>
        </IconButton>,
      );

      expect(button).toBeInstanceOf(HTMLButtonElement);
      expect(button.type).toBe("button");
      expect(button.getAttribute("aria-label")).toBe("Open Settings");
      expect(button.dataset.tooltip).toBe("Open Settings");
      expect(button.classList.contains(`ds-icon-button--${variant}`)).toBe(true);
    },
  );

  it("forwards its ref, explicit type, state, properties, and click behavior", () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    const button = mount(
      <IconButton
        ref={ref}
        label="Show Details"
        type="submit"
        aria-pressed="true"
        aria-expanded="false"
        data-purpose="details"
        onClick={onClick}
      >
        <span aria-hidden="true">more_horiz</span>
      </IconButton>,
    );

    expect(ref.current).toBe(button);
    expect(button.type).toBe("submit");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.dataset.purpose).toBe("details");
    act(() => button.click());
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("preserves native disabled behavior", () => {
    const onClick = vi.fn();
    const button = mount(
      <IconButton label="Delete" disabled onClick={onClick}>
        <span aria-hidden="true">delete</span>
      </IconButton>,
    );

    expect(button.disabled).toBe(true);
    act(() => button.click());
    expect(onClick).not.toHaveBeenCalled();
  });

  it("dismisses a focused tooltip for the current interaction and lets a later Escape bubble", () => {
    const parentEscape = vi.fn();
    const onKeyDown = vi.fn();
    document.addEventListener("keydown", parentEscape);
    const button = mount(
      <IconButton label="Open Settings" onKeyDown={onKeyDown}>
        <span aria-hidden="true">settings</span>
      </IconButton>,
    );

    act(() => button.focus());
    const dismissEvent = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Escape",
    });
    act(() => button.dispatchEvent(dismissEvent));

    expect(dismissEvent.defaultPrevented).toBe(true);
    expect(parentEscape).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(button);
    expect(button.dataset.tooltipDismissed).toBe("true");
    expect(button.getAttribute("aria-label")).toBe("Open Settings");
    expect(button.dataset.tooltip).toBe("Open Settings");
    expect(onKeyDown).toHaveBeenCalledOnce();

    const laterEscape = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Escape",
    });
    act(() => button.dispatchEvent(laterEscape));
    expect(laterEscape.defaultPrevented).toBe(false);
    expect(parentEscape).toHaveBeenCalledOnce();
    document.removeEventListener("keydown", parentEscape);

    act(() => {
      button.blur();
      button.focus();
    });
    expect(button.dataset.tooltipDismissed).toBeUndefined();
  });

  it("reopens a dismissed tooltip for a new pointer interaction", () => {
    const button = mount(
      <IconButton label="Delete">
        <span aria-hidden="true">delete</span>
      </IconButton>,
    );

    act(() => button.focus());
    act(() =>
      button.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" }),
      ),
    );
    expect(button.dataset.tooltipDismissed).toBe("true");

    act(() => button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
    expect(button.dataset.tooltipDismissed).toBeUndefined();
  });

  it("dismisses a hover-only tooltip from Escape without moving the pointer", () => {
    const focusedHandler = vi.fn((event: KeyboardEvent) => {
      expect(event.defaultPrevented).toBe(true);
    });
    const focusedControl = document.createElement("input");
    focusedControl.addEventListener("keydown", focusedHandler);
    document.body.appendChild(focusedControl);
    const button = mount(
      <IconButton label="Delete">
        <span aria-hidden="true">delete</span>
      </IconButton>,
    );

    act(() => button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
    focusedControl.focus();
    const escape = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Escape",
    });
    act(() => focusedControl.dispatchEvent(escape));

    expect(escape.defaultPrevented).toBe(true);
    expect(button.dataset.tooltipDismissed).toBe("true");
    expect(document.activeElement).not.toBe(button);
    expect(focusedHandler).toHaveBeenCalledOnce();

    act(() => button.dispatchEvent(new MouseEvent("pointerout", { bubbles: true })));
    act(() => button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
    expect(button.dataset.tooltipDismissed).toBeUndefined();
  });

  it("preserves the focused button handler when focus and pointer both expose tooltips", () => {
    const onKeyDown = vi.fn();
    const button = mount(
      <IconButton label="More options" onKeyDown={onKeyDown}>
        <span aria-hidden="true">more_horiz</span>
      </IconButton>,
    );

    act(() => {
      button.focus();
      button.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
    });
    const escape = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Escape",
    });
    act(() => button.dispatchEvent(escape));

    expect(escape.defaultPrevented).toBe(true);
    expect(onKeyDown).toHaveBeenCalledOnce();
    expect(button.dataset.tooltipDismissed).toBe("true");
    expect(document.activeElement).toBe(button);
  });
});
