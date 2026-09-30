import type { Page } from "@playwright/test";
import { expect, expectNoGlobalHorizontalOverflow, test } from "./fixtures";

type Appearance = "system" | "light" | "dark";

async function mockPreferences(page: Page, language: "en" | "de", appearance: Appearance) {
  const state = {
    ui_locale: language,
    appearance,
    ai_source: "integrated",
    local_ai_context_tokens: 32768,
    local_ai_mtp_enabled: false,
    notifications_enabled: true,
    prevent_sleep_while_generating: true,
    last_active_discussion_id: null,
  };
  await page.route(/\/api\/application\/preferences$/, async (route) => {
    if (route.request().method() === "PUT") Object.assign(state, route.request().postDataJSON());
    await route.fulfill({ json: state });
  });
  return state;
}

async function navigateTo(page: Page, view: string) {
  if (["local-ai", "network", "roles", "preview", "system"].includes(view)) {
    await page.locator("[data-configure-menu]").click();
  }
  await page.locator(`button[data-view="${view}"]`).click();
  await expect(page.locator(`button[data-view="${view}"]`)).toHaveAttribute("aria-current", "page");
}

for (const language of ["en", "de"] as const) {
  test(`${language}: system appearance follows OS and explicit choices persist`, async ({
    mockedPage: page,
  }) => {
    const preferences = await mockPreferences(page, language, "system");
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await navigateTo(page, "system");
    const select = page.getByRole("combobox", {
      name: language === "en" ? "Appearance Mode" : "Darstellungsmodus",
      exact: true,
    });
    await expect(select).toHaveValue("system");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    for (const appearance of ["light", "dark"] as const) {
      await select.selectOption(appearance);
      await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
      await expect.poll(() => preferences.appearance).toBe(appearance);
      await page.emulateMedia({ colorScheme: appearance === "light" ? "dark" : "light" });
      await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
      await page.evaluate(() => localStorage.removeItem("aqa.appearance"));
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
      await navigateTo(page, "system");
      await expect(select).toHaveValue(appearance);
      await select.focus();
      await expect(select).toBeFocused();
    }
    await select.selectOption("system");
    await expect.poll(() => preferences.appearance).toBe("system");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  for (const appearance of ["light", "dark"] as const) {
    for (const width of [1440, 320]) {
      test(`${language}: ${appearance} representative views fit ${width}px`, async ({
        mockedPage: page,
      }, testInfo) => {
        await mockPreferences(page, language, appearance);
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/");
        await expect(page.locator("html")).toHaveAttribute(
          "lang",
          new RegExp(`^${language}(?:-|$)`),
        );
        await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
        for (const view of [
          "setup",
          "discussion",
          "sessions",
          "local-ai",
          "network",
          "roles",
          "preview",
          "system",
        ]) {
          await navigateTo(page, view);
          await expectNoGlobalHorizontalOverflow(page);
          await page.evaluate(() => document.fonts.ready);
          await page.screenshot({
            path: testInfo.outputPath(`${language}-${appearance}-${width}-${view}.png`),
            animations: "disabled",
            fullPage: true,
          });
        }
        await page.goto("/?gallery=components");
        await expect(page.locator(".ds-gallery")).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
        await expectNoGlobalHorizontalOverflow(page);
        await page.screenshot({
          path: testInfo.outputPath(`${language}-${appearance}-${width}-gallery.png`),
          animations: "disabled",
          fullPage: true,
        });
      });
    }
  }
}

for (const appearance of ["light", "dark"] as const) {
  for (const width of [1440, 320]) {
    test(`${appearance}: populated discussion and host dialog fit ${width}px`, async ({
      mockedPage: page,
    }, testInfo) => {
      await mockPreferences(page, "en", appearance);
      await page.route(/\/api\/sessions$/, async (route) => {
        await route.fulfill({
          json: [
            {
              file_id: "appearance-review",
              title: "Shared Decisions",
              created: "2026-09-15T10:00:00Z",
              updated: "2026-09-15T10:00:00Z",
              round_count: 1,
              session_type: "exploration",
              is_open: true,
              is_favorite: false,
            },
          ],
        });
      });
      await page.route(/\/api\/sessions\/appearance-review\/open$/, async (route) => {
        const shared = {
          round_number: 1,
          status: "completed",
          note: "",
          include_in_agent_context: true,
        };
        await route.fulfill({
          json: {
            file_id: "appearance-review",
            title: "Shared Decisions",
            material_context: {
              material_type: "interview",
              session_type: "exploration",
              target_language: "English",
              input_values: {},
              input_definitions: [],
            },
            agents: [
              {
                name: "Conceptualization",
                prompt_id: "conceptualization",
                client_id: "agent-1",
                color: "#00c0c0",
                enabled: true,
                perspective_number: 1,
                llm_id: "research-model",
                api_host: "http://127.0.0.1:8080/v1",
              },
            ],
            synthesis: { enabled: true },
            sequential_mode: false,
            round_provider_provenance: [],
            material:
              "01  Participant: Shared decisions help our team.\n02  Interviewer: What happens when people disagree?\n03  Participant: We make room for different interpretations.",
            initial_question: "How do participants negotiate shared decisions?",
            has_active_discussion: true,
            has_errors: false,
            round_number: 1,
            round_status: "completed",
            messages: [
              {
                ...shared,
                id: "question",
                role: "user",
                content: "How do participants negotiate shared decisions?",
              },
              {
                ...shared,
                id: "perspective",
                role: "agent",
                agent_name: "Conceptualization",
                agent_index: 0,
                perspective_number: 1,
                theory_label: "Conceptualization",
                color: "#00c0c0",
                content:
                  "## Negotiating Participation\n\n**Shared decisions** involve competing interpretations. The material highlights `different interpretations` in Z0003.\n\n> We make room for different interpretations.\n\n- Participation remains negotiated.\n- Disagreement creates an opportunity to clarify meaning.\n\n[Research reference](https://example.org/research)",
              },
              {
                ...shared,
                id: "synthesis",
                role: "synthesis",
                include_in_agent_context: false,
                content:
                  "## Shared Findings\n\n- **Participation:** Joint decisions depend on making disagreement visible.\n- **Open question:** Who gets to define an acceptable interpretation?",
              },
            ],
          },
        });
      });
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/");
      await navigateTo(page, "sessions");
      await page.getByRole("button", { name: "Open", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Negotiating Participation" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Shared Findings" })).toBeVisible();
      await expectNoGlobalHorizontalOverflow(page);
      await page.screenshot({
        path: testInfo.outputPath(`en-${appearance}-${width}-populated-discussion.png`),
        fullPage: true,
      });
      await navigateTo(page, "network");
      await page.locator(".nc-header").getByRole("button").click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expectNoGlobalHorizontalOverflow(page);
      await page.screenshot({
        path: testInfo.outputPath(`en-${appearance}-${width}-host-dialog.png`),
        fullPage: true,
      });
    });
  }
}
