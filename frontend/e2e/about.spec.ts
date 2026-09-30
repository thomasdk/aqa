import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";

const releaseInfo = JSON.parse(
  readFileSync(new URL("../../release-info.json", import.meta.url), "utf8"),
) as { version: string };

const openNativeAbout = async (page: Page) => {
  await page.evaluate(() => {
    window.location.hash = "aqa-about";
  });
};

for (const language of ["en", "de"] as const) {
  for (const width of [1440, 320]) {
    test(`${language}: About entry fits ${width}px and restores focus`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize({ width, height: width === 320 ? 640 : 900 });
      await page.goto("/");
      await setLanguage(page, language);

      const focusReturn = page.locator('button[data-view="setup"]');
      await focusReturn.focus();
      await openNativeAbout(page);

      const dialog = page.getByRole("dialog", {
        name: language === "en" ? "About AQA" : "Über AQA",
      });
      await expect(dialog).toBeVisible();
      await expect(dialog).toContainText("Thomas Krause");
      await expect(dialog).toContainText(
        language === "en" ? "University of Stuttgart" : "Universität Stuttgart",
      );
      await expect(dialog).toContainText(releaseInfo.version);
      await expect(dialog).toContainText(
        language === "en"
          ? "The repository address has not been assigned yet."
          : "Die Repository-Adresse wurde noch nicht festgelegt.",
      );
      await expectNoGlobalHorizontalOverflow(page);
      expect(
        await dialog.evaluate((element) => element.getBoundingClientRect().width <= innerWidth),
      ).toBe(true);
      expect(
        await dialog
          .locator(".ds-editor-dialog-body")
          .evaluate((element) => element.scrollWidth <= element.clientWidth),
      ).toBe(true);

      await openNativeAbout(page);
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(focusReturn).toBeFocused();

      await openNativeAbout(page);
      await dialog.getByRole("button", { name: language === "en" ? "Close" : "Schließen" }).click();
      await expect(dialog).toBeHidden();
      await expect(focusReturn).toBeFocused();
    });
  }
}
