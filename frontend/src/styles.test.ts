// @vitest-environment node

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function readStylesheet(url: URL, visited = new Set<string>()): string {
  if (visited.has(url.href)) return "";
  visited.add(url.href);
  const source = readFileSync(url, "utf8");
  return source.replace(/@import\s+["']([^"']+)["'];/g, (_match, path: string) =>
    readStylesheet(new URL(path, url), visited),
  );
}

const styles = readStylesheet(new URL("./styles.css", import.meta.url));
const discussionStyles = readFileSync(new URL("./styles/discussion.css", import.meta.url), "utf8");

function hasControlGeometry(selector: string): boolean {
  return styles
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("}")
    .some((rule) => {
      const [selectorList, declarations] = rule.split("{");
      return (
        selectorList?.split(",").some((candidate) => candidate.trim() === selector) &&
        /min-height:\s*var\(--aqa-control-height\);/.test(declarations ?? "") &&
        /padding:\s*var\(--aqa-control-padding-block\)\s+var\(--aqa-control-padding-inline\);/.test(
          declarations ?? "",
        )
      );
    });
}

describe("stylesheet module boundaries", () => {
  it("loads focused stylesheets in cascade order", () => {
    const entrypoint = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
    expect(entrypoint.trim().split("\n")).toEqual([
      '@import "./styles/base.css";',
      '@import "./styles/design-system.css";',
      '@import "./styles/about.css";',
      '@import "./styles/layout.css";',
      '@import "./styles/discussion.css";',
      '@import "./styles/configuration.css";',
      '@import "./styles/local-ai.css";',
      '@import "./styles/responsive.css";',
    ]);
  });
});

describe("global app canvas", () => {
  it("uses one solid canvas background without a radial logo glow", () => {
    expect(styles).toMatch(/body\s*\{[^}]*background:\s*var\(--aqa-surface-canvas\);/);
    expect(styles).not.toMatch(/radial-gradient\(/);
  });
});

describe("activity context footprint", () => {
  it("uses the activity metadata font size for the context usage row", () => {
    expect(styles).toMatch(/\.context-usage\s*\{[^}]*font-size:\s*0\.85rem;/);
  });
});

describe("empty discussion states", () => {
  it("gives the activity and transcript messages the same neutral treatment", () => {
    const activityEmptyRule = styles.match(/\.activity-empty\s*\{([^}]*)\}/)?.[1] ?? "";
    const discussionEmptyRule =
      discussionStyles.match(/\.discussion-empty\s*\{([^}]*)\}/)?.[1] ?? "";

    for (const rule of [activityEmptyRule, discussionEmptyRule]) {
      expect(rule).toMatch(/text-align:\s*center;/);
      expect(rule).toMatch(/padding:\s*3rem\s+1rem;/);
      expect(rule).toMatch(/color:\s*var\(--aqa-ink-subtle\);/);
      expect(rule).not.toContain("font-style");
    }
  });
});

describe("bottom activity disclosure", () => {
  it("uses the standard box outline without a special accent top edge", () => {
    const panelRule = styles.match(/\.activity-log-panel\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(panelRule).toMatch(/border:\s*1px solid var\(--aqa-border\);/);
    expect(panelRule).not.toContain("color-mix");
    expect(panelRule).not.toContain("border-top-color");
  });
});

describe("discussion material divider", () => {
  it("shows a subtle divider at rest and expands it for interaction", () => {
    expect(styles).toMatch(
      /\.material-separator::before\s*\{[^}]*width:\s*1px;[^}]*background:\s*var\(--aqa-border\);/,
    );
    expect(styles).toMatch(
      /\.material-separator:hover::before,[\s\S]*?\.material-separator:active::before\s*\{[^}]*width:\s*4px;[^}]*background:\s*var\(--aqa-aqua\);/,
    );
  });
});

describe("discussion note treatment", () => {
  it("uses aquatic surfaces and the shared left-aligned secondary action", () => {
    const noteRule = discussionStyles.match(/\n\.message-note\s*\{([^}]*)\}/)?.[1] ?? "";
    const noteButtonRule =
      discussionStyles.match(/\.ds-button\.note-add-btn\s*\{([^}]*)\}/)?.[1] ?? "";
    const noteEditorRule = discussionStyles.match(/\.note-editor\s*\{([^}]*)\}/)?.[1] ?? "";

    expect(noteRule).toMatch(/background:\s*var\(--aqa-surface-raised\);/);
    expect(noteRule).toMatch(/border:\s*1px solid var\(--aqa-aqua\);/);
    expect(noteButtonRule).toMatch(/justify-content:\s*flex-start;/);
    expect(noteEditorRule).toMatch(/background:\s*var\(--aqa-surface-raised\);/);
    expect(noteEditorRule).toMatch(/border:\s*1px solid var\(--aqa-aqua\);/);
    expect(discussionStyles).not.toContain("168, 85, 247");
    expect(discussionStyles).not.toContain("192, 132, 252");
  });
});

