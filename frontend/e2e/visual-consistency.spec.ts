import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";
import type { Locator, Page } from "@playwright/test";

type ScenarioCoverage =
  | {
      kind: "rendered-browser";
      harness: "mocked" | "product";
      source: string;
      locales: readonly ("de" | "en")[];
      viewports: "matrix" | "desktop" | "narrow" | "desktop-and-narrow";
    }
  | { kind: "component-test"; source: string }
  | { kind: "catalog-only"; reason: string };

/**
 * This is an evidence catalogue, not proof that every listed state is rendered
 * by this file. Each entry states whether its evidence comes from an actual
 * browser render, a component test, or is only a documented coverage gap.
 */
type VisualScenario = {
  id: string;
  view:
    "setup" | "discussion" | "sessions" | "local-ai" | "network" | "roles" | "preview" | "system";
  state: string;
  fixture: "default" | "interaction";
  coverage: ScenarioCoverage;
};

const defaultMatrixCoverage = {
  kind: "rendered-browser",
  harness: "mocked",
  source: "visual-consistency.spec.ts default-state viewport matrix",
  locales: ["de", "en"],
  viewports: "matrix",
} as const satisfies ScenarioCoverage;

export const visualScenarioCatalog: readonly VisualScenario[] = [
  {
    id: "prepare-ready",
    view: "setup",
    state: "ready",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "prepare-disclosures",
    view: "setup",
    state: "expanded disclosures and options",
    fixture: "interaction",
    coverage: { kind: "component-test", source: "Layout.test.tsx setup disclosure behavior" },
  },
  {
    id: "prepare-validation",
    view: "setup",
    state: "validation",
    fixture: "interaction",
    coverage: {
      kind: "component-test",
      source: "Layout.test.tsx required-field validation behavior",
    },
  },
  {
    id: "discussion-empty",
    view: "discussion",
    state: "empty",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "discussion-populated",
    view: "discussion",
    state: "populated",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "product",
      source: "product.spec.ts discussion lifecycle",
      locales: ["de", "en"],
      viewports: "desktop",
    },
  },
  {
    id: "discussion-streaming",
    view: "discussion",
    state: "streaming and activity",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "product",
      source: "product.spec.ts discussion lifecycle and Activity controls",
      locales: ["de", "en"],
      viewports: "desktop",
    },
  },
  {
    id: "sessions-empty",
    view: "sessions",
    state: "empty",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "sessions-selected",
    view: "sessions",
    state: "selected session",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "product",
      source: "product.spec.ts session hydration lifecycle",
      locales: ["de", "en"],
      viewports: "desktop",
    },
  },
  {
    id: "sessions-loading-error",
    view: "sessions",
    state: "initial loading and load failure",
    fixture: "interaction",
    coverage: {
      kind: "catalog-only",
      reason: "No browser or component test currently renders the initial Sessions load failure.",
    },
  },
  {
    id: "local-ai-not-installed",
    view: "local-ai",
    state: "model selection",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "local-ai-transfer-ready-error",
    view: "local-ai",
    state: "transfer, ready, and error",
    fixture: "interaction",
    coverage: {
      kind: "component-test",
      source: "LocalAI.test.tsx lifecycle and transfer states",
    },
  },
  {
    id: "network-populated",
    view: "network",
    state: "populated table",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "network-editor-layout",
    view: "network",
    state: "create editor layout and fixed footer",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "mocked",
      source: "responsive.spec.ts narrow editor-dialog matrix",
      locales: ["de", "en"],
      viewports: "narrow",
    },
  },
  {
    id: "network-validation",
    view: "network",
    state: "long editor content and validation",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "mocked",
      source: "responsive.spec.ts External AI 320x480 editor test",
      locales: ["de"],
      viewports: "narrow",
    },
  },
  {
    id: "network-confirmation",
    view: "network",
    state: "delete confirmation and focus restoration",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "product",
      source: "product.spec.ts host dialog flow",
      locales: ["de", "en"],
      viewports: "desktop",
    },
  },
  {
    id: "roles-populated",
    view: "roles",
    state: "populated table",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "roles-editor-layout",
    view: "roles",
    state: "editor layout",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "mocked",
      source: "responsive.spec.ts narrow editor-dialog matrix",
      locales: ["de", "en"],
      viewports: "narrow",
    },
  },
  {
    id: "roles-confirmation",
    view: "roles",
    state: "validation, saving, and delete confirmation",
    fixture: "interaction",
    coverage: {
      kind: "component-test",
      source: "RoleManager.test.tsx editor and confirmation behavior",
    },
  },
  {
    id: "preview-output",
    view: "preview",
    state: "rendered prompt",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "preview-async-failure",
    view: "preview",
    state: "changed selection, loading, failure, and retry",
    fixture: "interaction",
    coverage: {
      kind: "component-test",
      source: "PromptPreview.test.tsx asynchronous preview behavior",
    },
  },
  {
    id: "system-populated",
    view: "system",
    state: "configuration tables",
    fixture: "default",
    coverage: defaultMatrixCoverage,
  },
  {
    id: "system-editor-layout",
    view: "system",
    state: "Session Type, Global Prompt, and Quick Action editor layouts",
    fixture: "interaction",
    coverage: {
      kind: "rendered-browser",
      harness: "mocked",
      source: "responsive.spec.ts narrow editor-dialog matrix",
      locales: ["de", "en"],
      viewports: "narrow",
    },
  },
  {
    id: "system-editor-behavior",
    view: "system",
    state: "editor validation, checkbox, saving, and confirmation",
    fixture: "interaction",
    coverage: {
      kind: "component-test",
      source: "PromptConfigurationManager.test.tsx and QuickActionsManager.test.tsx",
    },
  },
];

