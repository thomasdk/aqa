// @vitest-environment node

import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

type Color = readonly [number, number, number, number];

const baseStyles = readFileSync(new URL("./styles/base.css", import.meta.url), "utf8");
const designSystemStyles = readFileSync(
  new URL("./styles/design-system.css", import.meta.url),
  "utf8",
);
const layoutStyles = readFileSync(new URL("./styles/layout.css", import.meta.url), "utf8");
const discussionStyles = readFileSync(new URL("./styles/discussion.css", import.meta.url), "utf8");
const responsiveStyles = readFileSync(new URL("./styles/responsive.css", import.meta.url), "utf8");

const darkTokens = baseStyles.match(/:root\s*\{([^}]+)\}/)![1];
const lightTokens = baseStyles.match(/:root\[data-theme="light"\]\s*\{([^}]+)\}/)![1];
let palette = darkTokens;

function variables() {
  return new Map(
    Array.from(palette.matchAll(/(--[\w-]+):\s*([^;]+);/g), ([, name, value]) => [
      name,
      value.trim(),
    ]),
  );
}

function resolveVariable(name: string, seen = new Set<string>()): string {
  if (seen.has(name)) throw new Error(`Circular CSS variable: ${name}`);
  seen.add(name);
  const value = variables().get(name);
  if (!value) throw new Error(`Unknown CSS variable: ${name}`);
  const reference = value.match(/^var\((--[\w-]+)\)$/)?.[1];
  return reference ? resolveVariable(reference, seen) : value;
}

function parseColor(source: string): Color {
  const hex = source.match(/^#([\da-f]{6})$/i)?.[1];
  if (hex) {
    return [0, 2, 4]
      .map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16))
      .concat(255)
      .map((channel) => channel / 255) as unknown as Color;
  }
  const rgba = source.match(
    /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\)$/,
  );
  if (rgba) {
    return [Number(rgba[1]) / 255, Number(rgba[2]) / 255, Number(rgba[3]) / 255, Number(rgba[4])];
  }
  throw new Error(`Unsupported CSS color: ${source}`);
}

function token(name: string): Color {
  return parseColor(resolveVariable(name));
}

function composite(foreground: Color, background: Color): Color {
  const alpha = foreground[3] + background[3] * (1 - foreground[3]);
  return [
    (foreground[0] * foreground[3] + background[0] * background[3] * (1 - foreground[3])) / alpha,
    (foreground[1] * foreground[3] + background[1] * background[3] * (1 - foreground[3])) / alpha,
    (foreground[2] * foreground[3] + background[2] * background[3] * (1 - foreground[3])) / alpha,
    alpha,
  ];
}

