import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { setLocale } from "../i18n";
import type { HostInfo, LocalAIStatus } from "./types";
import AIReadinessIndicator, { isLocalAIUsable, localAIReadinessKey } from "./AIReadinessIndicator";

const status = (state: LocalAIStatus["state"], hostReady: boolean): LocalAIStatus =>
  ({ state, host_ready: hostReady }) as LocalAIStatus;

type Mounted = { container: HTMLDivElement; root: Root; onSourceChange: ReturnType<typeof vi.fn> };

function mountReadiness(
  localStatus: LocalAIStatus | null,
  source: "integrated" | "external" = "integrated",
  hosts: HostInfo[] = [],
): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onSourceChange = vi.fn();
  act(() =>
    root.render(
      createElement(AIReadinessIndicator, {
        hosts,
        source,
        localStatus,
        localStatusFailed: false,
        readinessChecked: true,
        onSourceChange,
        onNavigate: vi.fn(),
      }),
    ),
  );
  return { container, root, onSourceChange };
}

beforeEach(async () => {
  await setLocale("en");
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("AI readiness", () => {
  it("only treats a running or sleeping, reachable Integrated AI as usable", () => {
    expect(isLocalAIUsable(status("running", true))).toBe(true);
    expect(isLocalAIUsable(status("sleeping", true))).toBe(true);
    expect(isLocalAIUsable(status("stopped", true))).toBe(false);
    expect(isLocalAIUsable(status("running", false))).toBe(false);
    expect(isLocalAIUsable(null)).toBe(false);
  });

  it("keeps unavailable and setup states distinct in the UI", () => {
    expect(localAIReadinessKey(null, true)).toBe("error");
    expect(localAIReadinessKey(status("not_installed", false), false)).toBe("notInstalled");
    expect(localAIReadinessKey(status("installed", false), false)).toBe("startNeeded");
  });

  it("keeps both source choices visible when a source is usable", () => {
    const mounted = mountReadiness(status("running", true));
    try {
      const choices = mounted.container.querySelectorAll<HTMLInputElement>(
        'input[type="radio"][name="ai-source"]',
      );
      expect(choices).toHaveLength(2);
      expect(Array.from(choices).map((choice) => choice.value)).toEqual(["integrated", "external"]);
      expect(Array.from(choices).map((choice) => choice.checked)).toEqual([true, false]);
      expect(mounted.container.querySelector("button[aria-controls]")).toBeNull();
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("shows a checked radio marker only for the selected source", () => {
    const integrated = mountReadiness(status("running", true));
    try {
      const markers = integrated.container.querySelectorAll(".ai-readiness-choice-marker");
      expect(markers).toHaveLength(2);
      expect(markers[0].querySelector(".material-symbol")?.textContent).toBe("check");
      expect(markers[1].querySelector(".material-symbol")).toBeNull();
      expect(markers[0].closest(".ai-readiness-item")?.classList.contains("is-selected")).toBe(
        true,
      );
    } finally {
      act(() => integrated.root.unmount());
    }

    const external = mountReadiness(status("running", true), "external");
    try {
      const markers = external.container.querySelectorAll(".ai-readiness-choice-marker");
      expect(markers[0].querySelector(".material-symbol")).toBeNull();
      expect(markers[1].querySelector(".material-symbol")?.textContent).toBe("check");
      expect(markers[1].closest(".ai-readiness-item")?.classList.contains("is-selected")).toBe(
        true,
      );
    } finally {
      act(() => external.root.unmount());
    }
  });

  it("uses one native radio group for source selection", () => {
    const mounted = mountReadiness(status("running", true));
    try {
      const choices = mounted.container.querySelectorAll<HTMLInputElement>(
        'input[type="radio"][name="ai-source"]',
      );
      choices[0].focus();
      expect(document.activeElement).toBe(choices[0]);
      expect(choices[0].closest("label")?.classList.contains("ai-readiness-choice")).toBe(true);

      act(() => choices[1].click());
      expect(mounted.onSourceChange).toHaveBeenLastCalledWith("external");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("keeps Integrated AI selectable after External AI is selected", () => {
    const externalHost = {
      label: "OpenAI",
      url: "https://api.openai.example/v1",
      model: "gpt-4.1",
      models: ["gpt-4.1"],
      kind: "openai",
      has_api_key: true,
    } as HostInfo;
    const mounted = mountReadiness(status("running", true), "external", [externalHost]);
    try {
      const choices = mounted.container.querySelectorAll<HTMLInputElement>(
        '.ai-readiness-source-chooser input[type="radio"][name="ai-source"]',
      );
      expect(choices).toHaveLength(2);
      expect(choices[1].checked).toBe(true);
      const disclosure = mounted.container.querySelector("#ai-readiness-external-disclosure");
      expect(disclosure?.classList.contains("notice-banner--warning")).toBe(true);
      expect(disclosure?.getAttribute("role")).toBe("note");
      expect(disclosure?.textContent).toContain("When you select External AI");
      expect(disclosure?.textContent).toContain("session inputs");
      expect(disclosure?.textContent).toContain("token check");
      expect(choices[1].getAttribute("aria-describedby")).toBe("ai-readiness-external-disclosure");

      act(() => choices[0].click());
      expect(mounted.onSourceChange).toHaveBeenCalledWith("integrated");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("shows the English External AI transmission disclosure at the source decision", () => {
    const mounted = mountReadiness(status("running", true), "external");
    try {
      const disclosure = mounted.container.querySelector("#ai-readiness-external-disclosure");
      expect(disclosure?.textContent).toContain("When you select External AI");
      expect(disclosure?.textContent).toContain("session inputs");
      expect(disclosure?.textContent).toContain("target language");
      expect(disclosure?.textContent).toContain("token check");
      expect(disclosure?.textContent).not.toContain("sk-");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("hides the External AI transmission disclosure when Integrated AI is selected", () => {
    const mounted = mountReadiness(status("running", true), "integrated");
    try {
      expect(mounted.container.querySelector("#ai-readiness-external-disclosure")).toBeNull();
      const externalChoice = mounted.container.querySelectorAll<HTMLInputElement>(
        'input[type="radio"][name="ai-source"]',
      )[1];
      expect(externalChoice.hasAttribute("aria-describedby")).toBe(false);
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("shows the German External AI transmission disclosure at the source decision", async () => {
    await setLocale("de");
    const mounted = mountReadiness(status("running", true), "external");
    try {
      const disclosure = mounted.container.querySelector("#ai-readiness-external-disclosure");
      expect(disclosure?.textContent).toContain("Wenn du Externe KI auswählst");
      expect(disclosure?.textContent).toContain("Sitzungseingaben");
      expect(disclosure?.textContent).toContain("Token-Prüfung");
      expect(disclosure?.textContent).not.toContain("secret");
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("keeps the source chooser visible when the selected source is not usable", () => {
    const mounted = mountReadiness(status("stopped", false));
    try {
      expect(mounted.container.querySelector("button[aria-controls]")).toBeNull();
      expect(
        mounted.container.querySelectorAll('input[type="radio"][name="ai-source"]'),
      ).toHaveLength(2);
      const chooser = mounted.container.querySelector(".ai-readiness-source-chooser");
      const notice = mounted.container.querySelector(".setup-ai-notice");
      expect(chooser).not.toBeNull();
      expect(notice).not.toBeNull();
      expect(chooser!.compareDocumentPosition(notice!) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING,
      );
    } finally {
      act(() => mounted.root.unmount());
    }
  });

  it("does not show an unavailable-AI warning for a verified model Prepare can start", () => {
    const startableStatus = {
      ...status("installed", false),
      model_id: "gemma-4-e2b",
      preferred_model_id: "gemma-4-e2b",
      integrity: "verified",
      runtime_installed: true,
      models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "verified" }],
    } as LocalAIStatus;
    const mounted = mountReadiness(startableStatus);
    try {
      expect(mounted.container.querySelector(".setup-ai-notice")).toBeNull();
      expect(mounted.container.textContent).toContain("Configured");
    } finally {
      act(() => mounted.root.unmount());
    }
  });
});
