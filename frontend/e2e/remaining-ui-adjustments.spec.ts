import { expect, expectNoGlobalHorizontalOverflow, setLanguage, test } from "./fixtures";

const host = {
  configuration_id: "Lokale KI",
  label: "Integrated AI",
  url: "http://127.0.0.1:8080",
  model: "gemma-4-E2B-it",
  models: ["gemma-4-E2B-it", "gemma-4-E4B-it"],
  kind: "local_ai",
  has_api_key: false,
  is_favorite: false,
};

for (const language of ["de", "en"] as const) {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 900 },
    { name: "narrow", width: 390, height: 844 },
  ]) {
    test(`${language} ${viewport.name}: context reset and installed model choices`, async ({
      mockedPage: page,
    }) => {
      let savedContext = 65_536;
      let e4bInstalled = false;
      await page.route(/\/api\/application\/preferences$/, async (route) => {
        if (route.request().method() === "PUT") {
          const body = route.request().postDataJSON() as { local_ai_context_tokens?: number };
          savedContext = body.local_ai_context_tokens ?? savedContext;
        }
        await route.fulfill({
          json: {
            ui_locale: language,
            appearance: "system",
            ai_source: "integrated",
            local_ai_context_tokens: savedContext,
            local_ai_context_default_tokens: 32_768,
            local_ai_mtp_enabled: false,
            notifications_enabled: true,
            prevent_sleep_while_generating: true,
            last_active_discussion_id: null,
          },
        });
      });
      await page.route(/\/api\/hosts$/, (route) => route.fulfill({ json: [host] }));
      await page.route(/\/api\/local-ai\/status$/, (route) =>
        route.fulfill({
          json: {
            state: "running",
            model_id: "gemma-4-e2b",
            model_name: "Gemma 4 E2B",
            preferred_model_id: "gemma-4-e2b",
            download_bytes: 0,
            download_total: 0,
            context_tokens: 49_152,
            mtp_enabled: false,
            mtp_draft_tokens: null,
            host_ready: true,
            integrity: "verified",
            models: [
              {
                model_id: "gemma-4-e2b",
                api_alias: "gemma-4-E2B-it",
                installed: true,
                integrity: "verified",
              },
              {
                model_id: "gemma-4-e4b",
                api_alias: "gemma-4-E4B-it",
                installed: e4bInstalled,
                integrity: e4bInstalled ? "verified" : "unknown",
              },
            ],
            runtime_installed: true,
            runtime_selection: { acceleration_confirmed: true, runtime_installed: true },
          },
        }),
      );
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");
      await setLanguage(page, language);
      await page.locator('[aria-controls="setup-discussion-customization"]').click();
      await page.locator(".agent-config-row .agent-config-options-toggle").first().click();
      const model = page
        .locator(".agent-config-row select")
        .filter({ has: page.locator('option[value="gemma-4-E4B-it"]') })
        .first();
      await expect(model.locator('option[value="gemma-4-E2B-it"]')).not.toHaveAttribute(
        "disabled",
        "",
      );
      await expect(model.locator('option[value="gemma-4-E4B-it"]')).toHaveAttribute("disabled", "");
      await model.focus();
      await model.press("End");
      await expect(model).toHaveValue("gemma-4-E2B-it");
      e4bInstalled = true;
      await page.locator("[data-configure-menu]").click();
      await page.locator('button[data-view="local-ai"]').click();
      await page.locator(".local-ai-advanced > summary").click();
      const input = page.locator("#local-ai-context");
      await expect(input).toHaveValue(language === "de" ? "65.536" : "65,536");
      await expect(page.locator(".local-ai-context-reset")).toBeVisible();
      await input.fill("70000");
      await expect(page.locator("#local-ai-context-unsaved")).toBeVisible();
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page
          .locator(".local-ai-field")
          .first()
          .screenshot({
            path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-context-edited.png`,
          });
      }
      await page.locator(".local-ai-context-reset").click();
      await expect(input).toHaveValue(language === "de" ? "32.768" : "32,768");
      await expect(input).toBeFocused();
      expect(savedContext).toBe(32_768);
      await expect(page.locator(".local-ai-context-reset")).toHaveCount(0);
      await expect(page.locator(".local-ai-field").first()).toContainText(/49[., ]?152/);
      await expectNoGlobalHorizontalOverflow(page);
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-context-reset.png`,
        });
      }
      await page.locator('button[data-view="setup"]').click();
      if (!(await page.locator("#setup-discussion-customization").isVisible())) {
        await page.locator('[aria-controls="setup-discussion-customization"]').click();
      }
      if (!(await page.locator(".agent-config-row .agent-config-advanced").first().isVisible())) {
        await page.locator(".agent-config-row .agent-config-options-toggle").first().click();
      }
      const refreshedModel = page
        .locator(".agent-config-row select")
        .filter({ has: page.locator('option[value="gemma-4-E4B-it"]') })
        .first();
      await expect(refreshedModel.locator('option[value="gemma-4-E4B-it"]')).not.toHaveAttribute(
        "disabled",
        "",
      );
    });
  }
}

