import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  useDiscussionMaterialPresentation,
  type DiscussionContextEstimateDraft,
} from "./useDiscussionMaterialPresentation";

const draft: DiscussionContextEstimateDraft = {
  agents: [
    {
      name: "Perspective 1",
      client_id: "client-1",
      prompt_id: "role-1",
      color: "#000000",
      temperature: null,
      llm_id: "model-1",
      api_host: "https://configured.example/v1",
      api_key: "secret-must-not-leave-the-ui",
      max_tokens: null,
      enabled: true,
      perspective_number: 1,
    },
  ],
  synthesis: { enabled: false, api_host: null, llm_id: null, temperature: null },
  sessionType: "exploration",
  targetLanguage: "English",
  sessionInputValues: {
    research_material_context: "",
    main_input: "Question",
    additional_instructions: "",
  },
  sequentialMode: false,
};

function Harness({
  material,
  revision = "",
  selection = draft,
}: {
  material: string;
  revision?: string;
  selection?: DiscussionContextEstimateDraft;
}) {
  const { contextEstimate } = useDiscussionMaterialPresentation(
    material,
    "document",
    false,
    selection,
    revision,
  );
  return <output>{contextEstimate?.overflow ? "overflow" : "not-blocked"}</output>;
}

function render(material: string): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Harness material={material} />));
  return { container, root };
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.useFakeTimers();
});

it("discards stale host and model estimates after a selection change", async () => {
  let resolveOld: ((response: Response) => void) | undefined;
  const requests: Array<{ agents: Array<{ api_host: string; llm_id: string }> }> = [];
  const result = (overflow: boolean) =>
    ({
      ok: true,
      text: () => Promise.resolve(""),
      json: () =>
        Promise.resolve({
          known: true,
          overflow,
          estimated_input_tokens: overflow ? 21_029 : 500,
          available_input_tokens: 8_192,
          context_window_tokens: 12_288,
          reserved_output_tokens: 4_096,
        }),
    }) as Response;
  globalThis.fetch = vi.fn((input: unknown, init?: RequestInit) => {
    if (String(input).endsWith("/api/material/token-estimate")) {
      return Promise.resolve(result(false));
    }
    requests.push(JSON.parse(String(init?.body)));
    if (requests.length === 1) {
      return new Promise<Response>((resolve) => {
        resolveOld = resolve;
      });
    }
    return Promise.resolve(result(false));
  }) as typeof fetch;

  const { container, root } = render("Synthetic material");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  const nextSelection = {
    ...draft,
    agents: [
      {
        ...draft.agents[0],
        api_host: "https://new.example/v1",
        llm_id: "new-model",
      },
    ],
  };
  act(() => root.render(<Harness material="Synthetic material" selection={nextSelection} />));
  expect(container.textContent).toBe("not-blocked");
  await act(async () => {
    resolveOld?.(result(true));
    await vi.advanceTimersByTimeAsync(300);
  });
  expect(requests.map((request) => request.agents[0])).toMatchObject([
    { api_host: "https://configured.example/v1", llm_id: "model-1" },
    { api_host: "https://new.example/v1", llm_id: "new-model" },
  ]);
  expect(container.textContent).toBe("not-blocked");
  act(() => root.unmount());
});

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = originalFetch;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

it("does not expose an old overflow result after the material fingerprint changes", async () => {
  let contextRequestCount = 0;
  const contextRequestBodies: unknown[] = [];
  globalThis.fetch = vi.fn((input: unknown, init?: RequestInit) => {
    if (String(input).endsWith("/api/material/token-estimate")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(""),
        json: () => Promise.resolve({ approximate_tokens: 1, tokenizer: "test" }),
      } as unknown as Response);
    }
    if (String(input).endsWith("/api/discussions/context-estimate")) {
      contextRequestCount += 1;
      contextRequestBodies.push(JSON.parse(String(init?.body)));
      if (contextRequestCount === 1) {
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () => Promise.resolve(""),
          json: () =>
            Promise.resolve({
              known: true,
              estimated_input_tokens: 999,
              available_input_tokens: 1,
              context_window_tokens: 4097,
              reserved_output_tokens: 4096,
              overflow: true,
            }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(""),
        json: () =>
          Promise.resolve({
            known: true,
            estimated_input_tokens: 200,
            available_input_tokens: 4096,
            context_window_tokens: 8192,
            reserved_output_tokens: 4096,
            overflow: false,
          }),
      } as unknown as Response);
    }
    return Promise.reject(new Error(`Unexpected request: ${String(input)}`));
  }) as unknown as typeof fetch;

  const { container, root } = render("old material");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  expect(contextRequestCount).toBe(1);
  expect(contextRequestBodies[0]).toMatchObject({ agents: [{ api_key: null }] });
  expect(JSON.stringify(contextRequestBodies)).not.toContain("secret-must-not-leave-the-ui");
  expect(container.textContent).toBe("overflow");

  act(() => root.render(<Harness material="new material" />));
  expect(container.textContent).toBe("not-blocked");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  expect(contextRequestCount).toBe(2);
  expect(container.textContent).toBe("not-blocked");
  act(() => root.unmount());
});
it("invalidates an offline estimate when the running context revision changes", async () => {
  globalThis.fetch = vi.fn((input: unknown) => {
    if (String(input).endsWith("/api/material/token-estimate")) {
      return Promise.resolve({
        ok: true,
        text: () => Promise.resolve(""),
        json: () => Promise.resolve({ approximate_tokens: 1 }),
      } as Response);
    }
    return Promise.resolve({
      ok: true,
      text: () => Promise.resolve(""),
      json: () =>
        Promise.resolve({
          known: true,
          overflow: false,
          estimated_input_tokens: 100,
          available_input_tokens: 4096,
          context_window_tokens: 8192,
          reserved_output_tokens: 4096,
        }),
    } as Response);
  }) as typeof fetch;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  function RevisionHarness({ revision }: { revision: string }) {
    const { contextEstimate } = useDiscussionMaterialPresentation(
      "same material",
      "document",
      false,
      draft,
      revision,
    );
    return <output>{contextEstimate?.known ? "ready" : "refreshing"}</output>;
  }
  act(() => root.render(<RevisionHarness revision="8192" />));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  expect(container.textContent).toBe("ready");
  act(() => root.render(<RevisionHarness revision="16384" />));
  expect(container.textContent).toBe("refreshing");
  act(() => root.unmount());
});
