import {
  expectScreenshot,
  expect,
  expectNoGlobalHorizontalOverflow,
  setLanguage,
  test,
} from "./fixtures";
import type { Page } from "@playwright/test";

const configurationViews = new Set(["local-ai", "network", "roles", "preview", "system"]);

async function navigateTo(page: Page, view: string): Promise<void> {
  if (configurationViews.has(view)) {
    await page.locator("[data-configure-menu]").click();
  }
  await page.locator(`button[data-view="${view}"]`).click();
}

const viewportMatrix = [
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

const languages = ["de", "en"] as const;

test("Prepare keeps material guidance prominent at desktop and narrow widths", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");

  const guidance = page.locator("#setup-material-guidance");
  await expect(guidance).toBeVisible();
  await expect(guidance).toHaveClass(/notice-banner--info/);
  await expect(guidance).toContainText("Longer material takes longer to process");
  await expect(guidance).not.toContainText("Safe size depends on all selected models");
  await expect(page.locator("#setup-material-input")).toHaveAttribute(
    "aria-describedby",
    "setup-material-guidance",
  );
  await expectNoGlobalHorizontalOverflow(page);

  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await guidance.screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/prepare-material-guidance-wide.png`,
    });
  }

  await page.setViewportSize({ width: 400, height: 900 });
  await expect(guidance).toBeVisible();
  await expectNoGlobalHorizontalOverflow(page);
  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await guidance.screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/prepare-material-guidance-narrow.png`,
    });
  }
});

for (const language of languages) {
  for (const viewport of [
    { name: "desktop", width: 1280, height: 900 },
    { name: "narrow", width: 390, height: 844 },
  ]) {
    test(`configured session hints remain visible and associated in ${language} at ${viewport.name} width`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");
      await setLanguage(page, language);

      const taskInput = page.locator("#setup-input-main_input");
      const taskHint = page.locator("#setup-input-main_input-hint");
      await expect(taskHint).toBeVisible();
      await expect(taskHint).toHaveText("An exploration task to begin the open analysis.");
      await expect(taskInput).not.toHaveAttribute("placeholder", /.+/);
      await expect(taskInput).toHaveAttribute("aria-describedby", /setup-input-main_input-hint/);
      await taskInput.fill("Synthetic edited task");
      await expect(taskHint).toBeVisible();
      await expectNoGlobalHorizontalOverflow(page);

      await page.locator("button[aria-controls='setup-research-material-context']").click();
      const materialInput = page.locator("#setup-input-research_material_context");
      const materialHint = page.locator("#setup-input-research_material_context-hint");
      await expect(materialHint).toBeVisible();
      await expect(materialInput).toHaveAttribute(
        "aria-describedby",
        /setup-input-research_material_context-hint/,
      );

      await page.locator("button[aria-controls='setup-optional-inputs']").click();
      const instructionsInput = page.locator("#setup-input-additional_instructions");
      const instructionsHint = page.locator("#setup-input-additional_instructions-hint");
      await expect(instructionsHint).toBeVisible();
      await expect(instructionsInput).toHaveAttribute(
        "aria-describedby",
        /setup-input-additional_instructions-hint/,
      );
      await expectNoGlobalHorizontalOverflow(page);
    });
  }
}

const blockedStartCopy = {
  de: {
    missing: "Fülle alle erforderlichen Felder aus, bevor du startest.",
    overflow: "Die Eingabe ist zu lang. Kürze das Material oder den Auftrag.",
  },
  en: {
    missing: "Complete all required fields before starting.",
    overflow: "Input is too long. Shorten the material or task.",
  },
} as const;

for (const scenario of ["missing", "overflow"] as const) {
  for (const language of languages) {
    for (const theme of ["dark", "light"] as const) {
      test(`Prepare aligns ${scenario} feedback in ${language}/${theme} at desktop and narrow widths`, async ({
        mockedPage: page,
      }) => {
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.goto(scenario === "overflow" ? "/?e2e-context=overflow" : "/");
        await setLanguage(page, language);
        await page
          .locator("html")
          .evaluate((element, nextTheme) => element.setAttribute("data-theme", nextTheme), theme);
        if (scenario === "overflow") {
          await page
            .locator("#setup-target-language")
            .fill(language === "de" ? "Deutsch" : "English");
        }

        const startArea = page.locator(".prepare-start-area");
        const startHeader = startArea.locator(".prepare-step-header");
        const startButton = startArea.locator(".prepare-start-action .ds-button");
        const startHint = page.locator("#setup-start-disabled-reason");
        await expect(startHint).toContainText(blockedStartCopy[language][scenario]);
        await expect(startHint).toHaveClass("blocked-action-hint");
        const colors = await startHint.evaluate((node) => {
          const probe = document.createElement("span");
          probe.style.color = "var(--aqa-state-danger)";
          document.body.appendChild(probe);
          const expected = getComputedStyle(probe).color;
          probe.remove();
          return { actual: getComputedStyle(node).color, expected };
        });
        expect(colors.actual).toBe(colors.expected);

        const desktopArea = await startArea.boundingBox();
        const desktopHeader = await startHeader.boundingBox();
        const desktopButton = await startButton.boundingBox();
        const desktopHint = await startHint.boundingBox();
        expect(desktopArea).not.toBeNull();
        expect(desktopHeader).not.toBeNull();
        expect(desktopButton).not.toBeNull();
        expect(desktopHint).not.toBeNull();
        expect(Math.abs(desktopHeader!.y - desktopButton!.y)).toBeLessThanOrEqual(2);
        expect(
          Math.abs(desktopArea!.x + desktopArea!.width - desktopButton!.x - desktopButton!.width),
        ).toBeLessThanOrEqual(2);
        expect(desktopHint!.y).toBeGreaterThanOrEqual(desktopButton!.y + desktopButton!.height);
        expect(
          Math.abs(desktopButton!.x + desktopButton!.width - desktopHint!.x - desktopHint!.width),
        ).toBeLessThanOrEqual(2);
        await expectNoGlobalHorizontalOverflow(page);

        if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
          await startArea.screenshot({
            path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/prepare-${scenario}-${language}-${theme}-wide.png`,
          });
        }

        await page.setViewportSize({ width: 400, height: 900 });
        const narrowArea = await startArea.boundingBox();
        const narrowHeader = await startHeader.boundingBox();
        const narrowButton = await startButton.boundingBox();
        const narrowHint = await startHint.boundingBox();
        expect(narrowArea).not.toBeNull();
        expect(narrowHeader).not.toBeNull();
        expect(narrowButton).not.toBeNull();
        expect(narrowHint).not.toBeNull();
        expect(narrowButton!.y).toBeGreaterThanOrEqual(narrowHeader!.y + narrowHeader!.height);
        expect(narrowHint!.y).toBeGreaterThanOrEqual(narrowButton!.y + narrowButton!.height);
        expect(narrowButton!.width).toBeLessThanOrEqual(narrowArea!.width);
        expect(narrowHint!.width).toBeLessThanOrEqual(narrowArea!.width);
        await expectNoGlobalHorizontalOverflow(page);

        if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
          await startArea.screenshot({
            path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/prepare-${scenario}-${language}-${theme}-narrow.png`,
          });
        }
      });
    }
  }
}

