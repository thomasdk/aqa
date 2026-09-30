import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";

for (const language of ["en", "de"] as const) {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 900 },
    { name: "narrow", width: 390, height: 844 },
  ]) {
    test(`${language} ${viewport.name}: grouped token displays and external editing`, async ({
      mockedPage: page,
    }) => {
      const separator = language === "de" ? "." : ",";
      let context = 8192;
      const saved: number[] = [];
      await page.route(/\/api\/material\/token-estimate$/, (route) =>
        route.fulfill({ json: { approximate_tokens: 8000, tokenizer: "o200k_base" } }),
      );
      await page.route(/\/api\/hosts$/, async (route) => {
        await route.fulfill({
          json: [
            {
              configuration_id: "Synthetic",
              label: "Synthetic",
              url: "https://example.invalid",
              model: "model-a",
              models: ["model-a"],
              kind: "openai_compatible",
              has_api_key: false,
              is_favorite: false,
              model_context_tokens: { "model-a": context },
            },
          ],
        });
      });
      await page.route(/\/api\/hosts\/0$/, async (route) => {
        const body = route.request().postDataJSON() as {
          model_context_tokens?: Record<string, number>;
        };
        context = body.model_context_tokens?.["model-a"] ?? context;
        saved.push(context);
        await route.fulfill({ json: {} });
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");
      await setLanguage(page, language);
      await expect(page.locator(".setup-token-estimate")).toContainText(`8${separator}000`);
      await page.locator('button[data-view="discussion"]').click();
      await expect(page.locator(".material-token-estimate")).toContainText(`8${separator}000`);
      await page.locator("[data-configure-menu]").click();
      await page.locator('button[data-view="network"]').click();
      await expect(page.locator(".nc-table")).toContainText(`8${separator}192`);
      await page.getByRole("button", { name: language === "de" ? "Bearbeiten" : "Edit" }).click();
      const input = page.locator("#nc-model-context-0");
      await expect(input).toHaveValue(`8${separator}192`);
      await input.focus();
      await expect(input).toHaveValue(`8${separator}192`);
      await input.evaluate((element) => (element as HTMLInputElement).setSelectionRange(1, 1));
      await input.press("Delete");
      await expect(input).toHaveValue("8192");
      expect(await input.evaluate((element) => (element as HTMLInputElement).selectionStart)).toBe(
        1,
      );
      await input.evaluate((element) => (element as HTMLInputElement).setSelectionRange(1, 2));
      await input.press("3");
      await expect(input).toHaveValue("8392");
      await input.fill(language === "de" ? "8,192" : "8.192");
      await expect(input).toHaveAttribute("aria-invalid", "true");
      await expect(page.locator(".nc-context-window-field .ds-field__error")).toBeVisible();
      await page.locator(".nc-context-window-field .ds-field__error").scrollIntoViewIfNeeded();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-external-error.png`,
        });
      }
      await input.fill(`32${separator}768`);
      await input.press("ArrowUp");
      await expect(input).toHaveValue("32769");
      await input.press("ArrowDown");
      await expect(input).toHaveValue("32768");
      await input.blur();
      await expect(input).toHaveValue(`32${separator}768`);
      await page.getByRole("button", { name: language === "de" ? "Speichern" : "Save" }).click();
      expect(saved).toEqual([32768]);
      await expect(page.locator(".nc-table")).toContainText(`32${separator}768`);
      await expectNoGlobalHorizontalOverflow(page);
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-external-saved.png`,
        });
      }
      await page.locator(".nc-header button.ds-button--primary").click();
      await expect(page.locator("#nc-model-context-0")).toBeDisabled();
      await page.locator("#nc-model-context-0").scrollIntoViewIfNeeded();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-external-disabled.png`,
        });
      }
    });
  }
}