describe("perspective writing outline", () => {
  it("gives writing perspective rows the same aqua outline as synthesis", () => {
    const perspectiveRule = styles.match(/\.agent-status-row\.is-writing\s*\{([^}]*)\}/)?.[1] ?? "";
    const synthesisRule =
      styles.match(/\.synthesis-status-row\.is-writing\s*\{([^}]*)\}/)?.[1] ?? "";

    expect(perspectiveRule).toMatch(/border-top:\s*1px\s+solid\s+var\(--aqa-aqua\);/);
    expect(perspectiveRule).toMatch(/border-right:\s*1px\s+solid\s+var\(--aqa-aqua\);/);
    expect(perspectiveRule).toMatch(/border-bottom:\s*1px\s+solid\s+var\(--aqa-aqua\);/);
    expect(synthesisRule).toMatch(/border-color:\s*var\(--aqa-aqua\);/);
  });
});

describe("discussion material reading boundary", () => {
  it("stretches the material pane to the activity workspace height", () => {
    expect(styles).toMatch(/\.discussion-layout\s*\{[^}]*align-items:\s*stretch;/);
    expect(styles).toMatch(
      /\.discussion-layout\s*>\s*\.material-panel\s*\{[^}]*align-self:\s*stretch;[^}]*max-height:\s*none;/,
    );
    expect(styles).toMatch(
      /\.discussion-layout\.is-material-collapsed\s*>\s*\.material-rail\s*\{[^}]*align-self:\s*stretch;[^}]*max-height:\s*none;/,
    );
    expect(styles).toMatch(
      /\.discussion-layout\.is-mobile-stack\s*>\s*\.material-panel\s*\{[^}]*contain:\s*none;/,
    );
  });

  it("lets the right discussion workspace grow while keeping transcript scrolling local", () => {
    const workspaceRule = styles.match(/\.discussion-workspace\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(workspaceRule).toMatch(/min-height:\s*0;/);
    expect(workspaceRule).toMatch(/max-height:\s*none;/);
    expect(workspaceRule).toMatch(/overflow:\s*visible;/);
    expect(workspaceRule).not.toMatch(/overflow-y:\s*auto/);
  });

  it("uses a fixed citation-number gutter and balanced paragraph dividers", () => {
    const numberedLineRule = styles.match(/\.material-numbered-line\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(numberedLineRule).toMatch(/grid-template-columns:\s*4\.75rem\s+minmax\(0,\s*1fr\);/);
    expect(numberedLineRule).not.toMatch(/border-bottom:/);
    expect(styles).toMatch(
      /\.material-paragraph-break\s*\{[^}]*height:\s*0;[^}]*margin:\s*0\.6rem\s+0\.35rem;[^}]*border-top:\s*1px solid var\(--aqa-material-divider\);/,
    );
  });
});

describe("discussion transcript overflow boundaries", () => {
  it("keeps horizontal scrolling out of the rounded transcript container", () => {
    expect(styles).toMatch(
      /\.discussion-messages\s*\{[^}]*overflow-y:\s*auto;[^}]*overflow-x:\s*hidden;/,
    );
  });

  it("keeps the transcript scrollbar from interrupting its rounded outline", () => {
    expect(styles).toMatch(
      /\.discussion-messages\s*\{[^}]*scrollbar-color:\s*var\(--aqa-water-line\)\s+transparent;[^}]*scrollbar-width:\s*thin;/,
    );
    expect(styles).toMatch(
      /\.discussion-messages::-webkit-scrollbar-track,[\s\S]*?\.discussion-messages::-webkit-scrollbar-corner\s*\{[^}]*background:\s*transparent;/,
    );
  });

  it("gives populated transcripts a generous reading height before scrolling", () => {
    expect(styles).toMatch(
      /\.discussion-view\.has-discussion-content\s+\.discussion-messages\s*\{[^}]*min-height:\s*min\(32rem,\s*55dvh\);/,
    );
    expect(styles).toMatch(/\.discussion-messages\s*\{[^}]*max-height:\s*min\(72dvh,\s*44rem\);/);
  });

  it("retains inner horizontal scrolling for Markdown tables and code blocks", () => {
    expect(styles).toMatch(/\.md-content pre\s*\{[\s\S]*?overflow-x:\s*auto;/);
    expect(styles).toMatch(/\.md-content table\s*\{[\s\S]*?overflow-x:\s*auto;/);
  });
});

