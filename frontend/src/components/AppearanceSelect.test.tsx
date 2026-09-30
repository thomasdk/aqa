import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import { initializeAppearance, getAppearance, waitForNativeAppearance } from "../appearance";
import { AppearanceSelect } from "./AppearanceSelect";

vi.mock("../desktopBridge", () => ({ setNativeAppearance: vi.fn().mockResolvedValue(undefined) }));
vi.mock("../api", () => ({ updateApplicationPreferences: vi.fn().mockResolvedValue({}) }));
afterEach(() => {
  document.body.replaceChildren();
  window.localStorage.clear();
});

describe("appearance selector", () => {
  it.each([
    ["en", "Appearance Mode", ["Adaptive", "Light", "Dark"]],
    ["de", "Darstellungsmodus", ["Adaptiv", "Hell", "Dunkel"]],
  ] as const)(
    "labels native choices and applies them immediately in %s",
    async (locale, label, options) => {
      await setLocale(locale);
      const dispose = initializeAppearance();
      const container = document.createElement("div");
      document.body.append(container);
      const root = createRoot(container);
      act(() => root.render(<AppearanceSelect />));
      const select = container.querySelector("select")!;
      expect(select.labels?.[0].textContent).toBe(label);
      expect([...select.options].map((option) => option.textContent)).toEqual(options);
      expect(
        document.getElementById(select.getAttribute("aria-describedby")!)?.textContent,
      ).toBeTruthy();
      act(() => {
        select.focus();
        select.value = "dark";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(getAppearance()).toBe("dark");
      expect(document.activeElement).toBe(select);
      expect(document.documentElement.dataset.theme).toBe("dark");
      act(() => root.unmount());
      await waitForNativeAppearance();
      dispose();
    },
  );
});