export const viewportMatrix = [
  { width: 320, height: 800 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 640, height: 800 },
  { width: 768, height: 720 },
  { width: 768, height: 480 },
  { width: 1024, height: 768 },
  { width: 1025, height: 768 },
  { width: 1440, height: 900 },
] as const;

const views = [
  "setup",
  "discussion",
  "sessions",
  "local-ai",
  "network",
  "roles",
  "preview",
  "system",
] as const;
const configurationViews = new Set<string>(["local-ai", "network", "roles", "preview", "system"]);

async function navigateTo(page: Page, view: (typeof views)[number]): Promise<void> {
  if (configurationViews.has(view)) await page.locator("[data-configure-menu]").click();
  await page.locator(`button[data-view="${view}"]`).click();
  await expect(page.locator(`button[data-view="${view}"]`)).toHaveAttribute("aria-current", "page");
}

const familyProperties = [
  "minHeight",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontFamily",
  "fontSize",
  "fontWeight",
  "borderTopWidth",
  "borderTopColor",
  "borderTopLeftRadius",
  "backgroundColor",
  "color",
] as const;

type FamilyStyle = Record<(typeof familyProperties)[number], string>;

async function styleOf(locator: Locator): Promise<FamilyStyle> {
  return locator.evaluate((element, properties) => {
    const style = getComputedStyle(element);
    return Object.fromEntries(properties.map((property) => [property, style[property]]));
  }, familyProperties) as Promise<FamilyStyle>;
}

async function stylesAcrossViews(
  page: Page,
  selector: string,
  viewNames: readonly (typeof views)[number][],
): Promise<FamilyStyle[]> {
  const styles: FamilyStyle[] = [];
  for (const view of viewNames) {
    await navigateTo(page, view);
    const control = page.locator(selector).filter({ visible: true }).first();
    await expect(control, `${selector} should be visible in ${view}`).toBeVisible();
    styles.push(await styleOf(control));
  }
  return styles;
}

function expectFamilyStyles(styles: readonly FamilyStyle[], family: string): void {
  expect(styles.length, `${family} needs at least two representatives`).toBeGreaterThan(1);
  expect(styles, `${family} members must share their canonical treatment`).toEqual(
    Array.from({ length: styles.length }, () => styles[0]),
  );
}

type InteractiveFamily = {
  contract: "design-system" | "specialized";
  reason: string;
  selector: string;
};

const recognizedInteractiveFamilies: readonly InteractiveFamily[] = [
  {
    selector: ".ds-button",
    contract: "design-system",
    reason: "canonical text action",
  },
  {
    selector: ".ds-icon-button",
    contract: "design-system",
    reason: "canonical icon-only action",
  },
  { selector: ".aqa-brand", contract: "specialized", reason: "animated product mark" },
  { selector: ".view-tab", contract: "specialized", reason: "primary navigation tab" },
  {
    selector: ".configuration-menu-item",
    contract: "specialized",
    reason: "configuration-menu navigation item",
  },
  {
    selector: ".agent-config-options-toggle",
    contract: "specialized",
    reason: "setup disclosure",
  },
  { selector: ".session-type-card", contract: "specialized", reason: "compound radio card" },
  {
    selector: ".ai-readiness-choice",
    contract: "specialized",
    reason: "compound AI-source radio card",
  },
  {
    selector: ".material-collapse-btn",
    contract: "specialized",
    reason: "material-pane disclosure",
  },
  {
    selector: ".material-rail-toggle",
    contract: "specialized",
    reason: "narrow material rail",
  },
  {
    selector: ".activity-log-toggle",
    contract: "specialized",
    reason: "activity disclosure",
  },
  {
    selector: ".activity-log-clear-btn",
    contract: "specialized",
    reason: "activity-log utility action",
  },
  {
    selector: ".message-bezugspunkt-btn",
    contract: "specialized",
    reason: "message reference chip",
  },
  {
    selector: ".message-note",
    contract: "specialized",
    reason: "keyboard-operable message note",
  },
  {
    selector: ".quick-prompt-chip",
    contract: "specialized",
    reason: "prompt insertion chip",
  },
  {
    selector: ".local-ai-model-card",
    contract: "specialized",
    reason: "compound model radio card",
  },
  {
    selector: ".nc-host-preference-toggle",
    contract: "specialized",
    reason: "pressed-state favorite star",
  },
] as const;