describe("Local AI launch-setting symmetry", () => {
  it("gives both launch settings matching recessed cards and aligned rows", () => {
    expect(styles).toMatch(
      /\.local-ai-launch-settings\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
    );
    expect(styles).toMatch(
      /\.ds-card--recessed\s*\{[^}]*background:\s*var\(--aqa-surface-recessed\);/,
    );
    expect(styles).toMatch(
      /\.local-ai-field\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*min-height:\s*10rem;/,
    );
    expect(styles).toMatch(
      /\.local-ai-mtp-field\s+\.checkbox\s*\{[^}]*align-items:\s*center;[^}]*align-self:\s*stretch;[^}]*width:\s*100%;[^}]*min-height:\s*2\.4rem;/,
    );
    expect(styles).toMatch(/\.ds-control\s*\{[^}]*min-height:\s*var\(--aqa-control-height\);/);
  });
});

describe("Local AI maintenance spacing", () => {
  it("aligns runtime action blocks in columns and stacks them on narrow screens", () => {
    expect(styles).toMatch(
      /\.local-ai-runtime-actions\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*760px\)\s*\{[\s\S]*?\.local-ai-runtime-actions\s*\{[^}]*grid-template-columns:\s*1fr;/,
    );
  });

  it("separates Technical Details from the runtime actions", () => {
    expect(styles).toMatch(
      /\.local-ai-diagnostics\s*\{[^}]*margin-top:\s*0\.85rem;[^}]*padding:\s*0\.75rem;/,
    );
  });
});

describe("AQA brand animation continuity", () => {
  it("keeps one fixed CSS timeline so playback-rate changes preserve its phase", () => {
    const brandRule = styles.match(/\.aqa-brand\s*\{([^}]*)\}/)?.[1] ?? "";

    expect(brandRule).toMatch(/--aqa-wave-duration:\s*3\.9s;/);
    expect(brandRule).toMatch(/--aqa-wave-step:\s*0\.25s;/);
    expect(brandRule).not.toMatch(/transition:[\s\S]*--aqa-wave-duration/);
    expect(styles).not.toMatch(
      /\.aqa-brand\[data-aqa-generating="true"\]\s*\{[^}]*--aqa-wave-(?:duration|step)/,
    );
  });
});

describe("notice and provider-history presentation", () => {
  it("distinguishes notice tones while keeping shared geometry", () => {
    expect(styles).toMatch(
      /\.notice-banner\s*\{[^}]*border:\s*var\(--aqa-border-width\) solid var\(--aqa-notice-border\);[^}]*background:\s*var\(--aqa-state-info-bg\);[^}]*color:\s*var\(--aqa-ink\);/,
    );
    expect(styles).toMatch(/\.notice-banner--success\s*\{[^}]*var\(--aqa-state-success-bg\);/);
    expect(styles).toMatch(
      /\.notice-banner--warning,[\s\S]*?\.notice-banner--error\s*\{[^}]*var\(--aqa-state-warning-bg\);/,
    );
    expect(styles).not.toMatch(/\.error-banner\s*\{[^}]*aqa-state-danger/);
    expect(styles).not.toMatch(/\.export-notice\s*\{[^}]*aqa-state-success/);
    expect(styles).not.toMatch(/\.sessions-error\s*\{[^}]*aqa-state-danger/);
    expect(styles).toMatch(/\.blocked-action-hint\s*\{[^}]*color:\s*var\(--aqa-state-danger\);/);
    expect(styles).not.toMatch(/\.blocked-action-hint--(?:neutral|error)/);
    expect(styles).not.toMatch(/\.local-ai-runtime-hint\s*\{[^}]*color:/);
  });

  it("presents provider history as a contained, horizontally safe table", () => {
    expect(styles).toMatch(
      /\.provider-history\s*\{[^}]*background:\s*var\(--aqa-surface-raised\);[^}]*border:\s*1px solid var\(--aqa-border\);[^}]*overflow:\s*hidden;/,
    );
    expect(styles).toMatch(/\.provider-history-table-wrap\s*\{[^}]*overflow-x:\s*auto;/);
    expect(styles).toMatch(/\.provider-history table\s*\{[^}]*border-collapse:\s*collapse;/);
  });
});