for (const language of languages) {
  test(`${language}: external AI table wraps long values and keeps actions reachable`, async ({
    mockedPage: page,
  }, testInfo) => {
    await page.route(/\/api\/hosts$/, async (route) => {
      await route.fulfill({
        json: [
          {
            configuration_id: "external-overflow-regression",
            label: "ExternalResearchProviderWithAnUnbrokenLongDisplayName",
            url: "https://openrouter.ai/api/v1/chat/completions/with-an-unbroken-long-endpoint-name",
            model: "openai/research-model-with-a-deliberately-long-identifier",
            models: ["openai/research-model-with-a-deliberately-long-identifier"],
            kind: "openai_compatible",
            has_api_key: true,
            is_favorite: false,
          },
        ],
      });
    });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    await expect(page.locator(".app-shell")).toBeVisible();
    await setLanguage(page, language);
    await navigateTo(page, "network");

    const scrollRegion = page.locator(".nc-table-scroll");
    const row = page.locator(".nc-table tbody tr");
    await expect(row).toHaveCount(1);
    const actions = row.getByRole("button");
    await expect(actions).toHaveCount(3);

    for (const width of [1280, 1440, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoGlobalHorizontalOverflow(page);
      await expect
        .poll(() => scrollRegion.evaluate((element) => element.scrollHeight - element.clientHeight))
        .toBeLessThanOrEqual(1);
      if (width >= 1280) {
        await expect
          .poll(() => scrollRegion.evaluate((element) => element.scrollWidth - element.clientWidth))
          .toBeLessThanOrEqual(1);
      } else {
        await scrollRegion.focus();
        await expect(scrollRegion).toBeFocused();
        await scrollRegion.press("ArrowRight");
        await expect
          .poll(() => scrollRegion.evaluate((element) => element.scrollLeft))
          .toBeGreaterThan(0);
      }
      await page.screenshot({ path: testInfo.outputPath(`external-ai-${language}-${width}.png`) });

      for (const action of await actions.all()) {
        await action.focus();
        await expect(action).toBeFocused();
        await action.click({ trial: true });
        const actionBox = await action.boundingBox();
        const regionBox = await scrollRegion.boundingBox();
        expect(actionBox).not.toBeNull();
        expect(regionBox).not.toBeNull();
        expect(actionBox!.x).toBeGreaterThanOrEqual(regionBox!.x);
        expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(
          regionBox!.x + regionBox!.width,
        );
        expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(
          regionBox!.y + regionBox!.height,
        );
      }
    }
  });

  test(`${language}: management tables expose named keyboard scroll regions`, async ({
    mockedPage: page,
  }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto("/");
    await setLanguage(page, language);

    for (const view of ["roles", "system"]) {
      await navigateTo(page, view);
      const regions = page.locator(view === "roles" ? ".rm-table-scroll" : ".pcm-table-scroll");
      await expect.poll(() => regions.count()).toBeGreaterThan(0);
      for (const region of await regions.all()) {
        await expect(region).toHaveAttribute("role", "region");
        await expect(region).toHaveAttribute("aria-label", /.+/);
        await expect(region).toHaveAttribute("tabindex", "0");
        await expect
          .poll(() => region.evaluate((element) => element.scrollWidth - element.clientWidth))
          .toBeGreaterThan(0);
        await region.focus();
        await region.press("ArrowRight");
        await expect
          .poll(() => region.evaluate((element) => element.scrollLeft))
          .toBeGreaterThan(0);
      }
      await expectNoGlobalHorizontalOverflow(page);
    }
  });
}

for (const language of languages) {
  for (const viewport of viewportMatrix) {
    test(`${language}: all main views fit ${viewport.width}x${viewport.height}`, async ({
      mockedPage: page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(page.locator(".app-shell")).toBeVisible();
      await setLanguage(page, language);

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

      for (const view of views) {
        await navigateTo(page, view);
        await expect(page.locator(`[data-view="${view}"]`)).toHaveAttribute("aria-current", "page");
        await expectNoGlobalHorizontalOverflow(page);
      }

      if (viewport.width < 640) {
        for (const tab of await page.locator(".primary-navigation .view-tab").all()) {
          const box = await tab.boundingBox();
          expect(box?.height ?? 0).toBeGreaterThanOrEqual(40);
        }
      }
    });
  }
}

test("runtime maintenance actions align on wide screens and stack on narrow screens", async ({
  mockedPage: page,
}) => {
  await page.route(/\/api\/local-ai\/status$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        state: "stopped",
        model_id: "gemma-4-e2b",
        model_name: "Gemma 4 E2B",
        preferred_model_id: "gemma-4-e2b",
        recommended_model: "gemma-4-e2b",
        download_bytes: 0,
        download_total: 0,
        context_tokens: 131072,
        mtp_enabled: false,
        mtp_draft_tokens: null,
        host_ready: false,
        message: null,
        integrity: "verified",
        os_label: "macOS",
        cpu_label: "Apple Silicon",
        gpu_label: "Integrated GPU",
        ram_gb: 16,
        models: [{ model_id: "gemma-4-e2b", installed: true, integrity: "verified" }],
        runtime_installed: true,
        runtime_selection: {
          runtime_profile: "macos-arm64-metal",
          accelerator_label: "Metal",
          engine_name: "llama-server",
          decision_basis: "detected compatible runtime",
        },
      }),
    });
  });

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");
  await navigateTo(page, "local-ai");
  await page.locator(".local-ai-maintenance > summary").click();

  const actionBlocks = page.locator(".local-ai-runtime-action");
  await expect(actionBlocks).toHaveCount(2);
  const wideBoxes = await actionBlocks.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().toJSON()),
  );
  expect(Math.round(wideBoxes[0].top)).toBe(Math.round(wideBoxes[1].top));
  expect(wideBoxes[1].left).toBeGreaterThan(wideBoxes[0].right);

  await page.setViewportSize({ width: 640, height: 800 });
  const narrowBoxes = await actionBlocks.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().toJSON()),
  );
  expect(narrowBoxes[1].top).toBeGreaterThanOrEqual(narrowBoxes[0].bottom);
  expect(Math.round(narrowBoxes[0].left)).toBe(Math.round(narrowBoxes[1].left));
  await expectNoGlobalHorizontalOverflow(page);
});

