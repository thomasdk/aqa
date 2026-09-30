import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getRoundNotificationSnapshot,
  initializeRoundNotifications,
  requestInitialDesktopNotificationPermission,
  requestRoundNotificationPermission,
  resetRoundNotificationsForTests,
  sendRoundNotification,
  setRoundNotificationsEnabled,
} from "./roundNotifications";

type FakeNotificationConstructor = typeof Notification & {
  created: Array<{ title: string; options?: NotificationOptions }>;
};

function installBrowserNotifications(
  permission: NotificationPermission,
  requested: NotificationPermission = "granted",
): FakeNotificationConstructor {
  let currentPermission = permission;
  class FakeNotification {
    static created: Array<{ title: string; options?: NotificationOptions }> = [];
    static get permission(): NotificationPermission {
      return currentPermission;
    }
    static requestPermission = vi.fn(async () => {
      currentPermission = requested;
      return requested;
    });
    constructor(title: string, options?: NotificationOptions) {
      FakeNotification.created.push({ title, options });
    }
  }
  vi.stubGlobal("Notification", FakeNotification);
  Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
  return FakeNotification as unknown as FakeNotificationConstructor;
}

describe("round notification controller", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.__TAURI__ = undefined;
    resetRoundNotificationsForTests();
  });

  afterEach(() => {
    resetRoundNotificationsForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.__TAURI__ = undefined;
  });

  it("requests once after an eligible native launch and persists before requesting", async () => {
    const order: string[] = [];
    const invoke = vi.fn(async (command: string) => {
      order.push(command);
      return command === "native_notification_permission_state" ? "default" : "default";
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    const persist = vi.fn(async () => {
      order.push("persist");
    });

    await requestInitialDesktopNotificationPermission(false, persist);
    expect(order).toEqual([
      "native_notification_permission_state",
      "persist",
      "request_native_notification_permission",
    ]);
    expect(persist).toHaveBeenCalledOnce();
    expect(getRoundNotificationSnapshot().permission).toBe("default");

    await requestInitialDesktopNotificationPermission(false, persist);
    expect(invoke).toHaveBeenCalledTimes(2);
    resetRoundNotificationsForTests();
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(true, persist);
    expect(invoke).toHaveBeenCalledTimes(3);
    expect(persist).toHaveBeenCalledOnce();
  });

  it.each(["granted", "denied", "unavailable"] as const)(
    "does not automatically request when native permission is %s",
    async (permission) => {
      const invoke = vi.fn(async () => permission);
      window.__TAURI__ = { core: { invoke: invoke as never } };
      await initializeRoundNotifications();
      const persist = vi.fn(async () => undefined);
      await requestInitialDesktopNotificationPermission(false, persist);
      expect(persist).not.toHaveBeenCalled();
      expect(invoke).toHaveBeenCalledOnce();
    },
  );

  it("skips disabled notifications and a failed native status check", async () => {
    setRoundNotificationsEnabled(false);
    const invoke = vi
      .fn()
      .mockResolvedValueOnce("default")
      .mockRejectedValueOnce(new Error("status"));
    window.__TAURI__ = { core: { invoke: invoke as never } };
    const persist = vi.fn(async () => undefined);
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(persist).not.toHaveBeenCalled();
    setRoundNotificationsEnabled(true);
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    expect(persist).not.toHaveBeenCalled();
  });

  it("treats an unexpected native status as unavailable", async () => {
    const invoke = vi.fn().mockResolvedValue("not-a-permission-state");
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    const persist = vi.fn(async () => undefined);
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    expect(persist).not.toHaveBeenCalled();
  });

  it("does not retry after a dismissed or failed native request", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "native_notification_permission_state") return "default";
      throw new Error("permission failed");
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };
    const persist = vi.fn(async () => undefined);
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(false, persist);
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(persist).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    resetRoundNotificationsForTests();
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(true, persist);
    expect(invoke).toHaveBeenCalledTimes(3);
    expect(persist).toHaveBeenCalledOnce();
  });

  it("keeps the manual retry action available after a failed automatic request", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "native_notification_permission_state") return "default";
      if (invoke.mock.calls.filter(([name]) => name === command).length === 1) {
        throw new Error("permission failed");
      }
      return "granted";
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(false, async () => undefined);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    expect(await requestRoundNotificationPermission()).toBe("granted");
    expect(invoke).toHaveBeenCalledTimes(3);
  });

  it("coalesces concurrent initializations before the native request", async () => {
    let release!: (value: void) => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const invoke = vi.fn(async (command: string) =>
      command === "native_notification_permission_state" ? "default" : "granted",
    );
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    const persist = vi.fn(() => pending);
    const first = requestInitialDesktopNotificationPermission(false, persist);
    const second = requestInitialDesktopNotificationPermission(false, persist);
    expect(persist).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledOnce();
    release();
    await Promise.all([first, second]);
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it("does not request if notifications are disabled while the marker is saved", async () => {
    let release!: (value: void) => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const invoke = vi.fn(async (command: string) =>
      command === "native_notification_permission_state" ? "default" : "granted",
    );
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    const attempt = requestInitialDesktopNotificationPermission(false, () => pending);
    setRoundNotificationsEnabled(false);
    release();
    await attempt;
    expect(invoke).toHaveBeenCalledOnce();
  });

  it("requires a stored marker before prompting and leaves browser startup manual", async () => {
    const invoke = vi.fn(async () => "default");
    window.__TAURI__ = { core: { invoke: invoke as never } };
    await initializeRoundNotifications();
    const persist = vi.fn().mockRejectedValue(new Error("save failed"));
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(invoke).toHaveBeenCalledOnce();
    resetRoundNotificationsForTests();
    window.__TAURI__ = undefined;
    const Notification = installBrowserNotifications("default");
    await initializeRoundNotifications();
    await requestInitialDesktopNotificationPermission(false, persist);
    expect(Notification.requestPermission).not.toHaveBeenCalled();
  });

  it("reads native permission at startup and waits for the explicit permission action", async () => {
    installBrowserNotifications("default");
    const invoke = vi.fn(async (command: string) =>
      command === "native_notification_permission_state" ? "default" : "granted",
    );
    window.__TAURI__ = {
      core: { invoke: invoke as never },
    };

    await initializeRoundNotifications();

    expect(invoke).toHaveBeenCalledWith("native_notification_permission_state");
    expect(getRoundNotificationSnapshot()).toMatchObject({
      enabled: true,
      permission: "default",
      permissionRequestAttempted: false,
    });

    expect(await requestRoundNotificationPermission()).toBe("granted");
    expect(invoke).toHaveBeenCalledWith("request_native_notification_permission");
  });

  it("does not re-request native permission at startup after it was denied", async () => {
    installBrowserNotifications("denied");
    const invoke = vi.fn(async () => "denied");
    window.__TAURI__ = {
      core: { invoke: invoke as never },
    };

    await initializeRoundNotifications();

    expect(invoke).toHaveBeenCalledTimes(1);
    expect(invoke).toHaveBeenCalledWith("native_notification_permission_state");
    expect(getRoundNotificationSnapshot()).toMatchObject({
      enabled: true,
      permission: "denied",
      permissionRequestAttempted: false,
    });
    expect(await requestRoundNotificationPermission()).toBe("denied");
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("does not ask on unrelated portable-browser interactions", async () => {
    const Notification = installBrowserNotifications("default");
    await initializeRoundNotifications();

    expect(Notification.requestPermission).not.toHaveBeenCalled();
    document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    document.body.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }));
    expect(Notification.requestPermission).not.toHaveBeenCalled();
  });

  it("does not request permission when the preference is toggled", async () => {
    const Notification = installBrowserNotifications("default");
    await initializeRoundNotifications();

    setRoundNotificationsEnabled(false);
    setRoundNotificationsEnabled(true);

    expect(Notification.requestPermission).not.toHaveBeenCalled();
    expect(getRoundNotificationSnapshot().enabled).toBe(true);
  });

  it("reports denied and unsupported permission states without throwing", async () => {
    const Notification = installBrowserNotifications("default", "denied");
    await initializeRoundNotifications();
    expect(await requestRoundNotificationPermission()).toBe("denied");
    expect(await requestRoundNotificationPermission()).toBe("denied");
    expect(Notification.requestPermission).toHaveBeenCalledTimes(1);

    resetRoundNotificationsForTests();
    vi.stubGlobal("Notification", undefined);
    expect(await requestRoundNotificationPermission()).toBe("unsupported");
  });

  it("retains an undecided state when the browser prompt is dismissed", async () => {
    installBrowserNotifications("default", "default");
    await initializeRoundNotifications();

    expect(await requestRoundNotificationPermission()).toBe("default");
    expect(getRoundNotificationSnapshot()).toMatchObject({
      enabled: true,
      permission: "default",
      permissionRequestAttempted: true,
    });
  });

  it("preserves an unavailable native permission response", async () => {
    installBrowserNotifications("default");
    window.__TAURI__ = {
      core: { invoke: vi.fn().mockResolvedValue("unavailable") as never },
    };

    await initializeRoundNotifications();

    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    expect(await requestRoundNotificationPermission()).toBe("unavailable");
  });

  it("distinguishes unsupported environments from permission API failures", async () => {
    vi.stubGlobal("Notification", undefined);
    expect(await requestRoundNotificationPermission()).toBe("unsupported");

    resetRoundNotificationsForTests();
    const Notification = installBrowserNotifications("default");
    Notification.requestPermission = vi.fn().mockRejectedValue(new Error("permission API failed"));
    expect(await requestRoundNotificationPermission()).toBe("unavailable");
    expect(getRoundNotificationSnapshot()).toMatchObject({
      permission: "unavailable",
      permissionRequestAttempted: true,
    });

    resetRoundNotificationsForTests();
    window.__TAURI__ = {
      core: { invoke: vi.fn().mockRejectedValue(new Error("native plugin unavailable")) as never },
    };
    await initializeRoundNotifications();
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
    expect(await requestRoundNotificationPermission()).toBe("unavailable");
  });

  it("refreshes native permission after it is revoked and restored externally", async () => {
    const Notification = installBrowserNotifications("granted");
    let permission = "granted";
    const invoke = vi.fn(async (command: string) => {
      if (command === "native_notification_permission_state") return permission;
      if (command === "deliver_round_notification") {
        return { status: "queued", focused: false, minimized: true, visible: true };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = {
      core: {
        invoke: invoke as never,
      },
    };
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    await initializeRoundNotifications();

    permission = "denied";
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round failed." })).toBe(
      false,
    );
    expect(getRoundNotificationSnapshot().permission).toBe("denied");

    permission = "granted";
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      true,
    );
    expect(getRoundNotificationSnapshot().permission).toBe("granted");
    expect(Notification.created).toHaveLength(0);
    expect(invoke).toHaveBeenCalledWith("deliver_round_notification", {
      title: "AQA",
      body: "Discussion round finished.",
    });
  });

  it("uses native window state for foreground suppression and minimized delivery", async () => {
    installBrowserNotifications("granted");
    let result = { status: "suppressed", focused: true, minimized: false, visible: true };
    const invoke = vi.fn(async (command: string) => {
      if (command === "native_notification_permission_state") return "granted";
      if (command === "deliver_round_notification") return result;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke: invoke as never } };
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await initializeRoundNotifications();

    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      false,
    );
    result = { status: "queued", focused: false, minimized: true, visible: true };
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      true,
    );
    expect(invoke).toHaveBeenCalledTimes(5);
  });

  it("delivers generic content only while the page is in the background", async () => {
    const Notification = installBrowserNotifications("granted");
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await initializeRoundNotifications();

    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      false,
    );
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      true,
    );
    expect(Notification.created).toEqual([
      {
        title: "AQA",
        options: { body: "Discussion round finished." },
      },
    ]);
  });

  it("suppresses disabled and unsupported delivery but allows an unfocused visible page", async () => {
    const Notification = installBrowserNotifications("granted");
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await initializeRoundNotifications();
    setRoundNotificationsEnabled(false);
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      false,
    );

    setRoundNotificationsEnabled(true);
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      true,
    );
    expect(Notification.created).toHaveLength(1);

    resetRoundNotificationsForTests();
    vi.stubGlobal("Notification", undefined);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: false });
    expect(await sendRoundNotification({ title: "AQA", body: "Discussion round finished." })).toBe(
      false,
    );
  });

  it("keeps native delivery failures non-fatal", async () => {
    installBrowserNotifications("granted");
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "native_notification_permission_state") return "granted";
          throw new Error("OS rejected notification");
        }) as never,
      },
    };
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    await initializeRoundNotifications();

    await expect(
      sendRoundNotification({ title: "AQA", body: "Discussion round failed." }),
    ).resolves.toBe(false);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
  });

  it("keeps browser delivery failures non-fatal", async () => {
    class FailingNotification {
      static permission: NotificationPermission = "granted";
      static requestPermission = vi.fn().mockResolvedValue("granted");
      constructor() {
        throw new Error("Browser rejected notification");
      }
    }
    vi.stubGlobal("Notification", FailingNotification);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    await initializeRoundNotifications();

    await expect(
      sendRoundNotification({ title: "AQA", body: "Discussion round failed." }),
    ).resolves.toBe(false);
    expect(getRoundNotificationSnapshot().permission).toBe("unavailable");
  });
});
