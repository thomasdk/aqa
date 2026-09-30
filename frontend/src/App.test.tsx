import { act } from "react";
import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { resetRoundNotificationsForTests } from "./roundNotifications";

vi.mock("./components/Layout", () => ({ default: () => <main>AQA ready</main> }));

afterEach(() => {
  window.__TAURI__ = undefined;
  window.localStorage.clear();
  resetRoundNotificationsForTests();
  vi.unstubAllGlobals();
});

it("requests native permission once when Strict Mode mounts the ready app twice", async () => {
  const invoke = vi.fn(async (command: string) =>
    command === "native_notification_permission_state" ? "default" : "default",
  );
  window.__TAURI__ = { core: { invoke: invoke as never } };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal("fetch", fetchMock);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);

  await act(async () => {
    root.render(
      <StrictMode>
        <App notificationPermissionAutoAttempted={false} />
      </StrictMode>,
    );
  });
  await vi.waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("request_native_notification_permission"),
  );
  expect(
    invoke.mock.calls.filter(([command]) => command === "native_notification_permission_state"),
  ).toHaveLength(1);
  expect(
    invoke.mock.calls.filter(([command]) => command === "request_native_notification_permission"),
  ).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    notification_permission_auto_attempted: true,
  });

  await act(async () => root.unmount());
  host.remove();
});