test("running Integrated AI keeps an active model transfer aligned and responsive", async ({
  mockedPage: page,
}) => {
  const language = process.env.AQA_TEST_LANGUAGE === "en" ? "en" : "de";
  const theme = process.env.AQA_TEST_THEME === "light" ? "light" : "dark";
  const copy =
    language === "en"
      ? {
          delete: "Delete",
          cancel: "Cancel",
          activeHint: "Stop Integrated AI before deleting this model.",
          transferStatus: "The model is being downloaded and checked.",
          transferLane: "before downloading or importing another model",
          percent: "42%",
        }
      : {
          delete: "Löschen",
          cancel: "Abbrechen",
          activeHint: "Stoppe die integrierte KI, bevor du dieses Modell löschst.",
          transferStatus: "Modell wird heruntergeladen und geprüft.",
          transferLane: "bevor Sie ein weiteres Modell herunterladen oder importieren",
          percent: "42 %",
        };
  await page.route(/\/api\/local-ai\/status$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        state: "running",
        model_id: "gemma-4-e4b",
        model_name: "Gemma 4 E4B",
        preferred_model_id: "gemma-4-e4b",
        recommended_model: "gemma-4-e4b",
        operation_kind: "model_download",
        operation_state: "downloading",
        operation_model_id: "gemma-4-12b",
        download_phase: "main_model",
        download_bytes: 42,
        download_total: 100,
        job_id: "download-12b",
        context_tokens: 32768,
        mtp_enabled: false,
        mtp_draft_tokens: null,
        host: "http://127.0.0.1:43123",
        port: 43123,
        host_ready: true,
        message: null,
        integrity: "verified",
        os_label: "macOS",
        cpu_label: "Apple Silicon",
        gpu_label: "Integrated GPU",
        ram_gb: 16,
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
        runtime_installed: true,
        runtime_selection: {
          runtime_profile: "macos-arm64-metal",
          accelerator_label: "Metal",
          engine_name: "llama-server",
          decision_basis: "detected compatible runtime",
        },
      }),
    });
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await setLanguage(page, language);
  await page
    .locator("html")
    .evaluate((element, nextTheme) => element.setAttribute("data-theme", nextTheme), theme);
  await navigateTo(page, "local-ai");

  const activeModelCard = page.getByRole("group", { name: "Gemma 4 E4B" });
  const inactiveModelCard = page.getByRole("group", { name: "Gemma 4 E2B" });
  const activeDelete = activeModelCard.getByRole("button", { name: copy.delete });
  await expect(activeDelete).toBeVisible();
  await expect(activeDelete).toBeDisabled();
  const activeHint = activeModelCard.locator("#local-ai-active-model-gemma-4-e4b");
  await expect(activeHint).toBeVisible();
  await expect(activeHint).toContainText(copy.activeHint);
  await expect(activeHint).toHaveClass("blocked-action-hint");
  await expect(activeModelCard.locator(".ds-status-badge--info")).toBeVisible();
  await expect(activeModelCard.locator(".ds-status-badge--success")).toBeVisible();
  await expect(inactiveModelCard.locator(".ds-status-badge--info")).toBeVisible();
  await expect(inactiveModelCard.locator(".ds-status-badge--success")).toHaveCount(0);
  await expect(inactiveModelCard.getByRole("button", { name: copy.delete })).toBeEnabled();
  const activeModelSize = activeModelCard.locator(".local-ai-model-choice-meta");
  const inactiveModelSize = inactiveModelCard.locator(".local-ai-model-choice-meta");
  await expect(activeModelSize).toBeVisible();
  await expect(inactiveModelSize).toBeVisible();
  const transferRow = page.getByRole("group", { name: "Gemma 4 12B" });
  const wideCardBoxes = await Promise.all([
    inactiveModelCard.boundingBox(),
    activeModelCard.boundingBox(),
    transferRow.boundingBox(),
  ]);
  expect(wideCardBoxes.every(Boolean)).toBe(true);
  expect(
    Math.max(...wideCardBoxes.map((box) => box!.height)) -
      Math.min(...wideCardBoxes.map((box) => box!.height)),
  ).toBeLessThan(2);
  const transferStatus = transferRow.locator(".local-ai-model-transfer-status");
  const transferProgress = transferRow.locator(".local-ai-model-transfer-progress");
  const transferPercent = transferRow.locator(".local-ai-model-transfer-meta > span").first();
  const transferTotal = transferRow.locator(".local-ai-model-transfer-total");
  const transferCancel = transferRow.getByRole("button", { name: copy.cancel });
  await expect(transferStatus).toContainText(copy.transferStatus);
  await expect(transferStatus).not.toContainText(copy.percent);
  await expect(transferStatus).not.toContainText("·");
  await expect(transferPercent).toHaveText(copy.percent);
  await expect(transferTotal).toHaveText("100 B");
  await expect(transferRow.locator(".local-ai-model-choice-meta")).toContainText(/6[,.]97 GB/);
  await expect(transferProgress).toHaveAttribute("aria-valuetext", copy.percent);
  await expect(transferCancel).toBeEnabled();
  const wideTransferBoxes = await Promise.all([
    transferStatus.boundingBox(),
    transferPercent.boundingBox(),
    transferTotal.boundingBox(),
    transferProgress.boundingBox(),
    transferCancel.boundingBox(),
  ]);
  expect(wideTransferBoxes.every(Boolean)).toBe(true);
  expect(Math.abs(wideTransferBoxes[0]!.y - wideTransferBoxes[1]!.y)).toBeLessThan(2);
  expect(Math.abs(wideTransferBoxes[1]!.y - wideTransferBoxes[2]!.y)).toBeLessThan(2);
  expect(wideTransferBoxes[3]!.y).toBeGreaterThanOrEqual(
    wideTransferBoxes[0]!.y + wideTransferBoxes[0]!.height,
  );
  expect(wideTransferBoxes[4]!.x).toBeGreaterThanOrEqual(wideTransferBoxes[3]!.x);

  const transferLaneHint = page.locator("#local-ai-transfer-lane-reason");
  await expect(transferLaneHint).toContainText(copy.transferLane);
  await expect(transferLaneHint).toHaveClass("blocked-action-hint");
  for (const hint of [activeHint, transferLaneHint]) {
    const colors = await hint.evaluate((node) => {
      const probe = document.createElement("span");
      probe.style.color = "var(--aqa-state-danger)";
      document.body.appendChild(probe);
      const expected = getComputedStyle(probe).color;
      probe.remove();
      return { actual: getComputedStyle(node).color, expected };
    });
    expect(colors.actual).toBe(colors.expected);
  }
  await expectNoGlobalHorizontalOverflow(page);

  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await page.screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/model-management-running-${language}-${theme}-wide.png`,
      fullPage: true,
    });
  }

  await page.setViewportSize({ width: 400, height: 900 });
  await expect(activeDelete).toBeVisible();
  const narrowTransferBoxes = await Promise.all([
    transferStatus.boundingBox(),
    transferProgress.boundingBox(),
    transferCancel.boundingBox(),
  ]);
  expect(narrowTransferBoxes.every(Boolean)).toBe(true);
  expect(narrowTransferBoxes[1]!.y).toBeGreaterThanOrEqual(
    narrowTransferBoxes[0]!.y + narrowTransferBoxes[0]!.height,
  );
  expect(narrowTransferBoxes[2]!.y).toBeGreaterThanOrEqual(
    narrowTransferBoxes[1]!.y + narrowTransferBoxes[1]!.height,
  );
  expect(Math.round(narrowTransferBoxes[0]!.x)).toBe(Math.round(narrowTransferBoxes[1]!.x));
  expect(Math.round(narrowTransferBoxes[1]!.x)).toBe(Math.round(narrowTransferBoxes[2]!.x));
  await expectNoGlobalHorizontalOverflow(page);
  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await page.screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/model-management-running-${language}-${theme}-narrow.png`,
      fullPage: true,
    });
  }
});

