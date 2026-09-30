import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LocalAIStatus } from "../types";
import { useLocalAIStatus } from "./useLocalAIStatus";

const statusFixture = (state: LocalAIStatus["state"]): LocalAIStatus =>
  ({ state }) as LocalAIStatus;

const statusResponse = (status: LocalAIStatus): Response =>
  ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(status),
    json: async () => status,
  }) as Response;

function Harness({ view }: { view: string }) {
  const { failed, status } = useLocalAIStatus(view);
  return <output>{failed ? "failed" : (status?.state ?? "loading")}</output>;
}

function mount(view = "setup"): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Harness view={view} />));
  return { container, root };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("useLocalAIStatus", () => {
  it("keeps polling through repeated same-state responses until the lifecycle changes", async () => {
    const states: LocalAIStatus["state"][] = ["starting", "starting", "starting", "running"];
    const fetchMock = vi.fn(async () => {
      const status = statusFixture(states.shift() ?? "running");
      return statusResponse(status);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = mount();

    await act(async () => Promise.resolve());
    expect(container.textContent).toBe("starting");
    for (let poll = 0; poll < 3; poll += 1) {
      await act(async () => vi.advanceTimersByTimeAsync(500));
    }

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(container.textContent).toBe("running");
  });

  it("retries a transient status failure and recovers polling", async () => {
    let request = 0;
    const fetchMock = vi.fn(async () => {
      request += 1;
      if (request === 2) {
        return { ok: false, status: 503, text: async () => "temporarily unavailable" } as Response;
      }
      const status = statusFixture(request >= 4 ? "running" : "starting");
      return statusResponse(status);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = mount();

    await act(async () => Promise.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(container.textContent).toBe("failed");
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    await act(async () => vi.advanceTimersByTimeAsync(500));

    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(4);
    expect(container.textContent).toBe("running");
  });

  it("ignores an in-flight response after navigation enters the Local AI view", async () => {
    let resolveStatus!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveStatus = resolve;
          }),
      ),
    );
    const { container, root } = mount();

    act(() => root.render(<Harness view="local-ai" />));
    await act(async () => {
      const status = statusFixture("running");
      resolveStatus(statusResponse(status));
      await Promise.resolve();
    });

    expect(container.textContent).toBe("loading");
  });
});
