import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type APIRequestContext, type CDPSession, type Page } from "@playwright/test";

const PROVIDER_URL = "http://127.0.0.1:4175/v1";
const MODEL_ID = "aqa-e2e-model";
const SUSTAINED_STREAM_SENTINEL = "AQA_E2E_SUSTAINED_STREAM";

type BrandMeasurement = {
  activeFrameDeltas: number[];
  idleFrameDeltas: number[];
  animationStarts: number;
  animationCancels: number;
  animationIterations: number;
  participantReplacements: number;
  rootReplacements: number;
  backwardsProgressSteps: number;
  maxForwardProgressStep: number;
  longTasks: Array<{ duration: number; startTime: number }>;
};

async function ensureExternalHost(request: APIRequestContext): Promise<void> {
  const created = await request.post("/api/hosts", {
    data: {
      label: "I01 performance provider",
      url: PROVIDER_URL,
      model: MODEL_ID,
      models: [MODEL_ID],
      is_favorite: true,
    },
  });
  expect(created.ok()).toBe(true);
}

async function startDiscussion(page: Page): Promise<void> {
  await page.getByLabel(/target language|zielsprache/i).fill("English");
  await page.locator('[aria-controls="setup-discussion-customization"]').click();
  await page.locator(".synthesis-enabled-toggle input").uncheck();
  const start = page.getByRole("button", { name: /start discussion|diskussion starten/i });
  await expect(start).toBeEnabled({ timeout: 20_000 });
  await start.click();
  await expect(page.locator(".discussion-message.message-agent")).toHaveCount(3, {
    timeout: 20_000,
  });
}

async function continueWith(
  page: Page,
  text: string,
  expectedAgentMessages: number,
): Promise<void> {
  await page.locator(".followup-area textarea").fill(text);
  await page.locator(".followup-area > .ds-button--primary").click();
  await expect(page.locator(".discussion-message.message-agent")).toHaveCount(
    expectedAgentMessages,
    { timeout: 45_000 },
  );
  await expect(page.locator("[data-aqa-brand]")).toHaveAttribute("data-aqa-generating", "false", {
    timeout: 45_000,
  });
}

async function startBrowserTrace(session: CDPSession): Promise<void> {
  await session.send("Tracing.start", {
    categories: [
      "blink.user_timing",
      "devtools.timeline",
      "disabled-by-default-devtools.timeline",
      "disabled-by-default-devtools.timeline.frame",
    ].join(","),
    transferMode: "ReturnAsStream",
  });
}

async function stopBrowserTrace(session: CDPSession): Promise<string> {
  const completed = new Promise<{ stream: string }>((resolveComplete) => {
    session.once("Tracing.tracingComplete", (event) =>
      resolveComplete(event as { stream: string }),
    );
  });
  await session.send("Tracing.end");
  const { stream } = await completed;
  let trace = "";
  for (;;) {
    const chunk = (await session.send("IO.read", { handle: stream })) as {
      data: string;
      eof?: boolean;
    };
    trace += chunk.data;
    if (chunk.eof) break;
  }
  await session.send("IO.close", { handle: stream });
  return trace;
}