test("running E2B keeps equal cards and design-system E4B guidance", async ({
  mockedPage: page,
}) => {
  await page.route(/\/api\/local-ai\/status$/, async (route) => {
    await route.fulfill({
      json: {
        state: "running",
        model_id: "gemma-4-e2b",
        model_name: "Gemma 4 E2B",
        preferred_model_id: "gemma-4-e2b",
        context_tokens: 32_768,
        mtp_enabled: false,
        mtp_draft_tokens: null,
        host_ready: true,
        message: null,
        integrity: "verified",
        os_label: "macOS",
        cpu_label: "Apple Silicon",
        gpu_label: "Integrated GPU",
        ram_gb: 16,
        models: [
          { model_id: "gemma-4-e2b", installed: true, integrity: "verified" },
          { model_id: "gemma-4-e4b", installed: false, integrity: "unknown" },
          { model_id: "gemma-4-12b", installed: false, integrity: "unknown" },
        ],
        runtime_installed: true,
        runtime_selection: {
          runtime_profile: "macos-arm64-metal",
          accelerator_label: "Metal",
          engine_name: "llama-server",
          decision_basis: "detected compatible runtime",
          acceleration_confirmed: true,
        },
      },
    });
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");
  await navigateTo(page, "local-ai");

  const cards = page.locator(".local-ai-model-card");
  await expect(cards).toHaveCount(3);
  const boxes = await cards.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().toJSON()),
  );
  expect(
    Math.max(...boxes.map((box) => box.height)) - Math.min(...boxes.map((box) => box.height)),
  ).toBeLessThan(2);
  await expect(cards.nth(0).locator(".ds-status-badge--info")).toHaveText("Downloaded");
  await expect(cards.nth(0).locator(".ds-status-badge--success")).toHaveText("Running");
  await expect(cards.nth(1).locator(".notice-banner--info")).toContainText(
    "You can try E4B on this system.",
  );
  await expect(page.getByText("All models remain visible.")).toHaveCount(0);
  await expectNoGlobalHorizontalOverflow(page);

  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await page.locator(".local-ai-model-choice-grid").screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/model-cards-e2b-running-wide.png`,
    });
  }

  await page.setViewportSize({ width: 400, height: 900 });
  await expectNoGlobalHorizontalOverflow(page);
  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await page.locator(".local-ai-model-choice-grid").screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/model-cards-e2b-running-narrow.png`,
    });
  }

  await page.evaluate(() => localStorage.setItem("aqa.appearance", "light"));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await navigateTo(page, "local-ai");
  await expect(page.locator(".ds-status-badge--info")).toBeVisible();
  await expect(page.locator(".ds-status-badge--success")).toBeVisible();
  await expect(page.locator(".local-ai-model-invitation")).toBeVisible();
  await expectNoGlobalHorizontalOverflow(page);
  if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
    await page.locator(".local-ai-model-choice-grid").screenshot({
      path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/model-cards-e2b-running-light.png`,
    });
  }
});

test("perspective customization remains keyboard-accessible at 320 px", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");
  await setLanguage(page, "de");
  await page.locator("button[aria-controls='setup-discussion-customization']").click();

  const cards = page.locator(".agent-config-row");
  await expect(cards).toHaveCount(3);
  const firstCard = cards.nth(0);
  const perspective = firstCard.getByLabel("Perspektive wählen", { exact: true });
  await expect(perspective).toBeVisible();
  await expect(perspective).toHaveValue("conceptualization");

  const options = firstCard.getByRole("button", { name: "Optionen", exact: true });
  await expect(options).toHaveAttribute("aria-expanded", "false");
  await options.click();
  await expect(options).toHaveAttribute("aria-expanded", "true");
  await expect(
    firstCard.getByRole("region", { name: "Optionen für Perspektive 1", exact: true }),
  ).toBeVisible();

  await perspective.selectOption("skepticism");
  await options.press("Enter");
  await expect(options).toHaveAttribute("aria-expanded", "false");
  await expect(perspective).toHaveValue("skepticism");
  await expectNoGlobalHorizontalOverflow(page);
});

test("discussion split pane preserves workspace across container changes", async ({
  mockedPage: page,
}) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "aqa:discussion-split-pane:v1",
      JSON.stringify({ version: 1, width: 9999 }),
    );
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await navigateTo(page, "discussion");

  const layout = page.locator(".discussion-layout");
  const materialPane = page.locator(".discussion-layout > .material-panel");
  const workspace = page.locator(".discussion-workspace");
  await expect(layout).toBeVisible();
  await expect(layout).not.toHaveClass(/is-mobile-stack/);

  await expect
    .poll(async () => {
      const [material, discussion] = await Promise.all([
        materialPane.boundingBox(),
        workspace.boundingBox(),
      ]);
      return {
        materialWidth: Math.round(material?.width ?? 0),
        workspaceAtLeastMinimum: (discussion?.width ?? 0) >= 480,
      };
    })
    .toEqual({ materialWidth: 640, workspaceAtLeastMinimum: true });

  await page.locator(".material-collapse-btn").click();
  await expect(layout).toHaveClass(/is-material-collapsed/);
  await expect(page.locator(".material-rail")).toBeVisible();
  await page.locator(".material-rail-toggle").click();

  await page.setViewportSize({ width: 1025, height: 768 });
  await expect(layout).toHaveClass(/is-mobile-stack/);
  await expect(page.locator(".material-separator")).toHaveCount(0);
  await expectNoGlobalHorizontalOverflow(page);
});

test("expanded discussion material remains readable after reflow and restored resizing", async ({
  mockedPage: page,
}) => {
  const syntheticMaterial = Array.from(
    { length: 48 },
    (_, index) =>
      `Z${String(index + 1).padStart(4, "0")}: Synthetic research note with a long readable sentence.`,
  ).join("\n");
  await page.route(/\/api\/(defaults\/material|material\/with-line-numbers)$/, (route) =>
    route.fulfill({
      json: route.request().url().endsWith("/defaults/material")
        ? { material: syntheticMaterial, material_type: "document" }
        : { material: syntheticMaterial },
    }),
  );
  await page.route(/\/api\/sessions$/, (route) =>
    route.fulfill({
      json: [
        {
          file_id: "synthetic-reflow",
          title: "Synthetic Layout Review",
          created: "2026-09-23T10:00:00Z",
          updated: "2026-09-23T10:00:00Z",
          round_count: 1,
          session_type: "exploration",
          is_open: false,
          is_favorite: false,
        },
      ],
    }),
  );
  await page.route(/\/api\/sessions\/synthetic-reflow\/open$/, (route) =>
    route.fulfill({
      json: {
        file_id: "synthetic-reflow",
        title: "Synthetic Layout Review",
        material: syntheticMaterial,
        material_context: {
          material_type: "document",
          session_type: "exploration",
          target_language: "English",
          input_values: {},
          input_definitions: [],
        },
        agents: [],
        synthesis: { enabled: false },
        sequential_mode: false,
        round_provider_provenance: [],
        initial_question: "What is visible at this width?",
        has_active_discussion: true,
        has_errors: false,
        round_number: 1,
        round_status: "completed",
        messages: [],
      },
    }),
  );

  for (const language of ["de", "en"] as const) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page.evaluate(() => localStorage.removeItem("aqa:discussion-split-pane:v1"));
    await setLanguage(page, language);
    await navigateTo(page, "discussion");

    const layout = page.locator(".discussion-layout");
    const panel = layout.locator(".material-panel");
    const header = panel.locator(".material-panel-header");
    const content = panel.locator(".material-content");
    const toggle = panel.locator(".material-collapse-btn");
    await expect(toggle).toHaveAttribute(
      "aria-label",
      language === "de" ? "Materialleiste einklappen" : "Collapse Material Panel",
    );
    const assertReadable = async () => {
      await expect(toggle).toBeVisible();
      await expect
        .poll(async () => {
          const [panelBox, headerBox, contentBox, toggleBox] = await Promise.all([
            panel.boundingBox(),
            header.boundingBox(),
            content.boundingBox(),
            toggle.boundingBox(),
          ]);
          return Boolean(
            panelBox &&
            headerBox &&
            contentBox &&
            toggleBox &&
            headerBox.y >= panelBox.y &&
            headerBox.y + headerBox.height <= panelBox.y + panelBox.height &&
            toggleBox.y + toggleBox.height <= panelBox.y + panelBox.height &&
            contentBox.height >= 80 &&
            contentBox.y + contentBox.height <= panelBox.y + panelBox.height,
          );
        })
        .toBe(true);
      expect(await content.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
        true,
      );
      await expectNoGlobalHorizontalOverflow(page);
    };

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1200, height: 600 },
      { width: 1050, height: 500 },
      { width: 900, height: 500 },
      { width: 390, height: 600 },
      { width: 320, height: 480 },
    ]) {
      await page.setViewportSize(viewport);
      await assertReadable();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/discussion-${language}-${viewport.width}x${viewport.height}.png`,
        });
      }
    }

    await toggle.click();
    await expect(layout).toHaveClass(/is-material-collapsed/);
    await page.locator(".material-rail-toggle").click();
    await assertReadable();
    await navigateTo(page, "setup");
    await navigateTo(page, "discussion");
    await assertReadable();

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator(".material-separator").focus();
    await page.keyboard.press("End");
    await expect(page.locator(".material-separator")).toBeFocused();
    await expect(page.locator(".material-separator")).toHaveAttribute("aria-valuenow", "640");
    await page.reload();
    await navigateTo(page, "discussion");
    await expect(page.locator(".material-separator")).toHaveAttribute("aria-valuenow", "640");
    await page.setViewportSize({ width: 900, height: 500 });
    await assertReadable();
    await page.setViewportSize({ width: 1440, height: 900 });
    await assertReadable();
    await navigateTo(page, "sessions");
    await page.locator(".sessions-row .sessions-action-open").click();
    await expect(page.locator(".discussion-shell")).toBeVisible();
    await page.setViewportSize({ width: 900, height: 500 });
    await assertReadable();
  }
});

