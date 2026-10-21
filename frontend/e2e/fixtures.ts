import { test as base, expect, type Page } from "@playwright/test";

const longMaterial = [
  "01  Interviewmaterial mit absichtlich langen Zeilen für die Responsive-Prüfung.",
  "02  Die Anwendung darf dadurch niemals einen globalen horizontalen Scrollbereich erzeugen.",
  "03  https://example.invalid/a/very/long/path/that/must/wrap/or/scroll/only/inside/its/component",
].join("\n");

const roles = [
  {
    id: "conceptualization",
    label: "Conceptualization",
    description:
      "Develops concepts, tensions, and process logics while remaining grounded in the material.",
    role: "Develop concepts, tensions, and process logics from the material.",
    task: "Keep the reading grounded in the evidence.",
    output_format: "Continuous prose with material references.",
    editable: false,
    is_shipped: true,
    origin: "shipped_default",
  },
  {
    id: "precision",
    label: "Precision",
    description:
      "Checks interpretations against wording and evidence and refines overextended claims.",
    role: "Check interpretations against wording and evidence.",
    task: "Refine overextended claims.",
    output_format: "Continuous prose with precise textual anchors.",
    editable: false,
    is_shipped: true,
    origin: "shipped_default",
  },
  {
    id: "skepticism",
    label: "Skepticism",
    description:
      "Develops plausible rival readings and identifies evidence that could distinguish them.",
    role: "Develop plausible rival readings from the evidence.",
    task: "Identify evidence that could distinguish competing readings.",
    output_format: "Continuous prose with material references.",
    editable: false,
    is_shipped: true,
    origin: "shipped_default",
  },
];

const setupSessionInputs = [
  {
    key: "research_material_context",
    label: "Material Context",
    hint: "Optional context about the material and how it was collected.",
    default_text:
      "## Research Topic and Question\n\n…\n\n## Information on the Case / Material, Speaker Assignment, etc.\n\n…\n\n## Important Terms and Background Knowledge\n\n…",
    prompt_heading: "RESEARCH MATERIAL CONTEXT",
    required: false,
  },
  {
    key: "main_input",
    label: "Exploration Task",
    hint: "An exploration task to begin the open analysis.",
    default_text:
      "Explore the material, developing hypotheses while staying grounded in the actual text. Draw out recurring patterns, breaks, tensions, and plausible alternative interpretations.",
    prompt_heading: "MAIN INPUT",
    required: true,
  },
  {
    key: "additional_instructions",
    label: "Additional Instructions",
    hint: "Optional guidance for the analysis.",
    default_text: "",
    prompt_heading: "ADDITIONAL INSTRUCTIONS",
    required: false,
  },
];

const sessionTypes = [
  {
    key: "exploration",
    label: "Open Exploration",
    description: "Explore the material, focusing on patterns and possible interpretations.",
    inputs: setupSessionInputs,
  },
  {
    key: "critique",
    label: "Interpretation Review",
    description: "Critically examine an interpretation.",
    inputs: setupSessionInputs,
  },
];

const promptSessionTypes = sessionTypes.map((item, index) => ({
  ...item,
  description: "A detailed description for realistic wrapping tests.",
  default_agent_prompt_ids:
    index === 0 ? roles.map((role) => role.id) : [...roles].reverse().map((role) => role.id),
  body: "Consider the research context provided.",
  is_shipped: true,
  origin: "shipped_default",
}));

const hosts = [
  {
    label: "Lokales Forschungsmodell mit langem Anzeigenamen",
    url: "http://127.0.0.1:8080/v1",
    model: "research-model-with-a-deliberately-long-identifier",
    models: ["research-model-with-a-deliberately-long-identifier", "alternative-analysis-model"],
    kind: "openai_compatible",
    has_api_key: true,
    is_favorite: true,
  },
];

const localAIStatus = {
  state: "not_installed",
  model_id: null,
  model_name: null,
  preferred_model_id: "gemma-4-e2b",
  recommended_model: "gemma-4-e2b",
  download_bytes: 0,
  download_total: 0,
  context_tokens: 131072,
  mtp_enabled: false,
  mtp_draft_tokens: null,
  accelerator_label: "Metal",
  host_ready: false,
  message: null,
  integrity: "unknown",
  os_label: "macOS",
  cpu_label: "Apple Silicon",
  gpu_label: "Integrated GPU",
  ram_gb: 16,
  models: [
    { model_id: "gemma-4-e2b", installed: false, integrity: "unknown" },
    { model_id: "gemma-4-e4b", installed: false, integrity: "unknown" },
  ],
  runtime_installed: false,
  runtime_selection: {
    runtime_profile: "macos-arm64-metal",
    accelerator_label: "Metal",
    engine_name: "llama-server",
    decision_basis: "detected compatible runtime",
  },
};