test("I01 records brand continuity under sustained generation", async ({ page, request }) => {
  await ensureExternalHost(request);
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem("aqa.uiLocale.v1", "en");
    window.localStorage.setItem("aqa.aiSource.v1", "external");
  });
  await page.goto("/");
  await expect(page.locator(".app-shell")).toBeVisible();
  await startDiscussion(page);

  // Warm up the complete streaming/rendering path and leave a large Markdown
  // response in history so the measured round exercises a growing discussion.
  await continueWith(page, SUSTAINED_STREAM_SENTINEL, 6);
  await page.locator(".activity-log-toggle").click();
  await expect(page.locator(".activity-log")).toBeVisible();

  await page.evaluate(() => {
    const root = document.querySelector<HTMLElement>("[data-aqa-brand]");
    if (!root) throw new Error("AQA brand root is missing");
    const participants = Array.from(root.querySelectorAll<HTMLElement>("[data-aqa-wave]"));
    const animations = participants.map((participant) => participant.getAnimations()[0]);
    const measurement: BrandMeasurement = {
      activeFrameDeltas: [],
      idleFrameDeltas: [],
      animationStarts: 0,
      animationCancels: 0,
      animationIterations: 0,
      participantReplacements: 0,
      rootReplacements: 0,
      backwardsProgressSteps: 0,
      maxForwardProgressStep: 0,
      longTasks: [],
    };
    let previousFrame: number | null = null;
    let previousProgress: number | null = null;
    let previousGenerating = false;
    let frameRequest = 0;

    const onAnimationStart = () => (measurement.animationStarts += 1);
    const onAnimationCancel = () => (measurement.animationCancels += 1);
    const onAnimationIteration = () => (measurement.animationIterations += 1);
    root.addEventListener("animationstart", onAnimationStart, true);
    root.addEventListener("animationcancel", onAnimationCancel, true);
    root.addEventListener("animationiteration", onAnimationIteration, true);

    const longTaskObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        measurement.longTasks.push({ duration: entry.duration, startTime: entry.startTime });
      }
    });
    try {
      longTaskObserver.observe({ entryTypes: ["longtask"] });
    } catch {
      // The remaining continuity metrics work in engines without Long Tasks.
    }

    const sample = (timestamp: number) => {
      const currentRoot = document.querySelector<HTMLElement>("[data-aqa-brand]");
      if (currentRoot !== root) measurement.rootReplacements += 1;
      participants.forEach((participant) => {
        if (!participant.isConnected) measurement.participantReplacements += 1;
      });
      const generating = root.dataset.aqaGenerating === "true";
      if (previousFrame !== null) {
        (generating ? measurement.activeFrameDeltas : measurement.idleFrameDeltas).push(
          timestamp - previousFrame,
        );
      }
      const progress = animations[0]?.effect?.getComputedTiming().progress;
      if (generating && previousGenerating && typeof progress === "number") {
        if (previousProgress !== null) {
          let delta = progress - previousProgress;
          if (delta < -0.5) delta += 1;
          if (delta < -0.02) measurement.backwardsProgressSteps += 1;
          measurement.maxForwardProgressStep = Math.max(measurement.maxForwardProgressStep, delta);
        }
        previousProgress = progress;
      } else {
        previousProgress = typeof progress === "number" ? progress : null;
      }
      previousGenerating = generating;
      previousFrame = timestamp;
      frameRequest = requestAnimationFrame(sample);
    };
    frameRequest = requestAnimationFrame(sample);

    Object.assign(window, {
      __aqaStopBrandMeasurement: () => {
        cancelAnimationFrame(frameRequest);
        longTaskObserver.disconnect();
        root.removeEventListener("animationstart", onAnimationStart, true);
        root.removeEventListener("animationcancel", onAnimationCancel, true);
        root.removeEventListener("animationiteration", onAnimationIteration, true);
        return measurement;
      },
    });
  });

  const cdp = await page.context().newCDPSession(page);
  await startBrowserTrace(cdp);
  await continueWith(page, SUSTAINED_STREAM_SENTINEL, 9);
  await page.waitForTimeout(4_000);
  const trace = await stopBrowserTrace(cdp);
  const measurement = await page.evaluate(() => {
    const stop = (window as typeof window & { __aqaStopBrandMeasurement?: () => BrandMeasurement })
      .__aqaStopBrandMeasurement;
    if (!stop) throw new Error("Brand measurement hook is missing");
    return stop();
  });

  const outputDirectory = resolve(
    process.cwd(),
    "../dist/overnight-remediation/20260905-1640/measurements",
  );
  await mkdir(outputDirectory, { recursive: true });
  const label = process.env.AQA_I01_MEASUREMENT_LABEL ?? "measurement";
  await Promise.all([
    writeFile(resolve(outputDirectory, `i01-${label}.json`), JSON.stringify(measurement, null, 2)),
    writeFile(resolve(outputDirectory, `i01-${label}-trace.json`), trace),
  ]);

  expect(measurement.activeFrameDeltas.length).toBeGreaterThan(100);
  expect(measurement.animationIterations).toBeGreaterThan(100);
  expect(measurement.animationStarts).toBe(0);
  expect(measurement.rootReplacements).toBe(0);
  expect(measurement.participantReplacements).toBe(0);
  expect(measurement.animationCancels).toBe(0);
});
