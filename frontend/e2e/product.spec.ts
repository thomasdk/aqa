import { readFile } from "node:fs/promises";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { expectNoGlobalHorizontalOverflow } from "./fixtures";

const PROVIDER_URL = "http://127.0.0.1:4175/v1";
const MODEL_ID = "aqa-e2e-model";
const views = [
  "setup",
  "discussion",
  "sessions",
  "local-ai",
  "network",
  "roles",
  "preview",
  "system",
];

async function ensureExternalHost(request: APIRequestContext): Promise<void> {
  const current = await request.get("/api/hosts");
  expect(current.ok()).toBe(true);
  const hosts = (await current.json()) as Array<{ label: string }>;
  if (hosts.some((host) => host.label === "Product test provider")) return;

  const created = await request.post("/api/hosts", {
    data: {
      label: "Product test provider",
      url: PROVIDER_URL,
      model: MODEL_ID,
      models: [MODEL_ID],
      is_favorite: true,
    },
  });
  expect(created.ok()).toBe(true);
}

async function clearSavedSessions(request: APIRequestContext): Promise<void> {
  const response = await request.get("/api/sessions");
  expect(response.ok()).toBe(true);
  const sessions = (await response.json()) as Array<{ file_id: string }>;
  for (const session of sessions) {
    const deleted = await request.delete(`/api/sessions/${encodeURIComponent(session.file_id)}`);
    expect(deleted.ok()).toBe(true);
  }
}

async function openFreshWorkbench(page: Page, language: "de" | "en"): Promise<void> {
  await page.addInitScript((locale) => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("aqa.uiLocale.v1", locale);
    window.localStorage.setItem("aqa.aiSource.v1", "external");
  }, language);
  await page.goto("/");
  await expect(page.locator(".app-shell")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", new RegExp(`^${language}(?:-|$)`));
  if ((await page.locator(".ai-readiness-choice").count()) === 0) {
    await page.getByRole("button", { name: /new discussion|neue diskussion/i }).click();
    const discardDialog = page.locator('[role="dialog"]');
    await expect(discardDialog).toBeVisible();
    await discardDialog.locator(".ds-button--dangerPrimary").click();
  }
  await expect(page.locator(".ai-readiness-choice input[type='radio']").nth(1)).toBeChecked();
}

async function navigateTo(page: Page, view: string): Promise<void> {
  if (["local-ai", "network", "roles", "preview", "system"].includes(view)) {
    await page.locator("[data-configure-menu]").click();
  }
  await page.locator(`button[data-view="${view}"]`).click();
  await expect(page.locator(`[data-view="${view}"]`)).toHaveAttribute("aria-current", "page");
}

async function startDiscussion(page: Page): Promise<void> {
  await page.getByLabel(/target language|zielsprache/i).fill("English");
  const start = page.getByRole("button", { name: /start discussion|diskussion starten/i });
  await expect(start).toBeEnabled({ timeout: 20_000 });
  await start.click();
  await expect(page.locator(".discussion-message.message-agent").first()).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator(".followup-area")).toBeVisible({ timeout: 20_000 });
}

test.afterEach(async ({ request }) => {
  await clearSavedSessions(request);
});

