import type { Page } from "@playwright/test";
import { expect, setLanguage, test } from "./fixtures";

const configurationViews = new Set(["local-ai", "network", "roles", "preview", "system"]);

async function navigateTo(page: Page, view: string): Promise<void> {
  if (configurationViews.has(view)) await page.locator("[data-configure-menu]").click();
  await page.locator(`button[data-view="${view}"]`).click();
  await expect(page.locator(`button[data-view="${view}"]`)).toHaveAttribute("aria-current", "page");
}

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

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "narrow", width: 390, height: 844 },
] as const;

for (const language of ["de", "en"] as const) {
  for (const viewport of viewports) {
    test(`prior-version parity: ${language} ${viewport.name} main views`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await setLanguage(page, language);

      for (const view of views) {
        await navigateTo(page, view);
        await page.evaluate(async () => {
          await document.fonts.load('400 24px "Material Symbols Rounded"');
          await document.fonts.ready;
        });
        await expect(page).toHaveScreenshot(`parity-${language}-${viewport.name}-${view}.png`, {
          animations: "disabled",
          caret: "hide",
          fullPage: false,
          // This compares against ab7002c as a redesign guardrail. Small shared-control
          // normalization is intentional; large changes to hierarchy or density are not.
          // Local AI's narrow card/control consolidation touches more pixels while retaining
          // the same content order and responsive structure, so it gets a bounded exception.
          maxDiffPixelRatio: view === "local-ai" && viewport.name === "narrow" ? 0.1 : 0.08,
        });
      }
    });
  }
}