const recognizedInteractiveSelectors = recognizedInteractiveFamilies.map(
  ({ selector }) => selector,
);

test("visual scenario catalogue identifies rendered, component, and catalog-only evidence", () => {
  expect(new Set(visualScenarioCatalog.map((scenario) => scenario.id)).size).toBe(
    visualScenarioCatalog.length,
  );
  for (const view of views) {
    const scenarios = visualScenarioCatalog.filter((scenario) => scenario.view === view);
    expect(
      scenarios.length,
      `${view} needs default and interaction entries`,
    ).toBeGreaterThanOrEqual(2);
    expect(scenarios.some((scenario) => scenario.fixture === "default")).toBe(true);
    expect(scenarios.some((scenario) => scenario.fixture === "interaction")).toBe(true);
    expect(
      scenarios.some((scenario) => scenario.coverage.kind === "rendered-browser"),
      `${view} needs at least one actually rendered browser state`,
    ).toBe(true);
  }
  expect(viewportMatrix).toHaveLength(9);
  const rendered = visualScenarioCatalog.filter(
    (scenario) => scenario.coverage.kind === "rendered-browser",
  );
  expect(rendered).not.toHaveLength(0);
  for (const scenario of rendered) {
    if (scenario.coverage.kind !== "rendered-browser") continue;
    expect(scenario.coverage.source).toMatch(/\.spec\.ts/);
    expect(scenario.coverage.locales.length).toBeGreaterThan(0);
  }
  const componentOnly = visualScenarioCatalog.filter(
    (scenario) => scenario.coverage.kind === "component-test",
  );
  expect(componentOnly).not.toHaveLength(0);
  for (const scenario of componentOnly) {
    if (scenario.coverage.kind !== "component-test") continue;
    expect(scenario.coverage.source).toMatch(/\.test\.tsx?/);
  }
  const catalogOnly = visualScenarioCatalog.filter(
    (scenario) => scenario.coverage.kind === "catalog-only",
  );
  expect(catalogOnly).not.toHaveLength(0);
  for (const scenario of catalogOnly) {
    if (scenario.coverage.kind !== "catalog-only") continue;
    expect(scenario.coverage.reason.length).toBeGreaterThan(20);
  }
  expect(
    recognizedInteractiveFamilies.filter(({ contract }) => contract === "design-system"),
  ).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ selector: ".ds-button" }),
      expect.objectContaining({ selector: ".ds-icon-button" }),
    ]),
  );
  expect(
    recognizedInteractiveFamilies.filter(({ contract }) => contract === "specialized"),
  ).not.toHaveLength(0);
  expect(recognizedInteractiveFamilies.every(({ reason }) => reason.length > 0)).toBe(true);
});

// The full nine-viewport × two-locale matrix is kept as a fast DOM contract;
// the responsive suite owns pixel baselines, avoiding 144 duplicate images.
for (const language of ["de", "en"] as const) {
  for (const viewport of viewportMatrix) {
    test(`${language}: visual-family markup is complete at ${viewport.width}x${viewport.height}`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await setLanguage(page, language);
      for (const view of views) {
        await navigateTo(page, view);
        await expectNoGlobalHorizontalOverflow(page);
        const unknown = await page
          .locator("button:visible, [role='button']:visible, [role='radio']:visible")
          .evaluateAll(
            (elements, selectors) =>
              elements
                .filter((element) => !selectors.some((selector) => element.matches(selector)))
                .map((element) => ({
                  text: (element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 80),
                  className: element.className,
                })),
            recognizedInteractiveSelectors,
          );
        expect(unknown, `${view} has an uncatalogued interactive element`).toEqual([]);
      }
    });
  }
}