test("collapsed discussion layout contains its children above Activity", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1470, height: 920 });
  await page.goto("/");
  await navigateTo(page, "discussion");

  const layout = page.locator(".discussion-layout");
  await expect(layout).toBeVisible();
  await page.locator(".material-collapse-btn").click();
  await expect(layout).toHaveClass(/is-material-collapsed/);

  const geometry = await page.evaluate(() => {
    const rect = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const { left, right, top, bottom } = element.getBoundingClientRect();
      return { left, right, top, bottom };
    };

    return {
      layout: rect(".discussion-layout"),
      activity: rect(".activity-log-panel"),
      children: [
        ".discussion-layout > .material-rail",
        ".discussion-layout > .discussion-workspace",
        ".discussion-workspace > .activity-panel",
        ".discussion-workspace > .discussion-view",
        ".discussion-view > .discussion-messages",
      ].map((selector) => ({ selector, box: rect(selector) })),
    };
  });

  expect(geometry.layout).not.toBeNull();
  expect(geometry.activity).not.toBeNull();
  for (const child of geometry.children) {
    expect(child.box, `${child.selector} should exist`).not.toBeNull();
    expect(child.box!.left).toBeGreaterThanOrEqual(geometry.layout!.left - 1);
    expect(child.box!.right).toBeLessThanOrEqual(geometry.layout!.right + 1);
    expect(child.box!.top).toBeGreaterThanOrEqual(geometry.layout!.top - 1);
    expect(child.box!.bottom).toBeLessThanOrEqual(geometry.layout!.bottom + 1);
  }
  expect(geometry.activity!.top).toBeGreaterThanOrEqual(geometry.layout!.bottom - 1);
  await expectNoGlobalHorizontalOverflow(page);
});

