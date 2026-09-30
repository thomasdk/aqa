import { act, createRef, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import NoticeBanner, { type NoticeTone } from "./NoticeBanner";
import BlockedActionHint from "./BlockedActionHint";
import { Modal } from "./Modal";

async function settleFocus() {
  await act(async () => {
    await Promise.resolve();
  });
}

afterEach(async () => {
  document.body.replaceChildren();
  await setLocale("de");
});

describe("NoticeBanner", () => {
  it.each([
    ["info", "status", "Close Notice", "info"],
    ["success", "status", "Close Notice", "check"],
    ["warning", "status", "Close Notice", "warning"],
    ["error", "alert", "Close Error", "error"],
  ] as const)("renders a dismissible %s announcement", async (tone, role, closeLabel, icon) => {
    await setLocale("en");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const onDismiss = vi.fn();

    act(() => {
      root.render(
        <NoticeBanner tone={tone as NoticeTone} onDismiss={onDismiss}>
          Example notification
        </NoticeBanner>,
      );
    });

    const banner = container.querySelector(`[role="${role}"]`);
    expect(banner?.textContent).toContain("Example notification");
    expect(banner?.querySelector(".notice-banner__icon")?.textContent).toContain(icon);
    expect(banner?.getAttribute("aria-live")).toBe(tone === "error" ? null : "polite");
    const close = container.querySelector<HTMLButtonElement>(`button[aria-label="${closeLabel}"]`);
    expect(close?.title).toBe(closeLabel);
    act(() => close?.click());
    expect(onDismiss).toHaveBeenCalledOnce();
    act(() => root.unmount());
  });

  it("styles every blocked action as danger feedback without announcing it", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(<BlockedActionHint>Shorten the input.</BlockedActionHint>);
    });

    const hint = container.querySelector(".blocked-action-hint");
    expect(hint?.className).toBe("blocked-action-hint");
    expect(hint?.getAttribute("role")).toBeNull();
    expect(hint?.getAttribute("aria-live")).toBeNull();
    expect(hint?.querySelector(".material-symbol")?.textContent).toContain("help");
    act(() => root.unmount());
  });

  it("localizes the dismiss control", async () => {
    await setLocale("de");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(
        <NoticeBanner tone="warning" onDismiss={() => undefined}>
          Hinweis
        </NoticeBanner>,
      );
    });

    expect(container.querySelector('button[aria-label="Hinweis schließen"]')).not.toBeNull();
    act(() => root.unmount());
  });

  it("supports persistent notices with a tone icon and deliberate role", async () => {
    await setLocale("en");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => {
      root.render(
        <NoticeBanner tone="warning" role="note">
          External AI disclosure
        </NoticeBanner>,
      );
    });

    const banner = container.querySelector('[role="note"]');
    expect(banner?.classList.contains("notice-banner--warning")).toBe(true);
    expect(banner?.querySelector(".notice-banner__icon")?.textContent).toContain("warning");
    expect(banner?.querySelector("button")).toBeNull();
    expect(banner?.getAttribute("aria-live")).toBeNull();
    act(() => root.unmount());
  });

  it("restores focus after actual unmount to an explicit target enabled by dismissal", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    function Fixture() {
      const [visible, setVisible] = useState(true);
      const returnRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={returnRef} type="button" disabled={visible}>
            Restore notices
          </button>
          {visible && (
            <NoticeBanner
              tone="info"
              dismissReturnFocusRef={returnRef}
              onDismiss={() => setVisible(false)}
            >
              Example notification
            </NoticeBanner>
          )}
        </>
      );
    }

    act(() => root.render(<Fixture />));
    const dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
    act(() => dismiss.focus());
    act(() => dismiss.click());
    await settleFocus();

    expect(container.querySelector(".notice-banner")).toBeNull();
    expect(document.activeElement?.textContent).toBe("Restore notices");
    act(() => root.unmount());
  });

  it("uses the next nearby target and does not steal focus when dismissal starts elsewhere", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    function Fixture() {
      const [visible, setVisible] = useState(true);
      return (
        <>
          <button type="button">Before</button>
          {visible && (
            <NoticeBanner tone="warning" onDismiss={() => setVisible(false)}>
              Review this
            </NoticeBanner>
          )}
          <button type="button">After</button>
        </>
      );
    }

    act(() => root.render(<Fixture />));
    let dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
    act(() => dismiss.focus());
    act(() => dismiss.click());
    await settleFocus();
    expect(document.activeElement?.textContent).toBe("After");

    act(() => root.render(<Fixture key="again" />));
    const before = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Before",
    )!;
    dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
    act(() => before.focus());
    act(() => dismiss.click());
    await settleFocus();
    expect(document.activeElement).toBe(before);
    act(() => root.unmount());
  });

  it.each(["disabled", "aria-disabled", "hidden", "disconnected"] as const)(
    "rejects an unusable %s explicit target and uses the fallback",
    async (targetState) => {
      const container = document.createElement("div");
      document.body.appendChild(container);
      const root = createRoot(container);
      const disconnected = document.createElement("button");
      const externalRef = createRef<HTMLElement>();
      Object.defineProperty(externalRef, "current", { value: disconnected });

      function Fixture() {
        const [visible, setVisible] = useState(true);
        const targetRef = useRef<HTMLButtonElement>(null);
        return (
          <>
            {targetState !== "disconnected" && (
              <button
                ref={targetRef}
                type="button"
                disabled={targetState === "disabled"}
                aria-disabled={targetState === "aria-disabled" ? "true" : undefined}
                style={targetState === "hidden" ? { display: "none" } : undefined}
              >
                Unusable
              </button>
            )}
            {visible && (
              <NoticeBanner
                tone="error"
                dismissReturnFocusRef={targetState === "disconnected" ? externalRef : targetRef}
                onDismiss={() => setVisible(false)}
              >
                Failed
              </NoticeBanner>
            )}
            <button type="button">Fallback</button>
          </>
        );
      }

      act(() => root.render(<Fixture />));
      const dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
      act(() => dismiss.focus());
      act(() => dismiss.click());
      await settleFocus();
      expect(document.activeElement?.textContent).toBe("Fallback");
      act(() => root.unmount());
    },
  );

  it("does not restore focus when dismissal rerenders without removing the banner", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    function Fixture() {
      const [alternateTarget, setAlternateTarget] = useState(false);
      const firstRef = createRef<HTMLButtonElement>();
      const secondRef = createRef<HTMLButtonElement>();
      return (
        <>
          <button ref={firstRef} type="button">
            First target
          </button>
          <button ref={secondRef} type="button">
            Second target
          </button>
          <NoticeBanner
            tone="warning"
            dismissReturnFocusRef={alternateTarget ? secondRef : firstRef}
            onDismiss={() => setAlternateTarget(true)}
          >
            Still mounted
          </NoticeBanner>
        </>
      );
    }

    act(() => root.render(<Fixture />));
    const dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
    act(() => dismiss.focus());
    act(() => dismiss.click());
    await settleFocus();

    expect(container.querySelector(".notice-banner")).not.toBeNull();
    expect(document.activeElement).toBe(dismiss);
    act(() => root.unmount());
  });

  it("keeps fallback focus inside a modal when an explicit target is outside", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    function Fixture() {
      const [visible, setVisible] = useState(true);
      const outsideRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={outsideRef} type="button">
            Outside
          </button>
          <Modal label="Notice dialog" onClose={() => undefined}>
            {visible && (
              <NoticeBanner
                tone="info"
                dismissReturnFocusRef={outsideRef}
                onDismiss={() => setVisible(false)}
              >
                Inside notice
              </NoticeBanner>
            )}
            <button type="button">Inside fallback</button>
          </Modal>
        </>
      );
    }

    act(() => root.render(<Fixture />));
    const dismiss = container.querySelector(".notice-banner__dismiss") as HTMLButtonElement;
    act(() => dismiss.focus());
    act(() => dismiss.click());
    await settleFocus();

    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.activeElement?.textContent).toBe("Inside fallback");
    act(() => root.unmount());
  });
});
