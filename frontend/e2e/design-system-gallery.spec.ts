import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";
import type { Locator, Page } from "@playwright/test";

const galleryPath = "/?gallery=components";
const galleryLocales = {
  de: {
    buttons: "Schaltflächen",
    fields: "Felder",
    feedback: "Statusmeldungen",
    appearance: "Darstellungsmodus",
    dialog: "Beispieldialog öffnen",
    layout: "Layoutmuster",
    selection: "Auswahlmuster",
    title: "AQA Designsystem",
    workflow: "Ablauf und Fortschritt",
    closeNotice: "Hinweis schließen",
    blockedAction: "Diese Aktion ist noch nicht verfügbar. Erfülle zuerst die Voraussetzung.",
  },
  en: {
    buttons: "Buttons",
    fields: "Fields",
    feedback: "Feedback",
    appearance: "Appearance Mode",
    dialog: "Open Example Dialog",
    layout: "Layout Patterns",
    selection: "Selection Patterns",
    title: "AQA Design System",
    workflow: "Workflow And Progress",
    closeNotice: "Close Notice",
    blockedAction: "This action is not available yet. Complete the prerequisite first.",
  },
} as const;

const galleryViewports = [
  { name: "desktop", size: { width: 1440, height: 900 } },
  {
    name: "320-CSS-pixel reflow proxy for 400% zoom",
    size: { width: 320, height: 800 },
  },
] as const;

async function openGallery(
  page: Page,
  language: keyof typeof galleryLocales,
  viewport: (typeof galleryViewports)[number]["size"],
): Promise<void> {
  await page.setViewportSize(viewport);
  await page.goto(galleryPath);
  await setLanguage(page, language);
  await expect(page.locator(".ds-gallery")).toBeVisible();
}

async function expectEquivalentComputedStyles(
  locators: Locator,
  properties: readonly string[],
): Promise<void> {
  const styles = await locators.evaluateAll(
    (elements, styleProperties) =>
      elements.map((element) => {
        const style = getComputedStyle(element);
        return Object.fromEntries(styleProperties.map((property) => [property, style[property]]));
      }),
    properties,
  );
  expect(styles.length).toBeGreaterThan(1);
  expect(styles).toEqual(Array.from({ length: styles.length }, () => styles[0]));
}

async function expectFieldRelationships(page: Page): Promise<void> {
  const describedInput = page.locator("#gallery-input");
  const descriptionId = await describedInput.getAttribute("aria-describedby");
  expect(descriptionId).toBeTruthy();
  await expect(page.locator(`[id=${JSON.stringify(descriptionId)}]`)).not.toBeEmpty();

  const invalidInput = page.locator("#gallery-invalid");
  const errorId = await invalidInput.getAttribute("aria-describedby");
  expect(errorId).toBeTruthy();
  await expect(invalidInput).toHaveAttribute("aria-invalid", "true");
  await expect(invalidInput).toHaveAttribute("required", "");
  await expect(page.locator(`[id=${JSON.stringify(errorId)}]`)).toHaveAttribute("role", "alert");
  await expect(page.locator(`label[for="gallery-invalid"]`)).toBeVisible();

  for (const id of [
    "gallery-input",
    "gallery-invalid",
    "gallery-select",
    "gallery-textarea",
    "gallery-disabled",
    "gallery-disabled-select",
  ]) {
    await expect(page.locator(`label[for="${id}"]`)).toBeVisible();
    await expect(page.locator(`#${id}`)).toBeVisible();
  }
}

async function expectControlGeometry(page: Page, narrow: boolean): Promise<void> {
  const intrinsicMediumControls = page.locator(
    ".ds-icon-button.ds-control--medium, input.ds-control--medium, select.ds-control--medium",
  );
  const intrinsicMediumHeights = await intrinsicMediumControls.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().height),
  );
  expect(intrinsicMediumHeights.length).toBeGreaterThan(5);
  expect(new Set(intrinsicMediumHeights)).toEqual(new Set(narrow ? [36, 40] : [36]));

  const mediumButtonHeights = await page
    .locator(".ds-button.ds-control--medium")
    .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(mediumButtonHeights.length).toBeGreaterThan(5);
  expect(new Set(mediumButtonHeights)).toEqual(new Set([narrow ? 40 : 36]));

  await expect(page.locator("select.ds-control--small")).toHaveCSS("height", "32px");
  const smallButtonHeights = await page
    .locator("button.ds-control--small")
    .evaluateAll((elements) => elements.map((element) => getComputedStyle(element).height));
  expect(new Set(smallButtonHeights)).toEqual(new Set([narrow ? "40px" : "32px"]));

  await expectEquivalentComputedStyles(page.locator("input.ds-control"), [
    "minHeight",
    "padding",
    "borderWidth",
    "borderRadius",
  ]);
  const iconGeometry = await page.locator(".ds-icon-button").evaluateAll((elements) =>
    elements.map((element) => {
      const bounds = element.getBoundingClientRect();
      return { height: bounds.height, width: bounds.width };
    }),
  );
  expect(iconGeometry.every(({ height, width }) => width >= height)).toBe(true);

  const textareaHeight = await page
    .locator("#gallery-textarea")
    .evaluate((element) => element.getBoundingClientRect().height);
  expect(textareaHeight).toBeGreaterThan(36);
}

