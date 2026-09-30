import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import PromptPreview from "./PromptPreview";
import { setLocale } from "../i18n";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function previewResponse(estimatedTokens: number | null = 12): Response {
  return jsonResponse({
    template_id: "rt_skeptiker",
    label: "The Skeptic",
    mode: "single_agent",
    char_count: 42,
    estimated_tokens: estimatedTokens,
    tokenizer_name: "o200k_base",
    prompt_sources: [
      { key: "output_format", content: "Output" },
      { key: "role", content: "Role" },
      { key: "context", content: "Context" },
      { key: "globals", content: "Globals" },
      { key: "task", content: "Task" },
    ],
    system_prompt: "System prompt",
    user_prompt: "User prompt",
    session_type: "critique",
    session_label: "Critique",
  });
}

async function mountPreview(estimatedTokens: number | null = 12) {
  globalThis.fetch = vi.fn(async (input: unknown) => {
    const url = String(input);
    if (url.endsWith("/api/preview/templates")) {
      return jsonResponse([{ id: "rt_skeptiker", label: "The Skeptic" }]);
    }
    if (url.endsWith("/api/discussions/session-types")) {
      return jsonResponse([{ key: "critique", label: "Critique" }]);
    }
    if (url.startsWith("/api/preview/rt_skeptiker?")) return previewResponse(estimatedTokens);
    throw new Error(`Unexpected request: ${url}`);
  }) as unknown as typeof fetch;

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<PromptPreview />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return { container, root };
}

afterEach(async () => {
  await setLocale("de");
  document.body.replaceChildren();
});

describe("PromptPreview", () => {
  it("uses clear setup controls and request cards without duplicate global blocks", async () => {
    await setLocale("en");
    const { container, root } = await mountPreview();

    expect(container.querySelector(".preview-setup-card")).not.toBeNull();
    expect(container.querySelector(".preview-refresh")).toBeNull();
    expect(container.querySelector("#template-select")?.textContent).toBe("The Skeptic");
    expect(container.querySelector("#preview-perspectives")?.textContent).toContain(
      "Multiple Perspectives",
    );
    expect(container.querySelector(".preview-message-card")?.textContent).toContain(
      "System prompt",
    );
    expect(container.querySelector<HTMLElement>(".preview-prompt-text")?.tabIndex).toBe(0);
    expect(container.querySelector(".preview-prompt-text")?.getAttribute("aria-label")).toBe(
      "Full System Prompt",
    );
    expect(container.textContent).toContain("Full System Prompt");
    expect(container.textContent).toContain("Full User Message");
    expect(container.textContent).toContain("~12 Tokens");
    expect(container.textContent).not.toContain("o200k_base");
    expect(container.textContent).not.toContain("Estimated Tokens");
    expect(container.textContent).not.toContain("This later-round example includes");
    expect(container.querySelector(".preview-globals-ref")).toBeNull();
    expect(container.querySelector(".preview-segment")).toBeNull();

    act(() => root.unmount());
  });

  it("forces independent answers for a single perspective and defaults multiple perspectives to sequential", async () => {
    await setLocale("en");
    const { container, root } = await mountPreview();
    const perspectives = container.querySelector("#preview-perspectives") as HTMLSelectElement;
    const answerMode = container.querySelector("#preview-answer-mode") as HTMLSelectElement;
    const round = container.querySelector("#preview-round") as HTMLSelectElement;
    await act(async () => {
      round.value = "continuation";
      round.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.textContent).toContain("This later-round example includes a synthetic researcher note");
    expect(container.textContent).toContain("In real discussions, the reminder appears only");

    expect(answerMode.disabled).toBe(true);
    expect(answerMode.value).toBe("independent");
    expect(answerMode.textContent).toContain("Independent Answers");
    expect(answerMode.textContent).toContain("Sequential Discussion");

    await act(async () => {
      perspectives.value = "multiple";
      perspectives.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(answerMode.disabled).toBe(false);
    expect(answerMode.value).toBe("sequential");

    await act(async () => {
      perspectives.value = "single";
      perspectives.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(answerMode.value).toBe("independent");
    expect(answerMode.disabled).toBe(true);

    act(() => root.unmount());
  });

  it("does not repeat system-prompt source blocks below the complete messages", async () => {
    await setLocale("en");
    const { container, root } = await mountPreview();
    expect(container.querySelector(".preview-sources")).toBeNull();
    expect(container.querySelectorAll(".preview-source")).toHaveLength(0);

    act(() => root.unmount());
  });

  it("does not represent an unavailable token estimate as zero", async () => {
    await setLocale("en");
    const { container, root } = await mountPreview(null);

    expect(container.textContent).toContain("Token Estimate Unavailable");
    expect(container.textContent).not.toContain("~0 Tokens");

    act(() => root.unmount());
  });

  it("removes stale output during a changed preview request and offers retry after failure", async () => {
    await setLocale("en");
    let previewCalls = 0;
    globalThis.fetch = vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.endsWith("/api/preview/templates")) {
        return jsonResponse([{ id: "rt_skeptiker", label: "The Skeptic" }]);
      }
      if (url.endsWith("/api/discussions/session-types")) {
        return jsonResponse([{ key: "critique", label: "Critique" }]);
      }
      if (url.startsWith("/api/preview/rt_skeptiker?")) {
        previewCalls += 1;
        if (previewCalls === 1) return previewResponse();
        throw new Error("offline");
      }
      throw new Error(`Unexpected request: ${url}`);
    }) as unknown as typeof fetch;

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<PromptPreview />);
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(container.textContent).toContain("System prompt");

    const perspectives = container.querySelector("#preview-perspectives") as HTMLSelectElement;
    await act(async () => {
      perspectives.value = "multiple";
      perspectives.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(container.textContent).not.toContain("System prompt");
    expect(container.querySelector(".preview-error")?.textContent).toContain(
      "Could not connect to the backend.",
    );
    expect(container.querySelector(".preview-error button")?.textContent).toBe("Try Again");
    act(() => root.unmount());
  });
});
