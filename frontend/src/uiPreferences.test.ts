import {
  getAppearance,
  initializeAppearance,
  APPEARANCE_STORAGE_KEY,
  waitForNativeAppearance,
} from "./appearance";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AI_SOURCE_STORAGE_KEY } from "./components/aiSourceSelection";
import { LAST_ACTIVE_DISCUSSION_STORAGE_KEY } from "./components/lastActiveDiscussion";
import i18n, { LOCALE_STORAGE_KEY, setLocale } from "./i18n";
import {
  ROUND_NOTIFICATIONS_STORAGE_KEY,
  resetRoundNotificationsForTests,
} from "./roundNotifications";
import {
  getGenerationSleepInhibitionSnapshot,
  resetGenerationSleepInhibitionForTests,
} from "./generationSleepInhibition";
import {
  hydrateApplicationPreferences,
  selectPersistedAISource,
  selectPersistedAppearance,
  selectPersistedLocale,
  selectPersistedPreventSleepWhileGenerating,
  selectPersistedRoundNotifications,
} from "./uiPreferences";

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(payload),
    json: async () => payload,
  } as Response;
}

function deferredResponse(): { promise: Promise<Response>; resolve: (value: Response) => void } {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe("application preference hydration", () => {
  beforeEach(async () => {
    window.localStorage.clear();
    resetRoundNotificationsForTests();
    resetGenerationSleepInhibitionForTests();
    await setLocale("en");
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    window.localStorage.removeItem(AI_SOURCE_STORAGE_KEY);
    window.localStorage.removeItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY);
    window.localStorage.removeItem(ROUND_NOTIFICATIONS_STORAGE_KEY);
    resetRoundNotificationsForTests();
    resetGenerationSleepInhibitionForTests();
    await setLocale("de");
  });

  it("replaces stale cached appearance with server preference", async () => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");
    const dispose = initializeAppearance();
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        response({ ui_locale: "en", ai_source: "integrated", appearance: "light" }),
      );
    expect(await hydrateApplicationPreferences()).toBe(false);
    expect(getAppearance()).toBe("light");
    expect(window.localStorage.getItem(APPEARANCE_STORAGE_KEY)).toBe("light");
    await waitForNativeAppearance();
    dispose();
  });

  it("keeps cached appearance through persistence failures and accepts later writes", async () => {
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, "dark");
    const dispose = initializeAppearance();
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    globalThis.fetch = fetchMock;
    await hydrateApplicationPreferences();
    expect(getAppearance()).toBe("dark");
    await expect(selectPersistedAppearance("light")).resolves.toBeUndefined();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(APPEARANCE_STORAGE_KEY)).toBe("light");
    fetchMock.mockResolvedValue(response({ appearance: "dark" }));
    await selectPersistedAppearance("dark");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/application/preferences",
      expect.objectContaining({
        body: JSON.stringify({ appearance: "dark" }),
      }),
    );
    await waitForNativeAppearance();
    dispose();
  });

  it("serializes rapid appearance writes and retains the latest immediate choice", async () => {
    const first = deferredResponse();
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(response({ appearance: "light" }));
    globalThis.fetch = fetchMock;
    const darkWrite = selectPersistedAppearance("dark");
    const lightWrite = selectPersistedAppearance("light");
    expect(getAppearance()).toBe("light");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    first.resolve(response({ appearance: "dark" }));
    await Promise.all([darkWrite, lightWrite]);
    expect(fetchMock.mock.calls.map((call) => JSON.parse(call[1].body))).toEqual([
      { appearance: "dark" },
      { appearance: "light" },
    ]);
    expect(getAppearance()).toBe("light");
  });

  it("does not let delayed hydration reverse a user selection", async () => {
    const first = deferredResponse();
    globalThis.fetch = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(response({ appearance: "dark" }));
    const hydration = hydrateApplicationPreferences();
    await selectPersistedAppearance("dark");
    first.resolve(response({ ui_locale: "en", ai_source: "integrated", appearance: "light" }));
    await hydration;
    expect(getAppearance()).toBe("dark");
  });

  it("restores server preferences for a new loopback origin", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      response({
        ui_locale: "de",
        ai_source: "external",
        notifications_enabled: false,
        prevent_sleep_while_generating: false,
        last_active_discussion_id: "session-123",
      }),
    );

    await hydrateApplicationPreferences();

    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("de");
    expect(window.localStorage.getItem(AI_SOURCE_STORAGE_KEY)).toBe("external");
    expect(window.localStorage.getItem(ROUND_NOTIFICATIONS_STORAGE_KEY)).toBe("false");
    expect(window.localStorage.getItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY)).toBe("session-123");
    expect(getGenerationSleepInhibitionSnapshot().enabled).toBe(false);
    expect(i18n.resolvedLanguage).toBe("de");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("returns the persisted automatic permission marker", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      response({
        ui_locale: "en",
        ai_source: "integrated",
        notifications_enabled: true,
        notification_permission_auto_attempted: true,
        last_active_discussion_id: null,
      }),
    );
    expect(await hydrateApplicationPreferences()).toBe(true);
  });

  it("keeps existing browser-local preferences and backfills the server", async () => {
    await setLocale("en");
    window.localStorage.setItem(AI_SOURCE_STORAGE_KEY, "integrated");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          ui_locale: "de",
          ai_source: "external",
          notifications_enabled: true,
          last_active_discussion_id: null,
        }),
      )
      .mockResolvedValueOnce(
        response({
          ui_locale: "en",
          ai_source: "integrated",
          notifications_enabled: true,
          last_active_discussion_id: null,
        }),
      );
    globalThis.fetch = fetchMock;

    await hydrateApplicationPreferences();

    expect(i18n.resolvedLanguage).toBe("en");
    expect(window.localStorage.getItem(AI_SOURCE_STORAGE_KEY)).toBe("integrated");
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toEqual({
      ui_locale: "en",
      ai_source: "integrated",
    });
  });

  it("replaces a stale browser pointer with the server-owned discussion pointer", async () => {
    window.localStorage.setItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY, "stale-session");
    globalThis.fetch = vi.fn().mockResolvedValue(
      response({
        ui_locale: "en",
        ai_source: "integrated",
        notifications_enabled: true,
        last_active_discussion_id: "current-session",
      }),
    );

    await hydrateApplicationPreferences();

    expect(window.localStorage.getItem(LAST_ACTIVE_DISCUSSION_STORAGE_KEY)).toBe("current-session");
  });

  it("persists later locale and AI-source selections to both stores", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        ui_locale: "de",
        ai_source: "external",
        notifications_enabled: false,
        last_active_discussion_id: null,
      }),
    );
    globalThis.fetch = fetchMock;

    await selectPersistedLocale("de");
    selectPersistedAISource("external");
    selectPersistedRoundNotifications(false);
    selectPersistedPreventSleepWhileGenerating(false);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("de");
    expect(window.localStorage.getItem(AI_SOURCE_STORAGE_KEY)).toBe("external");
    expect(window.localStorage.getItem(ROUND_NOTIFICATIONS_STORAGE_KEY)).toBe("false");
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({ ui_locale: "de" });
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toEqual({
      ai_source: "external",
    });
    expect(JSON.parse(fetchMock.mock.calls[2]?.[1]?.body as string)).toEqual({
      notifications_enabled: false,
    });
    expect(JSON.parse(fetchMock.mock.calls[3]?.[1]?.body as string)).toEqual({
      prevent_sleep_while_generating: false,
    });
  });

  it("persists notification opt-in without requesting permission", async () => {
    const requestPermission = vi.fn().mockResolvedValue("granted");
    class FakeNotification {
      static permission: NotificationPermission = "default";
      static requestPermission = requestPermission;
    }
    vi.stubGlobal("Notification", FakeNotification);
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        ui_locale: "en",
        ai_source: "integrated",
        notifications_enabled: true,
        last_active_discussion_id: null,
      }),
    );
    globalThis.fetch = fetchMock;

    selectPersistedRoundNotifications(true);
    await Promise.resolve();

    expect(window.localStorage.getItem(ROUND_NOTIFICATIONS_STORAGE_KEY)).toBe("true");
    expect(requestPermission).not.toHaveBeenCalled();
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      notifications_enabled: true,
    });
  });

  it("serializes rapid sleep-preference writes so the last visible choice wins", async () => {
    const first = deferredResponse();
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(response({ prevent_sleep_while_generating: true }));
    globalThis.fetch = fetchMock;

    selectPersistedPreventSleepWhileGenerating(false);
    selectPersistedPreventSleepWhileGenerating(true);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(getGenerationSleepInhibitionSnapshot().enabled).toBe(true);

    first.resolve(response({ prevent_sleep_while_generating: false }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      prevent_sleep_while_generating: false,
    });
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toEqual({
      prevent_sleep_while_generating: true,
    });
  });
});