async function expectKeyboardReachabilityAndFocus(page: Page): Promise<void> {
  const selector =
    '.ds-gallery a[href], .ds-gallery button:not(:disabled), .ds-gallery input:not(:disabled):not([type="radio"]), .ds-gallery input[type="radio"]:checked, .ds-gallery select:not(:disabled), .ds-gallery textarea:not(:disabled)';
  const expectedCount = await page.locator(selector).count();
  const reached = new Set<number>();

  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (let index = 0; index < expectedCount; index += 1) {
    await page.keyboard.press("Tab");
    const focusState = await page.evaluate((interactiveSelector) => {
      const controls = Array.from(document.querySelectorAll(interactiveSelector));
      const activeElement = document.activeElement;
      const style = activeElement instanceof HTMLElement ? getComputedStyle(activeElement) : null;
      return {
        index: controls.indexOf(activeElement as Element),
        outlineStyle: style?.outlineStyle ?? "none",
        outlineWidth: style?.outlineWidth ?? "0px",
      };
    }, selector);
    expect(focusState.index, "Tab must reach only enabled gallery controls").toBeGreaterThanOrEqual(
      0,
    );
    expect(focusState.outlineStyle).not.toBe("none");
    expect(Number.parseFloat(focusState.outlineWidth)).toBeGreaterThanOrEqual(2);
    reached.add(focusState.index);
  }
  expect(reached.size).toBe(expectedCount);
}