function luminance(color: Color): number {
  const channels = color
    .slice(0, 3)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

function contrast(foreground: Color, background: Color): number {
  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  return (
    (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
  );
}

function expectContrast(foreground: Color, background: Color, minimum: number): void {
  expect(contrast(foreground, background)).toBeGreaterThanOrEqual(minimum);
}

function lengthInCssPixels(name: string): number {
  const value = resolveVariable(name);
  const match = value.match(/^(\d+(?:\.\d+)?)(px|rem)$/);
  if (!match) throw new Error(`Unsupported CSS length: ${name} = ${value}`);
  return Number(match[1]) * (match[2] === "rem" ? 16 : 1);
}

describe.each(["dark", "light"])("%s accessibility color tokens", (theme) => {
  beforeEach(() => {
    palette = theme === "light" ? darkTokens + lightTokens : darkTokens;
  });
  it("keeps feedback text readable on composited tinted surfaces", () => {
    for (const state of ["info", "success", "warning", "danger", "custom"]) {
      for (const surface of ["raised", "recessed", "canvas"]) {
        const background = composite(
          token(`--aqa-state-${state}-bg`),
          token(`--aqa-surface-${surface}`),
        );
        expectContrast(token(`--aqa-state-${state}`), background, 4.5);
        expectContrast(token("--aqa-ink"), background, 4.5);
      }
    }
    for (const state of ["success", "warning", "custom"]) {
      const background = composite(token(`--aqa-badge-${state}-bg`), token("--aqa-surface-raised"));
      const foreground = state === "custom" ? "--aqa-state-custom" : `--aqa-badge-${state}-ink`;
      expectContrast(token(foreground), background, 4.5);
    }
  });

  it("keeps Markdown, material, and user-message reading surfaces legible", () => {
    for (const surface of ["raised", "recessed", "code", "user"]) {
      for (const text of [
        "ink",
        "ink-muted",
        "markdown-heading",
        "markdown-subheading",
        "markdown-strong",
        "markdown-emphasis",
      ]) {
        expectContrast(token(`--aqa-${text}`), token(`--aqa-surface-${surface}`), 4.5);
      }
    }
  });

  it("keeps synthesis text readable at every gradient stop", () => {
    for (const surface of [
      "synthesis",
      "synthesis-config",
      "synthesis-status",
      "synthesis-writing",
    ]) {
      const stops =
        resolveVariable(`--aqa-surface-${surface}`).match(/#[\da-f]{6}|rgba\([^)]+\)/gi) ?? [];
      expect(stops.length).toBeGreaterThanOrEqual(2);
      for (const stop of stops) {
        const background = composite(parseColor(stop), token("--aqa-surface-raised"));
        expectContrast(token("--aqa-ink"), background, 4.5);
        expectContrast(token("--aqa-synthesis-ink"), background, 4.5);
      }
    }
  });

  it("keeps missing required field outlines distinguishable", () => {
    for (const background of ["--aqa-surface-raised", "--aqa-surface-recessed"]) {
      expectContrast(token("--aqa-state-warning"), token(background), 3);
    }
    expect(layoutStyles).toMatch(
      /\.setup-group textarea\.setup-required-missing\s*\{[^}]*border-color: var\(--aqa-state-warning\);[^}]*box-shadow: inset 0 0 0 1px var\(--aqa-state-warning\);/,
    );
    expect(layoutStyles).toMatch(
      /\.setup-group textarea\.setup-required-missing:focus\s*\{[^}]*outline: 2px solid var\(--aqa-state-warning\);[^}]*border-color: var\(--aqa-state-warning\);[^}]*box-shadow: 0 0 0 2px var\(--aqa-state-warning-bg\);/,
    );
  });

  it("keeps essential boundaries distinguishable on every control surface", () => {
    for (const background of [
      "--aqa-surface-raised",
      "--aqa-surface-recessed",
      "--aqa-pool-raised",
    ]) {
      expectContrast(token("--aqa-border"), token(background), 3);
    }
  });

  it("keeps focus indicators distinguishable across normal and hover surfaces", () => {
    for (const background of [
      "--aqa-surface-canvas",
      "--aqa-surface-raised",
      "--aqa-surface-recessed",
      "--aqa-pool-raised",
    ]) {
      expectContrast(token("--aqa-aqua-bright"), token(background), 3);
    }
    expectContrast(token("--aqa-aqua-bright"), token("--aqa-action-secondary-hover"), 3);
  });

  it("keeps normal danger text readable over its strongest tinted surface", () => {
    const tintedBackground = composite(token("--aqa-state-danger-bg"), token("--aqa-pool-raised"));
    expectContrast(token("--aqa-state-danger"), tintedBackground, 4.5);
  });

  it("keeps subtle helper text readable on application surfaces", () => {
    for (const background of [
      "--aqa-surface-canvas",
      "--aqa-surface-raised",
      "--aqa-surface-recessed",
    ]) {
      expectContrast(token("--aqa-ink-subtle"), token(background), 4.5);
    }
  });

  it("keeps core design-system action and status colors readable", () => {
    for (const background of ["--aqa-action-primary", "--aqa-action-primary-hover"]) {
      expectContrast(token("--aqa-action-primary-ink"), token(background), 4.5);
    }
    expectContrast(token("--aqa-action-primary-ink"), token("--aqa-state-danger"), 4.5);
    for (const background of ["--aqa-action-secondary", "--aqa-action-secondary-hover"]) {
      expectContrast(token("--aqa-ink"), token(background), 4.5);
    }
    for (const foreground of ["--aqa-state-info", "--aqa-state-success", "--aqa-state-danger"]) {
      for (const background of ["--aqa-surface-raised", "--aqa-surface-recessed"]) {
        expectContrast(token(foreground), token(background), 4.5);
      }
    }
  });
});