test("canonical design-system primary, secondary, and navigation families share computed styles", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");

  expectFamilyStyles(
    await stylesAcrossViews(page, ".ds-button--primary", ["network", "roles", "system"]),
    "primary button",
  );
  expectFamilyStyles(
    await stylesAcrossViews(page, ".ds-button--secondary", ["network", "roles", "system"]),
    "secondary button",
  );

  const navigation = (await page.locator(".primary-navigation .view-tab").evaluateAll(
    (elements, properties) =>
      elements
        .filter(
          (element) => element.tagName === "BUTTON" && !element.hasAttribute("data-configure-menu"),
        )
        .map((element) => {
          const style = getComputedStyle(element);
          return Object.fromEntries(properties.map((property) => [property, style[property]]));
        }),
    familyProperties,
  )) as FamilyStyle[];
  expectFamilyStyles(navigation, "primary navigation");
});

test("disclosure, form, and scrollbar families retain shared browser chrome", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");

  const disclosures = await page.locator(".agent-config-options-toggle").evaluateAll((elements) =>
    elements.map((element) => {
      const style = getComputedStyle(element);
      return [style.minHeight, style.borderRadius, style.color, style.backgroundColor];
    }),
  );
  expect(new Set(disclosures.map((style) => JSON.stringify(style))).size).toBe(1);

  await page.locator("button[aria-controls='setup-research-material-context']").click();
  const setupField = page.locator(".setup-group textarea").first();
  await setupField.fill("Example material");
  await setupField.blur();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(250);
  const setupStyle = await styleOf(setupField);
  const setupScrollbar = await setupField.evaluate((element) => {
    const style = getComputedStyle(element, "::-webkit-scrollbar-thumb");
    return {
      width: getComputedStyle(element).scrollbarWidth,
      thumb: style.backgroundColor,
      radius: style.borderRadius,
    };
  });
  await navigateTo(page, "network");
  await page.locator(".nc-header .ds-button--primary").click();
  const modalStyle = await styleOf(page.locator(".nc-modal .ds-control").first());
  for (const property of [
    "fontFamily",
    "fontSize",
    "borderTopWidth",
    "borderTopColor",
    "borderTopLeftRadius",
    "backgroundColor",
    "color",
  ] as const) {
    expect(modalStyle[property], `form treatment differs for ${property}`).toBe(
      setupStyle[property],
    );
  }

  const scrollbars = await page
    .locator(".nc-modal .ds-control")
    .first()
    .evaluate((element) => {
      const style = getComputedStyle(element, "::-webkit-scrollbar-thumb");
      return {
        width: getComputedStyle(element).scrollbarWidth,
        thumb: style.backgroundColor,
        radius: style.borderRadius,
      };
    });
  expect(scrollbars).toEqual(setupScrollbar);
});

test("Prompt Preview selects retain the canonical shared-control contract", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");

  const canonical = page.locator("#setup-material-type");
  const canonicalStyle = await styleOf(canonical);
  await navigateTo(page, "preview");
  const previewSelect = page.locator("#template-select");
  const previewStyle = await styleOf(previewSelect);
  for (const property of [
    "fontFamily",
    "fontSize",
    "paddingTop",
    "paddingRight",
    "borderTopWidth",
    "borderTopColor",
    "borderTopLeftRadius",
    "backgroundColor",
    "color",
  ] as const) {
    expect(previewStyle[property], `Prompt Preview differs for ${property}`).toBe(
      canonicalStyle[property],
    );
  }

  await previewSelect.focus();
  await expect(previewSelect).toBeFocused();
  expect((await styleOf(previewSelect)).outlineStyle).not.toBe("none");
});

test("primary and secondary interaction states remain coherent", async ({ mockedPage: page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");

  await navigateTo(page, "network");
  const networkPrimary = page.locator(".nc-header .ds-button--primary");
  await networkPrimary.hover();
  await page.waitForTimeout(200);
  const primaryHover = await styleOf(networkPrimary);
  await navigateTo(page, "roles");
  const rolePrimary = page.locator(".rm-header .ds-button--primary");
  await rolePrimary.hover();
  await page.waitForTimeout(200);
  expect(await styleOf(rolePrimary)).toEqual(primaryHover);

  const roleSecondary = page.locator(".rm-header .ds-button--secondary").first();
  await roleSecondary.focus();
  const secondaryFocus = await roleSecondary.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outline: style.outline, outlineOffset: style.outlineOffset };
  });
  await navigateTo(page, "network");
  const networkSecondary = page.locator(".nc-table .ds-button--secondary").first();
  await networkSecondary.focus();
  expect(
    await networkSecondary.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outline: style.outline, outlineOffset: style.outlineOffset };
    }),
  ).toEqual(secondaryFocus);
});