function payloadFor(url: URL): unknown {
  const path = url.pathname;

  if (path === "/api/application/status") return { can_quit: false, quit_token: null };
  if (path === "/api/discussions/perspectives") {
    return roles.map(({ id, label, description }) => ({ id, label, description }));
  }
  if (path === "/api/discussions/session-types") return sessionTypes;
  if (path === "/api/discussions/defaults/agents") return roles.map((role) => role.id);
  if (path === "/api/discussions/defaults/interpretation") {
    return {
      text: "Welche Deutungsmuster und Gegenbeispiele sind im Material erkennbar?",
      hint: "Eine präzise Frage unterstützt die Analyse.",
      description: "Offene qualitative Exploration",
      interpretation_required: false,
    };
  }
  if (path === "/api/defaults/material") {
    return { material: longMaterial, material_type: "document" };
  }
  if (path === "/api/material/token-estimate") {
    return { approximate_tokens: 123, tokenizer: "o200k_base" };
  }
  if (path === "/api/defaults/collection-context") {
    return { template: "Leitfadengestützte Interviews, erhoben in mehreren Forschungskontexten." };
  }
  if (path === "/api/material/with-line-numbers") return { material: longMaterial };
  if (path === "/api/discussions/state") {
    return {
      material: "",
      initial_question: "",
      messages: [],
      round_number: 0,
      has_active_discussion: false,
    };
  }
  if (path === "/api/sessions") return [];
  if (path === "/api/quick-actions") {
    return { actions: [], can_restore_defaults: false };
  }
  if (path === "/api/hosts") return hosts;
  if (path === "/api/prompts/roles") return roles;
  if (path === "/api/prompts/session-types") return promptSessionTypes;
  if (path === "/api/prompts/globals") {
    return [
      {
        id: "research_context",
        label: "Übergreifender Forschungskontext mit langer Bezeichnung",
        scope: null,
        content: "Arbeite transparent, materialnah und ohne unbelegte Schlussfolgerungen.",
        is_shipped: true,
        origin: "shipped_default",
      },
    ];
  }
  if (path === "/api/preview/templates") {
    return [
      {
        id: "conceptualization",
        label: "Conceptualization",
        source_file: "roles/conceptualization.poml",
      },
    ];
  }
  if (path === "/api/preview/globals") {
    return [
      {
        id: "research_context",
        label: "Forschungskontext",
        scope: null,
        content: "Globale Anweisung",
      },
    ];
  }
  if (path.startsWith("/api/preview/")) {
    return {
      template_id: "conceptualization",
      label: "Conceptualization",
      mode: "single_agent",
      char_count: 1240,
      approx_tokens: 310,
      segments: {
        globals: "Arbeite transparent und materialnah.",
        context: "Forschungskontext mit absichtlich ausführlicher Beschreibung.",
        role: "Du bist eine qualitative Forscherin.",
        task: "Analysiere Muster, Spannungen und Gegenbeispiele.",
        output_format: "Markdown mit nachvollziehbaren Materialbelegen.",
      },
      rendered_prompt: `${longMaterial}\n\n${longMaterial}`,
      session_type: "offene_exploration",
      session_label: "Offene Exploration",
    };
  }
  if (path === "/api/local-ai/status") return localAIStatus;
  if (path === "/api/local-ai/diagnostics") {
    return {
      runtime_directory: "/mock/runtime",
      model_directory: "/mock/models",
      command_reference: null,
      runtime_installed: false,
    };
  }
  if (path === "/api/local-ai/recommendation") {
    return {
      model_id: "gemma-4-e2b",
      model_name: "Gemma 4 E2B",
      reason: "Empfohlen für die erkannte Hardware.",
      runtime_selection: localAIStatus.runtime_selection,
    };
  }

  return {};
}

async function installApiMocks(page: Page): Promise<void> {
  // Match only root-level backend endpoints. A broad `**/api/**` glob also
  // intercepts Vite source modules under paths such as `/src/api/client.ts`
  // and incorrectly serves JSON in place of JavaScript.
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const referrer = request.headers().referer;
    const contextScenario = referrer ? new URL(referrer).searchParams.get("e2e-context") : null;
    const payload =
      url.pathname === "/api/discussions/context-estimate" && contextScenario === "overflow"
        ? {
            known: true,
            estimated_input_tokens: 43_166,
            available_input_tokens: 28_672,
            context_window_tokens: 32_768,
            reserved_output_tokens: 4_096,
            overflow: true,
          }
        : payloadFor(url);
    const body = JSON.stringify(payload);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body,
    });
  });
}

type ResponsiveFixtures = {
  mockedPage: Page;
};

export const test = base.extend<ResponsiveFixtures>({
  mockedPage: async ({ page }, use) => {
    await installApiMocks(page);
    await page.addInitScript(() => {
      // Match visual baselines without depending on fonts installed on the runner.
      const inter = new FontFace(
        "Inter",
        'url("/node_modules/@fontsource-variable/inter/files/inter-latin-standard-normal.woff2")',
        { weight: "100 900" },
      );
      document.fonts.add(inter);
      void inter.load();
      if (!window.sessionStorage.getItem("aqa.e2e.initialized")) {
        window.localStorage.clear();
        window.sessionStorage.setItem("aqa.e2e.initialized", "1");
      }
    });
    await use(page);
  },
});

export async function setLanguage(page: Page, language: "de" | "en"): Promise<void> {
  await page.evaluate((nextLanguage) => {
    window.localStorage.setItem("aqa.uiLocale.v1", nextLanguage);
  }, language);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", new RegExp(`^${language}(?:-|$)`));
}

export async function expectNoGlobalHorizontalOverflow(page: Page): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(() => ({
          // clientWidth excludes a reserved vertical scrollbar in Chromium.
          // Compare with the viewport instead so a page that simply scrolls
          // vertically is not misreported as horizontally overflowing.
          body: Math.max(0, document.body.scrollWidth - window.innerWidth),
          root: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
        })),
      { message: "The page must not own a horizontal overflow region." },
    )
    .toEqual({ body: 0, root: 0 });
}

export async function expectScreenshot(page: Page, name: string): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.load('400 24px "Material Symbols Rounded"');
    await document.fonts.load('400 24px "Material Symbols Rounded Filled"');
    await document.fonts.ready;
  });
  await expect(page).toHaveScreenshot(`${name}.png`, {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
  });
}

export { expect };
