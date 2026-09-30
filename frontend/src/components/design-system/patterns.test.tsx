import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChoiceIndicator, FavoriteToggle, StatusBadge, StepMarker } from "./patterns";

const roots: Root[] = [];

function mount(element: ReactElement): HTMLDivElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  roots.push(root);
  return container;
}

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount());
  document.body.replaceChildren();
});

describe("design-system recurring patterns", () => {
  it("renders checked and unchecked decorative choice indicators", () => {
    const container = mount(
      <>
        <ChoiceIndicator selected />
        <ChoiceIndicator selected={false} />
      </>,
    );
    const indicators = container.querySelectorAll(".ds-choice-indicator");

    expect(indicators[0].getAttribute("aria-hidden")).toBe("true");
    expect(indicators[0].classList.contains("is-selected")).toBe(true);
    expect(indicators[0].textContent).toContain("check");
    expect(indicators[1].classList.contains("is-selected")).toBe(false);
    expect(indicators[1].textContent).toBe("");
  });

  it("renders a decorative circular workflow marker", () => {
    const container = mount(<StepMarker>3</StepMarker>);
    const marker = container.querySelector(".ds-step-marker");
    expect(marker?.getAttribute("aria-hidden")).toBe("true");
    expect(marker?.textContent).toBe("3");
  });

  it("renders neutral, information, and success status badges", () => {
    const container = mount(
      <>
        <StatusBadge>Queued</StatusBadge>
        <StatusBadge tone="info">Downloaded</StatusBadge>
        <StatusBadge tone="success">Running</StatusBadge>
      </>,
    );
    const badges = container.querySelectorAll(".ds-status-badge");
    expect(badges[0].classList.contains("ds-status-badge--neutral")).toBe(true);
    expect(badges[1].classList.contains("ds-status-badge--info")).toBe(true);
    expect(badges[2].classList.contains("ds-status-badge--success")).toBe(true);
  });

  it("owns the two-state favorite button semantics", () => {
    const onClick = vi.fn();
    const container = mount(
      <FavoriteToggle
        pressed
        activeLabel="Remove Favorite"
        inactiveLabel="Add Favorite"
        onClick={onClick}
      />,
    );
    const button = container.querySelector<HTMLButtonElement>("button")!;

    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.getAttribute("aria-label")).toBe("Remove Favorite");
    expect(button.querySelector(".favorite-star.is-active")).not.toBeNull();
    act(() => button.click());
    expect(onClick).toHaveBeenCalledOnce();
  });
});