describe("responsive UI consistency contracts", () => {
  it("uses a compact two-column options form that collapses to one column", () => {
    expect(styles).toMatch(
      /\.agent-config-advanced\s*>\s*\.agent-controls,[\s\S]*?\.synthesis-config-controls\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*768px\)\s*\{[\s\S]*?\.agent-config-advanced\s*>\s*\.agent-controls,[\s\S]*?\.synthesis-config-controls\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/,
    );
  });

  it("keeps Prepare session inputs equal initially with self-contained native scrolling", () => {
    expect(styles).toMatch(/\.setup-session-input\s*\{[^}]*min-height:\s*8\.5rem;/);
    expect(styles).toMatch(/\.followup-area textarea\s*\{[^}]*min-height:\s*8\.5rem;/);
    expect(styles).toMatch(
      /\.setup-group textarea::-webkit-scrollbar,[\s\S]*?\.rm-textarea::-webkit-scrollbar\s*\{[^}]*width:\s*0\.65rem;/,
    );
    expect(styles).toContain(".setup-group textarea::-webkit-scrollbar-track");
    expect(styles).toContain(".setup-group textarea::-webkit-scrollbar-corner");
    expect(styles).toMatch(
      /\.setup-group textarea::-webkit-resizer,[\s\S]*?\.rm-textarea::-webkit-resizer\s*\{[^}]*background-color:\s*transparent;/,
    );
  });

  it("keeps the native resize grip transparent over focused textarea borders", () => {
    const resizerRule =
      styles.match(
        /\.setup-group textarea::-webkit-resizer,[\s\S]*?\.rm-textarea::-webkit-resizer\s*\{([^}]*)\}/,
      )?.[1] ?? "";
    expect(resizerRule).toMatch(/background-color:\s*transparent;/);
    expect(resizerRule).not.toMatch(/background-color:\s*var\(--aqa-surface-recessed\);/);
  });

  it("styles text inputs in setup with the same aquatic control treatment", () => {
    expect(styles).toMatch(
      /\.ds-control\s*\{[^}]*border:\s*var\(--aqa-border-width\) solid var\(--aqa-border\);[^}]*background:\s*var\(--aqa-surface-recessed\);[^}]*color:\s*var\(--aqa-ink\);/,
    );
    expect(styles).not.toMatch(/\.setup-group (?:input|textarea|select)\s*\{[^}]*font-size:/);
  });

  it("shares native textarea scrollbars and resize corners across setup, discuss, and configuration", () => {
    for (const selector of [".followup-area textarea", ".note-editor textarea", ".rm-textarea"]) {
      expect(styles).toContain(`${selector}::-webkit-scrollbar`);
      expect(styles).toContain(`${selector}::-webkit-resizer`);
    }
  });

  it("uses one standard control geometry for navigation, text actions, and locale selection", () => {
    expect(styles).toMatch(/--aqa-control-height:\s*2\.25rem;/);
    expect(styles).toMatch(/--aqa-control-height-touch:\s*2\.5rem;/);
    expect(styles).toMatch(/--aqa-control-padding-block:\s*0\.375rem;/);
    expect(styles).toMatch(/--aqa-control-padding-inline:\s*0\.75rem;/);

    for (const selector of [".view-tab", ".ds-button"]) {
      expect(hasControlGeometry(selector)).toBe(true);
    }
    expect(styles).toMatch(
      /\.locale-switcher select\s*\{[^}]*min-height:\s*2\.25rem;[^}]*padding:\s*var\(--aqa-control-padding-block\)\s+1\.75rem\s+var\(--aqa-control-padding-block\)\s+var\(--aqa-control-padding-inline\);/,
    );
  });

  it("keeps the locale control on the aquatic design tokens", () => {
    expect(styles).toMatch(
      /\.locale-switcher select\s*\{[^}]*border:[^;]*var\(--aqa-border\);[^}]*background:\s*var\(--aqa-surface-recessed\);[^}]*color:\s*var\(--aqa-ink\);/,
    );
    expect(styles).not.toMatch(/var\(--(?:border|surface|accent),/);
  });

  it("keeps the System language control compact and subordinate on narrow screens", () => {
    expect(styles).toMatch(
      /\.system-language\s*\{[^}]*background:\s*var\(--aqa-surface-raised\);[^}]*border:\s*1px solid var\(--aqa-border\);[^}]*border-radius:\s*var\(--aqa-radius-card\);/,
    );
    expect(styles).toMatch(
      /\.system-language-header\s*\{[^}]*display:\s*flex;[^}]*justify-content:\s*space-between;/,
    );
    expect(styles).toMatch(
      /\.system-language-header h2\s*\{[^}]*font-size:\s*1\.125rem;[^}]*font-weight:\s*700;/,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*640px\)[\s\S]*?\.system-language-header\s*\{[^}]*flex-direction:\s*column;/,
    );
  });

  it("uses a two-column narrow navigation without page-level overflow", () => {
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*640px\)[\s\S]*?\.primary-navigation-main\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*320px\)[\s\S]*?\.primary-navigation-main\s*>\s*\.configuration-menu\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/,
    );
  });

  it("gives prompt configuration tables their own scroll boundary", () => {
    expect(styles).toMatch(
      /\.pcm-table-scroll\s*\{[^}]*max-width:\s*100%;[^}]*overflow-x:\s*auto;/,
    );
    expect(styles).not.toMatch(
      /@media\s*\(max-width:\s*760px\)[\s\S]*?\.pcm-section\s*\{[^}]*overflow-x:\s*auto;/,
    );
  });

  it("gives System editor modals one padded scroll body and a fixed action footer", () => {
    expect(styles).toMatch(
      /\.modal-content--editor > \.ds-editor-dialog-body\s*\{[^}]*min-height:\s*0;[^}]*flex:\s*1 1 auto;[^}]*overflow-y:\s*auto;[^}]*padding:\s*var\(--aqa-space-2\)\s+1\.75rem\s+var\(--aqa-space-5\);/,
    );
    expect(styles).toMatch(
      /\.modal-content--editor > \.ds-dialog-footer\s*\{[^}]*flex:\s*0 0 auto;[^}]*padding:\s*var\(--aqa-space-3\)\s+var\(--aqa-space-6\)\s+var\(--aqa-space-5\);[^}]*border-top:\s*var\(--aqa-border-width\) solid var\(--aqa-border\);/,
    );
    expect(styles).not.toContain(".rm-modal-actions");
  });

  it("uses divider-separated Setup inputs and preserves focus clearance in every System editor", () => {
    expect(styles).toMatch(
      /\.pcm-input-item\s*\{[^}]*padding:\s*0\.9rem\s+0;[^}]*border-top:\s*1px solid var\(--aqa-border\);/,
    );
    expect(styles).not.toContain(".pcm-input-card {");
    expect(styles).toMatch(
      /\.ds-control:focus-visible,[\s\S]*?outline:\s*var\(--aqa-focus-width\) solid var\(--aqa-focus-color\);/,
    );
    expect(styles).toMatch(
      /@media\s*\(max-width:\s*760px\)[\s\S]*?\.pcm-input-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/,
    );
  });

  it("responds to the discussion workspace rather than only the viewport", () => {
    expect(styles).toMatch(
      /\.discussion-workspace\s*\{[^}]*container-type:\s*inline-size;[^}]*container-name:\s*discussion-workspace;/,
    );
    expect(styles).toMatch(/@container\s+discussion-workspace\s*\(max-width:\s*520px\)/);
  });
});

