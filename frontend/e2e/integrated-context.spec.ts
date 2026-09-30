import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";

for (const language of ["de", "en"] as const) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`${language} context input fits at ${viewport.width}px`, async ({ mockedPage: page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await setLanguage(page, language);
      await page.locator("[data-configure-menu]").click();
      await page.locator('button[data-view="local-ai"]').click();
      await page.locator(".local-ai-advanced > summary").click();
      const input = page.locator("#local-ai-context");
      await expect(input).toBeVisible();
      await expect(input).toHaveAttribute("min", "8192");
      await expect(input).toHaveAttribute("max", "131072");
      await input.fill("");
      await expect(input).toHaveAttribute("aria-invalid", "true");
      await expect(page.locator("#local-ai-context-error")).toBeVisible();
      await expect(page.locator("#local-ai-context-error")).toHaveClass("ds-field__error");
      await expect(input).toHaveAttribute("aria-describedby", /local-ai-context-error/);
      await expectNoGlobalHorizontalOverflow(page);
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/context-${language}-${viewport.width}.png`,
          fullPage: true,
        });
      }
    });
  }
}