for (const language of ["de", "en"] as const) {
  test(`${language}: FastAPI serves every view with the external product provider`, async ({
    page,
    request,
  }) => {
    await ensureExternalHost(request);
    await openFreshWorkbench(page, language);

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      for (const view of views) {
        await navigateTo(page, view);
        await expectNoGlobalHorizontalOverflow(page);
      }
    }

    const fontsLoaded = await page.evaluate(async () => {
      await document.fonts.load('400 24px "Material Symbols Rounded"');
      await document.fonts.load('400 24px "Material Symbols Rounded Filled"');
      await document.fonts.ready;
      return [
        document.fonts.check('400 24px "Material Symbols Rounded"'),
        document.fonts.check('400 24px "Material Symbols Rounded Filled"'),
      ];
    });
    expect(fontsLoaded).toEqual([true, true]);
  });

  test(`${language}: discussion lifecycle, session hydration, activity, reference, and dialogs`, async ({
    page,
    request,
  }) => {
    await ensureExternalHost(request);
    await openFreshWorkbench(page, language);
    await startDiscussion(page);

    await expect(page.locator(".activity-round-configuration")).toHaveCount(0);
    const perspectiveOptions = page.locator(".agent-status-row .agent-status-options-btn");
    await expect(perspectiveOptions).toHaveCount(3);
    expect(
      await perspectiveOptions.evaluateAll((buttons) =>
        buttons.every((button) => button.classList.contains("ds-button--text")),
      ),
    ).toBe(true);
    const perspectiveMoveButtons = page.locator(".agent-status-row .agent-status-move-btn");
    await expect(perspectiveMoveButtons).toHaveCount(6);
    expect(
      await perspectiveMoveButtons.evaluateAll((buttons) =>
        buttons.every((button) => button.classList.contains("ds-icon-button")),
      ),
    ).toBe(true);
    for (let index = 0; index < 3; index += 1) {
      const button = perspectiveOptions.nth(index);
      await expect(button).toHaveAttribute("aria-expanded", "false");
      await button.click();
      await expect(button).toHaveAttribute("aria-expanded", "true");
      const controlsId = await button.getAttribute("aria-controls");
      const controls = page.locator(`#${controlsId}`);
      await expect(controls).toBeVisible();
      await expect(controls.locator(".agent-config-field > span")).toHaveText(
        language === "de" ? ["Host", "Modell"] : ["Host", "Model"],
      );
      expect(
        await controls.evaluate((region) => {
          const model = region.querySelectorAll(".agent-config-field select")[1];
          const temperature = region.querySelector('.checkbox input[type="checkbox"]');
          return Boolean(
            model &&
            temperature &&
            model.compareDocumentPosition(temperature) & Node.DOCUMENT_POSITION_FOLLOWING,
          );
        }),
      ).toBe(true);
      await button.click();
      await expect(page.locator(`#${controlsId}`)).toHaveCount(0);
    }

    const synthesisRow = page.locator(".synthesis-status-row");
    const synthesisOptions = synthesisRow.locator(".agent-status-options-btn");
    const synthesisActive = synthesisRow.locator(".synthesis-status-toggle");
    const [optionsBox, activeBox] = await Promise.all([
      synthesisOptions.boundingBox(),
      synthesisActive.boundingBox(),
    ]);
    expect(optionsBox).not.toBeNull();
    expect(activeBox).not.toBeNull();
    expect(optionsBox!.x).toBeLessThan(activeBox!.x);
    await perspectiveOptions.first().click();
    await synthesisOptions.click();
    await expect(page.locator("#activity-synthesis-options")).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoGlobalHorizontalOverflow(page);
    const [narrowOptionsBox, narrowActiveBox] = await Promise.all([
      synthesisOptions.boundingBox(),
      synthesisActive.boundingBox(),
    ]);
    expect(narrowOptionsBox).not.toBeNull();
    expect(narrowActiveBox).not.toBeNull();
    expect(narrowOptionsBox!.x).toBeLessThan(narrowActiveBox!.x);
    expect(
      Math.abs(
        narrowOptionsBox!.y +
          narrowOptionsBox!.height / 2 -
          (narrowActiveBox!.y + narrowActiveBox!.height / 2),
      ),
    ).toBeLessThan(2);
    await perspectiveOptions.first().click();
    await synthesisOptions.click();
    await expect(page.locator("#activity-synthesis-options")).toHaveCount(0);
    await expect(page.getByText(/Edit Options|Optionen bearbeiten/)).toHaveCount(0);
    await page.setViewportSize({ width: 1280, height: 720 });

    const firstActiveToggle = page
      .locator(".agent-status-row")
      .first()
      .locator(".agent-status-active-toggle input");
    await firstActiveToggle.uncheck();
    await expect(firstActiveToggle).not.toBeChecked();
    await firstActiveToggle.check();
    await expect(firstActiveToggle).toBeChecked();

    const debateAction = page.locator(".quick-prompt-chip").first();
    await expect(debateAction).toHaveText(language === "de" ? "Diskutieren" : "Debate");
    await debateAction.click();
    await expect(page.locator(".followup-area textarea")).toHaveValue(
      "Continue the discussion by responding to the contributions of the previous round.",
    );

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(
      /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_AQA_[a-z0-9-]+\.md$/,
    );
    const downloadedPath = await download.path();
    expect(downloadedPath).not.toBeNull();
    const exportedMarkdown = await readFile(downloadedPath!, "utf8");
    expect(exportedMarkdown).toContain("Deterministic analysis.");
    expect(exportedMarkdown.length).toBeGreaterThan(0);

    const firstAgentMessage = page.locator(".discussion-message.message-agent").first();
    await firstAgentMessage.locator(".message-bezugspunkt-btn").click();
    await expect(page.locator(".followup-area textarea")).toContainText("Deterministic analysis.");

    await page.locator(".followup-area textarea").fill("Continue with the same material.");
    await page.locator(".followup-area > .ds-button--primary").click();
    await expect(page.locator(".discussion-message.message-agent")).toHaveCount(6, {
      timeout: 20_000,
    });
    const providerHistory = page.locator(".activity-panel .provider-history");
    await expect(providerHistory).toBeVisible();
    await expect(page.locator(".discussion-messages .provider-history")).toHaveCount(0);
    await providerHistory.locator("summary").click();
    await expect(providerHistory.locator("thead th")).toHaveText(
      language === "de"
        ? ["Runde", "Perspektive / Synthese", "Host", "Modell"]
        : ["Round", "Perspective / Synthesis", "Host", "Model"],
    );
    await expect(providerHistory.locator("tbody tr")).toHaveCount(8);
    await expect(providerHistory).toContainText(language === "de" ? "Synthese" : "Synthesis");
    await expect(providerHistory).not.toContainText(PROVIDER_URL);

    await page.locator(".followup-area textarea").fill("AQA_E2E_SLOW_STOP");
    await perspectiveOptions.first().click();
    await synthesisOptions.click();
    await expect(page.locator(".activity-inline-config")).toHaveCount(2);
    const idlePlaybackRate = await page
      .locator("[data-aqa-brand]")
      .evaluate((brand) =>
        Math.min(
          ...Array.from(brand.querySelectorAll("[data-aqa-wave]"), (participant) =>
            Math.max(...participant.getAnimations().map((animation) => animation.playbackRate)),
          ),
        ),
      );
    await page.locator(".followup-area > .ds-button--primary").click();
    const stop = page.locator(".activity-stop-btn");
    await expect(stop).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".activity-inline-config")).toHaveCount(0);
    await expect(page.locator("[data-aqa-brand]")).toHaveAttribute("data-aqa-generating", "true");
    await expect
      .poll(() =>
        page
          .locator("[data-aqa-brand]")
          .evaluate((brand) =>
            Math.min(
              ...Array.from(brand.querySelectorAll("[data-aqa-wave]"), (participant) =>
                Math.max(...participant.getAnimations().map((animation) => animation.playbackRate)),
              ),
            ),
          ),
      )
      .toBeGreaterThan(idlePlaybackRate);
    await stop.click();
    await expect(stop).toBeHidden({ timeout: 10_000 });
    await page.waitForTimeout(2_000);

    await page.locator(".activity-log-toggle").click();
    await expect(page.locator(".activity-log")).toContainText(/discussion|diskussion/i);

    await navigateTo(page, "sessions");
    const openSession = page.locator(".sessions-row").first();
    await expect(openSession).toBeVisible();
    await openSession.locator(".sessions-action-open").click();
    await expect(page.locator(".discussion-shell")).toBeVisible();

    await navigateTo(page, "network");
    const deleteHost = page.locator(".nc-actions .ds-icon-button--danger").first();
    await deleteHost.click();
    const deleteDialog = page.locator('[role="dialog"]');
    await expect(deleteDialog.locator(".ds-dialog-footer")).toBeVisible();
    await expect(deleteDialog.locator(".modal-message > .nc-delete-impact > p")).toHaveCount(2);
    await expect(deleteDialog.locator(".nc-delete-summary")).toHaveCount(0);
    await expect(deleteDialog).not.toContainText(
      language === "de" ? "Vor dem Löschen" : "Before Deleting",
    );
    await expect(deleteDialog).toContainText(
      language === "de" ? "Bei bestehenden Diskussionen" : "Existing discussions",
    );
    await expect(deleteDialog.locator("ul")).toHaveCount(0);
    await deleteDialog
      .getByRole("button", { name: language === "de" ? "Abbrechen" : "Cancel" })
      .click();
    await expect(deleteDialog).toBeHidden();

    const openModal = page.locator(".nc-header .ds-button--primary");
    await openModal.focus();
    await openModal.click();
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#nc-host-url")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(openModal).toBeFocused();
  });
}
