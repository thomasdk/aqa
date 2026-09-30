// Required by React 18's `act` environment detection.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// A German browser locale verifies that first-run language is not browser-derived.
if (typeof navigator !== "undefined") {
  Object.defineProperty(globalThis.navigator, "languages", {
    configurable: true,
    value: ["de-DE"],
  });
  Object.defineProperty(globalThis.navigator, "language", {
    configurable: true,
    value: "de-DE",
  });
}

// Component tests bypass `main.tsx`, so initialize its locale singleton here.
if (typeof window !== "undefined") {
  window.localStorage.setItem("aqa.uiLocale.v1", "de");
  window.localStorage.removeItem("aqa.aiSource.v1");
}
await import("./i18n");

export {};