for (const language of languages) {
  test(`${language}: narrow modals remain reachable and contained`, async ({
    mockedPage: page,
  }) => {
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("/");
    await setLanguage(page, language);

    const modalLaunchers = [
      {
        id: "external-ai",
        view: "network",
        launcher: ".nc-header .ds-button--primary",
        modal: ".nc-modal",
        editor: true,
      },
      {
        id: "perspective",
        view: "roles",
        launcher: ".rm-header .ds-button--primary",
        modal: ".rm-modal",
        editor: true,
      },
      {
        id: "session-type",
        view: "system",
        launcher: ".pcm-section-header .ds-button--primary",
        modal: ".pcm-modal",
        editor: true,
      },
      {
        id: "global-prompt",
        view: "system",
        launcher: "#pcm-edit-global-research_context",
        modal: ".pcm-modal",
        editor: true,
      },
      {
        id: "quick-action",
        view: "system",
        launcher: "#qam-new-action",
        modal: ".qam-modal",
        editor: true,
      },
    ];

    for (const entry of modalLaunchers) {
      await navigateTo(page, entry.view);
      await page.locator(entry.launcher).first().click();
      const modal = page.locator(entry.modal);
      await expect(modal).toBeVisible();
      await expectNoGlobalHorizontalOverflow(page);

      const bounds = await modal.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(360);

      if (entry.editor) {
        const body = modal.locator(":scope > .ds-editor-dialog-body");
        const footer = modal.locator(":scope > .ds-dialog-footer");
        const primaryAction = footer.locator("button").last();
        await expect(body).toBeVisible();
        await expect(footer).toBeVisible();
        await expect(primaryAction).toBeVisible();
        expect(await modal.evaluate((element) => getComputedStyle(element).overflow)).toBe(
          "hidden",
        );
        expect(await footer.evaluate((element) => getComputedStyle(element).borderTopWidth)).toBe(
          "1px",
        );

        const footerBefore = await footer.boundingBox();
        const actionBounds = await primaryAction.boundingBox();
        expect(footerBefore).not.toBeNull();
        expect(actionBounds).not.toBeNull();
        expect(
          bounds!.x + bounds!.width - (actionBounds!.x + actionBounds!.width),
        ).toBeGreaterThanOrEqual(20);
        expect(
          bounds!.y + bounds!.height - (actionBounds!.y + actionBounds!.height),
        ).toBeGreaterThanOrEqual(16);

        await body.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
        const footerAfter = await footer.boundingBox();
        expect(footerAfter?.y).toBeCloseTo(footerBefore!.y, 0);

        if (entry.id === "external-ai") {
          expect(
            await modal
              .locator(".nc-model-rows")
              .evaluate((element) => getComputedStyle(element).overflowY),
          ).toBe("visible");
        }

        if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
          const root = page.locator("html");
          const originalTheme = await root.getAttribute("data-theme");
          for (const theme of ["light", "dark"] as const) {
            await root.evaluate(
              (element, value) => element.setAttribute("data-theme", value),
              theme,
            );
            await modal.screenshot({
              path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${entry.id}-${theme}.png`,
              animations: "disabled",
            });
          }
          if (originalTheme) {
            await root.evaluate(
              (element, value) => element.setAttribute("data-theme", value),
              originalTheme,
            );
          }
        }
      }

      await page.locator(".modal-overlay").click({ position: { x: 2, y: 2 } });
      await expect(modal).toBeHidden();
    }
  });
}

test("External AI editor keeps one scroll owner and a fixed footer at 320x480", async ({
  mockedPage: page,
}, testInfo) => {
  await page.setViewportSize({ width: 320, height: 480 });
  await page.goto("/");
  await setLanguage(page, "de");
  await page.locator("html").evaluate((element) => element.setAttribute("data-theme", "dark"));
  await navigateTo(page, "network");

  const launcher = page.locator(".nc-header .ds-button--primary");
  await launcher.focus();
  await launcher.click();
  const modal = page.locator(".nc-modal");
  const body = modal.locator(":scope > .ds-editor-dialog-body");
  const footer = modal.locator(":scope > .ds-dialog-footer");
  const save = footer.locator("button").last();

  for (let index = 0; index < 6; index += 1) {
    await modal.locator(".nc-model-actions button").click();
  }
  await save.click();
  await expect(modal.locator(".ds-field__error").first()).toBeVisible();
  await expect(body).toHaveCSS("overflow-y", "auto");
  await expect
    .poll(() => body.evaluate((element) => element.scrollHeight - element.clientHeight))
    .toBeGreaterThan(0);

  const verticalScrollOwners = await modal.evaluate((element) =>
    Array.from(element.querySelectorAll<HTMLElement>("*"))
      .filter((candidate) => {
        const overflow = getComputedStyle(candidate).overflowY;
        return (
          (overflow === "auto" || overflow === "scroll") &&
          candidate.scrollHeight > candidate.clientHeight + 1
        );
      })
      .map((candidate) => candidate.className),
  );
  expect(verticalScrollOwners).toEqual(["ds-editor-dialog-body nc-form"]);

  const footerBefore = await footer.boundingBox();
  await body.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  const footerAfter = await footer.boundingBox();
  expect(footerAfter?.y).toBeCloseTo(footerBefore!.y, 0);
  expect(footerAfter!.y + footerAfter!.height).toBeLessThanOrEqual(480);
  await expectNoGlobalHorizontalOverflow(page);
  await page.screenshot({
    path: testInfo.outputPath("external-ai-editor-de-dark-320x480.png"),
    animations: "disabled",
  });

  await page.keyboard.press("Escape");
  await expect(modal).toBeHidden();
  await expect(launcher).toBeFocused();
});

test("Quick Action bulk restore stays visible but disabled when defaults are unchanged", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "en");
  await navigateTo(page, "system");

  const restoreDefaults = page.getByRole("button", {
    name: "Restore Default Quick Actions",
  });
  await expect(restoreDefaults).toBeVisible();
  await expect(restoreDefaults).toBeDisabled();
  await expect(restoreDefaults).toHaveAttribute(
    "title",
    "All default Quick Actions are present and unchanged.",
  );
  await expectNoGlobalHorizontalOverflow(page);

  await page.setViewportSize({ width: 320, height: 800 });
  await expect(restoreDefaults).toBeVisible();
  await expect(restoreDefaults).toBeDisabled();
  await expectNoGlobalHorizontalOverflow(page);
});

test("core desktop views match visual baselines", async ({ mockedPage: page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await setLanguage(page, "de");

  await expect(page.locator(".setup-token-estimate")).toHaveText(/123/);
  await expectScreenshot(page, "desktop-setup");
  await navigateTo(page, "network");
  await expect(page.locator(".network-config")).toBeVisible();
  await expectScreenshot(page, "desktop-network");
  await navigateTo(page, "system");
  await expect(page.locator(".pcm-manager")).toBeVisible();
  await expectScreenshot(page, "desktop-prompt-configuration");
});

test("core mobile views and modal match visual baselines", async ({ mockedPage: page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await setLanguage(page, "en");

  await expect(page.locator(".setup-token-estimate")).toHaveText(/123/);
  await expectScreenshot(page, "mobile-setup");
  await navigateTo(page, "network");
  await page.locator(".nc-header .ds-button--primary").click();
  await expect(page.locator(".nc-modal")).toBeVisible();
  await expectScreenshot(page, "mobile-network-modal");
});

test("Prepare session textareas begin at one height and retain internal overflow", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const inputs = page.locator(".setup-session-input");
  await expect(inputs).toHaveCount(1);
  await page.locator("button[aria-controls='setup-research-material-context']").click();
  await expect(inputs).toHaveCount(2);
  await page.locator("button[aria-controls='setup-optional-inputs']").click();
  await expect(inputs).toHaveCount(3);

  const heights = await inputs.evaluateAll((elements) =>
    elements.map((element) => Math.round(element.getBoundingClientRect().height)),
  );
  expect(new Set(heights).size).toBe(1);
  const hasOverflowingInput = await inputs.evaluateAll((elements) =>
    elements.some(
      (element) =>
        (element as HTMLTextAreaElement).scrollHeight >
        (element as HTMLTextAreaElement).clientHeight,
    ),
  );
  expect(hasOverflowingInput).toBe(true);
  await expectNoGlobalHorizontalOverflow(page);
});

test("Prepare session textareas keep coherent focus, hover, and vertical resize states", async ({
  mockedPage: page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const firstInput = page.locator(".setup-session-input").first();
  await expect(firstInput).toBeVisible();
  await firstInput.focus();
  await expect(firstInput).toBeFocused();
  await page.waitForTimeout(200);

  const focusedBorder = await firstInput.evaluate(
    (element) => getComputedStyle(element).borderColor,
  );

  await page.mouse.click(10, 10);
  await firstInput.hover();
  await page.waitForTimeout(200);
  const hoverBorder = await firstInput.evaluate((element) => getComputedStyle(element).borderColor);
  expect(focusedBorder).toBe("rgb(139, 233, 229)");
  expect(hoverBorder).toBe("rgb(82, 214, 208)");

  const before = await firstInput.boundingBox();
  expect(before).not.toBeNull();
  await page.mouse.move(
    (before?.x ?? 0) + (before?.width ?? 0) - 4,
    (before?.y ?? 0) + (before?.height ?? 0) - 4,
  );
  await page.mouse.down();
  await page.mouse.move(
    (before?.x ?? 0) + (before?.width ?? 0) - 4,
    (before?.y ?? 0) + (before?.height ?? 0) + 72,
  );
  await page.mouse.up();

  const after = await firstInput.boundingBox();
  expect(after?.height ?? 0).toBeGreaterThan((before?.height ?? 0) + 32);
  expect(await firstInput.evaluate((element) => getComputedStyle(element).resize)).toBe("vertical");
  await expectNoGlobalHorizontalOverflow(page);
});

for (const viewport of [
  { width: 1440, height: 900, expectedHeight: 36 },
  { width: 390, height: 844, expectedHeight: 40 },
] as const) {
  test(`standard text controls share a ${viewport.expectedHeight}px minimum at ${viewport.width}px`, async ({
    mockedPage: page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await setLanguage(page, "en");
    await navigateTo(page, "system");
    const languageBox = await page.locator(".locale-switcher select").boundingBox();
    await navigateTo(page, "roles");
    await expect(page.locator(".role-manager")).toBeVisible();

    const controls = [
      page.locator('button[data-view="setup"]'),
      page.locator(".rm-header .ds-button--secondary"),
      page.locator(".rm-header .ds-button--primary"),
    ];
    expect(Math.round(languageBox?.height ?? 0)).toBeGreaterThanOrEqual(viewport.expectedHeight);
    for (const control of controls) {
      const box = await control.boundingBox();
      expect(Math.round(box?.height ?? 0)).toBeGreaterThanOrEqual(viewport.expectedHeight);
    }
    await expectNoGlobalHorizontalOverflow(page);
  });
}