for (const language of ["de", "en"] as const) {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 900 },
    { name: "narrow", width: 390, height: 844 },
  ]) {
    test(`${language} ${viewport.name}: Discuss retains an unavailable local selection and allows valid replacement`, async ({
      mockedPage: page,
    }) => {
      await page.route(/\/api\/hosts$/, (route) => route.fulfill({ json: [host] }));
      await page.route(/\/api\/local-ai\/status$/, (route) =>
        route.fulfill({
          json: {
            state: "stopped",
            model_id: "gemma-4-e2b",
            preferred_model_id: "gemma-4-e2b",
            host_ready: false,
            integrity: "verified",
            runtime_installed: true,
            models: [
              {
                model_id: "gemma-4-e2b",
                api_alias: "gemma-4-E2B-it",
                installed: true,
                integrity: "verified",
              },
              {
                model_id: "gemma-4-e4b",
                api_alias: "gemma-4-E4B-it",
                installed: false,
                integrity: "unknown",
              },
            ],
            runtime_selection: { acceleration_confirmed: true, runtime_installed: true },
          },
        }),
      );
      await page.route(/\/api\/sessions$/, (route) =>
        route.fulfill({
          json: [
            {
              file_id: "synthetic-ui",
              title: "Synthetic UI Review",
              created: "2026-09-24T10:00:00Z",
              updated: "2026-09-24T10:00:00Z",
              round_count: 1,
              session_type: "exploration",
              is_open: false,
              is_favorite: false,
            },
          ],
        }),
      );
      await page.route(/\/api\/sessions\/synthetic-ui\/open$/, (route) =>
        route.fulfill({
          json: {
            file_id: "synthetic-ui",
            title: "Synthetic UI Review",
            material: "Synthetic material",
            material_context: {
              material_type: "document",
              session_type: "exploration",
              target_language: "English",
              input_values: {},
              input_definitions: [],
            },
            agents: [
              {
                name: "Perspective",
                client_id: "agent-1",
                prompt_id: "conceptualization",
                color: "#2563eb",
                temperature: null,
                llm_id: "gemma-4-E4B-it",
                api_host: host.url,
                host_configuration_id: host.configuration_id,
                host_label: host.label,
                api_key: null,
                max_tokens: null,
                enabled: true,
                perspective_number: 1,
              },
            ],
            synthesis: {
              enabled: true,
              llm_id: "gemma-4-E4B-it",
              api_host: host.url,
              host_configuration_id: host.configuration_id,
              host_label: host.label,
              temperature: null,
            },
            sequential_mode: false,
            round_provider_provenance: [],
            initial_question: "Synthetic question",
            has_active_discussion: true,
            has_errors: false,
            round_number: 1,
            round_status: "completed",
            messages: [
              {
                id: "u1",
                role: "user",
                content: "Synthetic question",
                round_number: 1,
                note: "",
                include_in_agent_context: true,
              },
            ],
          },
        }),
      );
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");
      await setLanguage(page, language);
      await page.locator('button[data-view="sessions"]').click();
      await page.locator(".sessions-row .sessions-action-open").click();
      const configure = page.locator(
        'button[aria-controls="activity-perspective-options-agent-1"]',
      );
      await expect(configure).toBeVisible();
      await configure.click();
      const model = page
        .locator("#activity-perspective-options-agent-1 select")
        .filter({ has: page.locator('option[value="gemma-4-E4B-it"]') });
      await expect(model).toHaveValue("");
      await expect(model).toHaveAttribute("aria-invalid", "true");
      await expect(model.locator('option[value="gemma-4-E4B-it"]')).toHaveAttribute("disabled", "");
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-discuss-unavailable-selection.png`,
        });
      }
      await model.focus();
      await expect(model).toBeFocused();
      await model.press("Tab");
      await expect(model).not.toBeFocused();
      await model.selectOption("gemma-4-E2B-it");
      await expect(model).toHaveValue("gemma-4-E2B-it");
      await page.locator('button[aria-controls="activity-synthesis-options"]').click();
      const synthesisModel = page
        .locator("#activity-synthesis-options select")
        .filter({ has: page.locator('option[value="gemma-4-E4B-it"]') });
      await expect(synthesisModel.locator('option[value="gemma-4-E4B-it"]')).toHaveAttribute(
        "disabled",
        "",
      );
      await expectNoGlobalHorizontalOverflow(page);
      if (process.env.AQA_VISUAL_EVIDENCE_DIR) {
        await page.screenshot({
          path: `${process.env.AQA_VISUAL_EVIDENCE_DIR}/${language}-${viewport.name}-discuss-unavailable-model.png`,
        });
      }
    });
  }
}