for (const language of ["de", "en"] as const) {
  for (const viewport of galleryViewports) {
    test(`${language}: gallery contracts render at ${viewport.name}`, async ({
      mockedPage: page,
    }) => {
      await openGallery(page, language, viewport.size);
      const copy = galleryLocales[language];

      await expect(page.getByRole("heading", { level: 1, name: copy.title })).toBeVisible();
      await expect(page.getByRole("region", { name: copy.buttons })).toBeVisible();
      await expect(page.getByRole("region", { name: copy.fields })).toBeVisible();
      await expect(page.getByRole("region", { name: copy.selection })).toBeVisible();
      await expect(page.getByRole("region", { name: copy.workflow })).toBeVisible();
      await expect(page.getByRole("region", { name: copy.layout })).toBeVisible();
      await expect(page.locator(".ds-page-header")).toHaveCount(1);
      await expect(page.locator(".ds-section-header")).toHaveCount(7);
      await expect(page.locator(".ds-card")).toHaveCount(7);
      expect(await page.locator(".ds-action-group").count()).toBeGreaterThan(9);
      const feedback = page.getByRole("region", { name: copy.feedback, exact: true });
      await expect(feedback).toBeVisible();
      await expect(feedback.locator(".pcm-badge")).toHaveCount(3);
      for (const origin of ["shipped-default", "shipped-modified", "custom"]) {
        await expect(feedback.locator(`.pcm-badge--${origin}`)).toBeVisible();
      }
      await expect(feedback.locator(".notice-banner")).toHaveCount(6);
      await expect(feedback.locator(".notice-banner__dismiss")).toHaveCount(4);
      await expect(
        feedback.locator(".notice-banner--info .notice-banner__icon").first(),
      ).toHaveText("info");
      await expect(feedback.locator(".blocked-action-hint")).toHaveCount(1);
      await expect(feedback.getByRole("alert")).toHaveCount(1);
      await expect(feedback.getByRole("status")).toHaveCount(5);
      await expect(page.locator(".ds-choice-indicator")).toHaveCount(3);
      await expect(page.locator(".ds-step-marker")).toHaveCount(2);
      const stepMarkerStyle = await page
        .locator(".ds-step-marker")
        .first()
        .evaluate((node) => {
          const style = getComputedStyle(node);
          return {
            backgroundColor: style.backgroundColor,
            borderColor: style.borderColor,
            borderRadius: style.borderRadius,
            borderWidth: style.borderWidth,
          };
        });
      expect(stepMarkerStyle.borderRadius).toBe("50%");
      expect(stepMarkerStyle.borderWidth).not.toBe("0px");
      expect(stepMarkerStyle.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
      expect(stepMarkerStyle.borderColor).not.toBe(stepMarkerStyle.backgroundColor);
      const infoBadge = feedback.locator(".ds-status-badge--info");
      const successBadge = feedback.locator(".ds-status-badge--success");
      await expect(infoBadge).toBeVisible();
      await expect(successBadge).toBeVisible();
      const [infoColors, successColors] = await Promise.all(
        [infoBadge, successBadge].map((badge) =>
          badge.evaluate((node) => {
            const style = getComputedStyle(node);
            return { backgroundColor: style.backgroundColor, color: style.color };
          }),
        ),
      );
      expect(infoColors.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
      expect(successColors.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
      expect(infoColors).not.toEqual(successColors);
      await expect(page.locator(".ds-favorite-toggle")).toHaveCount(2);
      await expect(
        page.getByRole("combobox", { name: copy.appearance, exact: true }),
      ).toBeVisible();
      await expect(page.locator(".ds-button--toolbar.is-active")).toHaveAttribute(
        "aria-pressed",
        "true",
      );

      for (const variant of [
        "primary",
        "secondary",
        "danger",
        "dangerPrimary",
        "toolbar",
        "text",
      ]) {
        await expect(page.locator(`.ds-button--${variant}`)).not.toHaveCount(0);
      }
      for (const variant of ["secondary", "danger", "ghost"]) {
        await expect(page.locator(`.ds-icon-button--${variant}`)).not.toHaveCount(0);
      }
      expect(await page.locator("button.ds-control--small").count()).toBeGreaterThanOrEqual(2);

      const loadingButton = page.locator('.ds-button[aria-busy="true"]');
      await expect(loadingButton).toBeDisabled();
      await expect(loadingButton).not.toBeEmpty();
      const disabledButton = page.locator(".ds-button--secondary:disabled");
      await expect(disabledButton).toHaveCount(1);
      await expect(disabledButton).not.toHaveAttribute("aria-busy", "true");
      await expect(page.locator("#gallery-disabled")).toBeDisabled();
      await expect(page.locator("#gallery-disabled-select")).toBeDisabled();

      await expectFieldRelationships(page);
      await expectControlGeometry(page, viewport.size.width === 320);
      await expectNoGlobalHorizontalOverflow(page);

      await expectEquivalentComputedStyles(page.locator(".ds-button--primary:not(:disabled)"), [
        "minHeight",
        "padding",
        "fontSize",
        "fontWeight",
        "borderColor",
        "borderRadius",
        "backgroundColor",
        "color",
      ]);
      await expectEquivalentComputedStyles(
        page.locator(".ds-button--secondary.ds-control--medium:not(:disabled)"),
        [
          "minHeight",
          "padding",
          "fontSize",
          "fontWeight",
          "borderColor",
          "borderRadius",
          "backgroundColor",
          "color",
        ],
      );
      const dangerTreatment = await page
        .locator(".ds-button--danger, .ds-icon-button--danger")
        .evaluateAll((elements) =>
          elements.map((element) => {
            const style = getComputedStyle(element);
            return { borderColor: style.borderColor, color: style.color };
          }),
        );
      expect(dangerTreatment).toEqual([dangerTreatment[0], dangerTreatment[0]]);

      if (viewport.size.width === 320) {
        await expect(page.locator(".ds-page-header")).toHaveCSS("flex-direction", "column");
        await expect(page.locator(".ds-gallery__fields")).toHaveCSS(
          "grid-template-columns",
          /\d+(?:\.\d+)?px/,
        );
        const contained = await page.locator(".ds-gallery > *").evaluateAll((elements) =>
          elements.every((element) => {
            const bounds = element.getBoundingClientRect();
            return bounds.left >= 0 && bounds.right <= window.innerWidth;
          }),
        );
        expect(contained, "all gallery sections must reflow inside 320 CSS pixels").toBe(true);
      }
    });

    test(`${language}: enabled controls are keyboard reachable with visible focus at ${viewport.name}`, async ({
      mockedPage: page,
    }) => {
      await openGallery(page, language, viewport.size);
      await expectKeyboardReachabilityAndFocus(page);
    });
  }
}

for (const language of ["de", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test(`${language}: blocked actions use semantic danger feedback in ${theme} mode`, async ({
      mockedPage: page,
    }) => {
      await openGallery(page, language, galleryViewports[0].size);
      await page
        .locator("html")
        .evaluate((element, nextTheme) => element.setAttribute("data-theme", nextTheme), theme);

      const hint = page.locator("#gallery-blocked-hint");
      await expect(hint.locator(":scope > span").last()).toHaveText(
        galleryLocales[language].blockedAction,
      );
      const colors = await hint.evaluate((node) => {
        const probe = document.createElement("span");
        probe.style.color = "var(--aqa-state-danger)";
        document.body.appendChild(probe);
        const expected = getComputedStyle(probe).color;
        probe.remove();
        return { actual: getComputedStyle(node).color, expected };
      });
      expect(colors.actual).toBe(colors.expected);

      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.locator("[aria-labelledby='gallery-blocked']").screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/gallery-blocked-${language}-${theme}.png`,
        });
      }
    });
  }
}

for (const language of ["de", "en"] as const) {
  test(`${language}: gallery specimens expose their meaningful interactions`, async ({
    mockedPage: page,
  }) => {
    await openGallery(page, language, galleryViewports[0].size);
    const copy = galleryLocales[language];

    const availableChoice = page.locator('input[name="gallery-choice"][value="available"]');
    await availableChoice.locator("..").click();
    await expect(availableChoice).toBeChecked();
    await expect(availableChoice.locator("..")).toHaveClass(/is-selected/);

    const favorite = page.locator(".ds-favorite-toggle:not(:disabled)");
    await favorite.click();
    await expect(favorite).toHaveAttribute("aria-pressed", "true");

    const iconButton = page.getByRole("button", { name: copy.closeNotice, exact: true }).first();
    await iconButton.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(iconButton).toBeFocused();
    await expect
      .poll(() => iconButton.evaluate((node) => getComputedStyle(node, "::after").visibility))
      .toBe("visible");
    await page.keyboard.press("Escape");
    await expect(iconButton).toBeFocused();
    await expect(iconButton).toHaveAttribute("data-tooltip-dismissed", "true");
    await expect
      .poll(() => iconButton.evaluate((node) => getComputedStyle(node, "::after").visibility))
      .toBe("hidden");
    await iconButton.evaluate((node) => (node as HTMLElement).blur());
    await iconButton.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(iconButton).not.toHaveAttribute("data-tooltip-dismissed");

    await iconButton.evaluate((node) => (node as HTMLElement).blur());
    await iconButton.hover();
    const bounds = await iconButton.boundingBox();
    expect(bounds).not.toBeNull();
    await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y - 10);
    await expect.poll(() => iconButton.evaluate((node) => node.matches(":hover"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(iconButton).toHaveAttribute("data-tooltip-dismissed", "true");
    await page.mouse.move(0, 0);
    await iconButton.hover();
    await expect(iconButton).not.toHaveAttribute("data-tooltip-dismissed");
    await expect(iconButton).toHaveAttribute("aria-label", copy.closeNotice);

    const feedback = page.getByRole("region", { name: copy.feedback, exact: true });
    await feedback.locator(".notice-banner__dismiss").first().click();
    await expect(feedback.locator(".notice-banner")).toHaveCount(5);
    const restore = feedback.locator(".ds-gallery__specimen-header .ds-button");
    await expect(restore).toBeEnabled();
    await expect(restore).toBeFocused();
    await restore.click();
    await expect(feedback.locator(".notice-banner")).toHaveCount(6);

    const dialogTrigger = page.getByRole("button", { name: copy.dialog });
    await dialogTrigger.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator(".ds-dialog-footer")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(dialogTrigger).toBeFocused();
  });
}

for (const viewport of galleryViewports) {
  test(`reduced motion removes control transitions at ${viewport.name}`, async ({
    mockedPage: page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openGallery(page, "en", viewport.size);
    const transitions = await page
      .locator(".ds-button, .ds-control, .ds-icon-button")
      .evaluateAll((elements) =>
        elements.map((element) => ({
          delay: getComputedStyle(element).transitionDelay,
          duration: getComputedStyle(element).transitionDuration,
        })),
      );
    expect(transitions.length).toBeGreaterThan(10);
    expect(
      transitions.every(
        ({ delay, duration }) =>
          delay.split(", ").every((value) => value === "0s") &&
          duration.split(", ").every((value) => value === "0s"),
      ),
    ).toBe(true);
  });
}
