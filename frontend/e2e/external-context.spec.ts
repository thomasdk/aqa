import { expect, setLanguage, test } from "./fixtures";

for (const language of ["en", "de"] as const) {
  for (const viewport of [
    { name: "desktop", width: 1280, height: 900 },
    { name: "narrow", width: 390, height: 844 },
  ]) {
    test(`External AI oversized feedback and recovery in ${language} at ${viewport.name} width`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.route(/^https?:\/\/[^/]+\/api\/discussions\/context-estimate$/, async (route) => {
        const body = route.request().postDataJSON() as { material: string };
        const overflow = body.material.length > 1_000;
        await route.fulfill({
          json: {
            known: true,
            estimated_input_tokens: overflow ? 21_029 : 500,
            available_input_tokens: 8_192,
            context_window_tokens: 12_288,
            reserved_output_tokens: 4_096,
            overflow,
          },
        });
      });
      await page.goto("/");
      await setLanguage(page, language);
      await page.locator(".ai-readiness-choice").nth(1).click();
      await page.locator("#setup-target-language").fill(language === "de" ? "Deutsch" : "English");
      await page.locator("#setup-input-main_input").fill("Synthetic task");

      const material = page.locator("#setup-material-input");
      const start = page.locator(".prepare-start-action .ds-button");
      const guidance = page.locator("#setup-material-guidance");
      const message =
        language === "de"
          ? "Die Eingabe ist zu lang. Kürze das Material oder den Auftrag."
          : "Input is too long. Shorten the material or task.";
      await material.fill("Synthetic interview material. ".repeat(80));
      await expect(guidance).toHaveClass(/notice-banner--error/);
      await expect(guidance).toContainText(message);
      await expect(start).toBeDisabled();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/external-${language}-${viewport.name}-oversized.png`,
        });
      }

      await material.fill("Short synthetic material.");
      await expect(guidance).toHaveClass(/notice-banner--info/);
      await expect(start).toBeEnabled();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/external-${language}-${viewport.name}-valid.png`,
        });
      }
    });
  }
}
