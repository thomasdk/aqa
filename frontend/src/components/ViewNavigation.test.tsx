import { describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import ViewNavigation from "./ViewNavigation";
import { de, en } from "../locales";

describe("ViewNavigation configuration label", () => {
  it("uses Configure in English and Konfigurieren in German", () => {
    const html = renderToStaticMarkup(
      createElement(ViewNavigation, { view: "setup", onNavigate: () => undefined }),
    );

    expect(html).toContain("Konfigurieren");
    expect(de.nav.configure).toBe("Konfigurieren");
    expect(en.nav.configure).toBe("Configure");
  });
});

describe("ViewNavigation configuration menu", () => {
  it("toggles from nested button content and closes on an outside pointer interaction", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => root.render(<ViewNavigation view="setup" onNavigate={vi.fn()} />));

    const trigger = container.querySelector<HTMLButtonElement>("[data-configure-menu]")!;
    const nestedLabel = Array.from(trigger.querySelectorAll("span")).find(
      (span) => span.textContent === "Konfigurieren",
    )!;
    act(() => nestedLabel.click());
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector(".configuration-menu-panel")).not.toBeNull();

    act(() => document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })));
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector(".configuration-menu-panel")?.hasAttribute("hidden")).toBe(true);

    act(() => root.unmount());
    container.remove();
  });

  it("closes after navigation and Escape returns focus to the trigger", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const onNavigate = vi.fn();
    act(() => root.render(<ViewNavigation view="setup" onNavigate={onNavigate} />));

    const trigger = container.querySelector<HTMLButtonElement>("[data-configure-menu]")!;
    act(() => trigger.click());
    const localAI = container.querySelector<HTMLButtonElement>('[data-view="local-ai"]')!;
    localAI.focus();
    act(() => localAI.click());
    expect(onNavigate).toHaveBeenCalledWith("local-ai");
    expect(container.querySelector(".configuration-menu-panel")?.hasAttribute("hidden")).toBe(true);
    expect(document.activeElement).toBe(trigger);

    act(() => trigger.click());
    act(() =>
      trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })),
    );
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);

    act(() => root.unmount());
    container.remove();
  });

  it("opens and moves through configuration choices with arrow keys", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => root.render(<ViewNavigation view="setup" onNavigate={vi.fn()} />));

    const trigger = container.querySelector<HTMLButtonElement>("[data-configure-menu]")!;
    trigger.focus();
    act(() =>
      trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })),
    );
    await act(async () => Promise.resolve());

    const items = container.querySelectorAll<HTMLButtonElement>(".configuration-menu-item");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(items[0]);

    act(() => items[0].dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(document.activeElement).toBe(items[items.length - 1]);

    act(() => root.unmount());
    container.remove();
  });
});