describe("System editor hierarchy", () => {
  it("keeps primary session instructions and Setup Inputs as flat sections", () => {
    expect(styles).toMatch(
      /\.pcm-role-section,[\s\S]*?\.pcm-session-instructions\s*\{[^}]*border-top:\s*1px solid var\(--aqa-border\);/,
    );
    expect(styles).not.toContain(".pcm-role-fieldset");
    expect(styles).toMatch(/\.pcm-input-section h3\s*\{[^}]*font-size:\s*1\.05rem;/);
    expect(styles).toMatch(
      /\.pcm-role-section h3,[\s\S]*?\.pcm-session-instructions > label\s*\{[^}]*font-size:\s*1\.05rem;/,
    );
  });

  it("uses a single-line normal-weight material-template checkbox and metadata IDs", () => {
    const checkboxRule =
      styles.match(/\.pcm-input-grid \.pcm-material-context-toggle\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(checkboxRule).toMatch(/flex-direction:\s*row;/);
    expect(checkboxRule).toMatch(/align-items:\s*center;/);
    expect(checkboxRule).toMatch(/font-weight:\s*400;/);
    expect(styles).toMatch(
      /\.pcm-role-empty\s*\{[^}]*color:\s*var\(--aqa-ink-subtle\);[^}]*font-size:\s*0\.85rem;/,
    );
    expect(styles).toMatch(/\.pcm-immutable-id\s*\{[^}]*font-family:\s*var\(--aqa-font-mono\);/);
  });
});