describe("visual accessibility contracts", () => {
  beforeEach(() => {
    palette = darkTokens;
  });
  it("centralizes palette colors and separates action ink from the canvas", () => {
    for (const stylesheet of [
      "design-system",
      "layout",
      "discussion",
      "configuration",
      "local-ai",
      "responsive",
    ]) {
      const source = readFileSync(new URL(`./styles/${stylesheet}.css`, import.meta.url), "utf8");
      expect(source).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(/i);
      expect(source).not.toContain("color: var(--aqa-pool-deep)");
    }
    expect(baseStyles).toMatch(/:root\[data-theme="light"\]\s*\{\s*color-scheme: light;/);
  });

  it("uses contrast-tested placeholder ink without browser opacity dilution", () => {
    expect(baseStyles).toMatch(
      /input::placeholder,\s*textarea::placeholder\s*\{[^}]*color: var\(--aqa-ink-subtle\);[^}]*opacity: 1;/,
    );
  });

  it("uses distinct two-pixel focus rings for controls with custom interaction states", () => {
    expect(baseStyles).toMatch(
      /\.configuration-menu-item:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--aqa-aqua-bright\);/,
    );
    expect(layoutStyles).toMatch(
      /\.ai-readiness-choice:has\(\.choice-radio-input:focus-visible\)\s*\{[^}]*outline:\s*2px solid var\(--aqa-aqua-bright\);/,
    );
    expect(layoutStyles).toMatch(
      /\.session-type-card:has\(\.choice-radio-input:focus-visible\)\s*\{[^}]*outline:\s*2px solid var\(--aqa-aqua-bright\);/,
    );
    expect(layoutStyles).toMatch(
      /\.setup-mode-option:has\(\.choice-radio-input:focus-visible\)\s*\{[^}]*outline:\s*2px solid var\(--aqa-aqua-bright\);/,
    );
    expect(lengthInCssPixels("--aqa-focus-width")).toBeGreaterThanOrEqual(2);
    expectContrast(token("--aqa-focus-color"), token("--aqa-surface-canvas"), 3);
    expect(designSystemStyles).toMatch(
      /\.ds-control:focus-visible,[\s\S]*?\.ds-button:focus-visible,[\s\S]*?\.ds-icon-button:focus-visible\s*\{[^}]*outline:\s*var\(--aqa-focus-width\) solid var\(--aqa-focus-color\);/,
    );
  });

  it("keeps native radio markers and selected surfaces visually explicit", () => {
    expect(designSystemStyles).toMatch(
      /\.ds-choice-indicator\s*\{[^}]*width:\s*1\.55rem;[^}]*height:\s*1\.55rem;[^}]*border:\s*var\(--aqa-border-width\) solid var\(--aqa-border\);[^}]*border-radius:\s*50%;/,
    );
    expect(designSystemStyles).toMatch(
      /\.ds-choice-indicator\.is-selected\s*\{[^}]*background:\s*var\(--aqa-action-primary\);[^}]*color:\s*var\(--aqa-action-primary-ink\);/,
    );
    expect(layoutStyles).toMatch(
      /\.ai-readiness-item\.is-selected\s*\{[^}]*background:\s*var\(--aqa-pool-raised\);/,
    );
    expect(designSystemStyles).toMatch(
      /\.ds-step-marker\s*\{[^}]*width:\s*1\.45rem;[^}]*height:\s*1\.45rem;[^}]*border:\s*var\(--aqa-border-width\) solid var\(--aqa-border-strong\);[^}]*border-radius:\s*50%;[^}]*background:\s*var\(--aqa-surface-recessed\);[^}]*font-weight:\s*700;/,
    );
  });

  it("keeps compact desktop controls at least 24 CSS pixels tall", () => {
    expect(discussionStyles).toMatch(/\.activity-log-clear-btn\s*\{[^}]*min-height:\s*1\.5rem;/);
    expect(lengthInCssPixels("--aqa-control-height-small")).toBeGreaterThanOrEqual(24);
    expect(lengthInCssPixels("--aqa-control-height")).toBeGreaterThanOrEqual(24);
    expect(designSystemStyles).toMatch(
      /\.ds-control--small\s*\{[^}]*min-height:\s*var\(--aqa-control-height-small\);/,
    );
    expect(designSystemStyles).toMatch(
      /\.ds-icon-button\.ds-control--small\s*\{[^}]*min-width:\s*var\(--aqa-control-height-small\);/,
    );
  });

  it("preserves an invalid boundary without suppressing the shared focus outline", () => {
    const invalidRule = designSystemStyles.match(
      /\.ds-control\[aria-invalid="true"\]\s*\{([^}]*)\}/,
    )?.[1];
    expect(invalidRule).toBeDefined();
    expect(invalidRule).toContain("border-color: var(--aqa-state-danger)");
    expect(invalidRule).not.toMatch(/\boutline\s*:/);
    expectContrast(token("--aqa-state-danger"), token("--aqa-surface-recessed"), 3);
  });

  it("wraps icon tooltips and keeps pointer-triggered content hoverable", () => {
    expect(responsiveStyles).toMatch(
      /\.icon-button::after\s*\{[^}]*max-width:[^;]+;[^}]*pointer-events:\s*none;[^}]*overflow-wrap:\s*anywhere;[^}]*white-space:\s*normal;/,
    );
    expect(responsiveStyles).toMatch(
      /\.icon-button:not\(\[data-tooltip-dismissed="true"\]\):hover::after,[\s\S]*?\.icon-button:not\(\[data-tooltip-dismissed="true"\]\):focus-visible::after\s*\{[^}]*pointer-events:\s*auto;[^}]*visibility:\s*visible;/,
    );
  });

  it("disables every product animation when reduced motion is requested", () => {
    const reducedMotion = responsiveStyles.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    expect(reducedMotion).toBeDefined();
    for (const selector of [
      ".aqa-brand [data-aqa-wave]",
      ".icon-spinning",
      ".agent-waveform span",
      ".streaming-caret",
      ".message-loading",
      ".discussion-message.is-just-arrived",
    ]) {
      expect(reducedMotion).toContain(selector);
    }
    expect(reducedMotion).toMatch(/animation:\s*none !important;/);

    const designSystemReducedMotion = designSystemStyles.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    expect(designSystemReducedMotion).toBeDefined();
    for (const selector of [".ds-button", ".ds-control", ".ds-icon-button"]) {
      expect(designSystemReducedMotion).toContain(selector);
    }
    expect(designSystemReducedMotion).toMatch(/transition:\s*none;/);
  });
});
