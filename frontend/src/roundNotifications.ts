export const ROUND_NOTIFICATIONS_STORAGE_KEY = "aqa.roundNotifications.v1";

export type RoundNotificationOutcome = "completed" | "failed" | "interrupted";
export type RoundNotificationPermission =
  "unknown" | "default" | "granted" | "denied" | "unsupported" | "unavailable";

export type RoundNotificationSnapshot = {
  enabled: boolean;
  permission: RoundNotificationPermission;
  permissionRequestAttempted: boolean;
};

type NotificationCopy = {
  title: string;
  body: string;
};

type NativeRoundNotificationResult = {
  status: "queued" | "suppressed";
  focused: boolean;
  minimized: boolean;
  visible: boolean;
};

let snapshot: RoundNotificationSnapshot = {
  enabled: true,
  permission: "unknown",
  permissionRequestAttempted: false,
};
let automaticPermissionAttempt: Promise<void> | null = null;
let permissionRequest: Promise<RoundNotificationPermission> | null = null;
let notificationInitialization: Promise<void> | null = null;
const subscribers = new Set<() => void>();

const publish = (update: Partial<RoundNotificationSnapshot>) => {
  const next = { ...snapshot, ...update };
  if (
    next.enabled === snapshot.enabled &&
    next.permission === snapshot.permission &&
    next.permissionRequestAttempted === snapshot.permissionRequestAttempted
  ) {
    return;
  }
  snapshot = next;
  subscribers.forEach((subscriber) => subscriber());
};

const nativeInvoke = () => window.__TAURI__?.core?.invoke;

const browserNotificationsSupported = () =>
  window.isSecureContext === true &&
  typeof window.Notification === "function" &&
  typeof window.Notification.requestPermission === "function";

const normalizePermission = (permission: string): RoundNotificationPermission => {
  if (
    permission === "default" ||
    permission === "granted" ||
    permission === "denied" ||
    permission === "unavailable"
  ) {
    return permission;
  }
  return "unavailable";
};

async function readPermission(): Promise<RoundNotificationPermission> {
  const invoke = nativeInvoke();
  if (invoke) {
    try {
      const permission = await invoke<string>("native_notification_permission_state");
      return normalizePermission(permission);
    } catch {
      return "unavailable";
    }
  }
  if (!browserNotificationsSupported()) return "unsupported";
  try {
    return normalizePermission(window.Notification.permission);
  } catch {
    return "unavailable";
  }
}

export async function requestRoundNotificationPermission(): Promise<RoundNotificationPermission> {
  if (permissionRequest) return permissionRequest;
  if (snapshot.permission === "granted" || snapshot.permission === "denied") {
    return snapshot.permission;
  }
  permissionRequest = (async () => {
    publish({ permissionRequestAttempted: true });
    const invoke = nativeInvoke();
    if (!invoke && !browserNotificationsSupported()) {
      publish({ permission: "unsupported" });
      return "unsupported";
    }
    try {
      const permission = invoke
        ? await invoke<string>("request_native_notification_permission")
        : await window.Notification.requestPermission();
      const normalizedPermission = normalizePermission(permission);
      publish({ permission: normalizedPermission });
      return normalizedPermission;
    } catch {
      publish({ permission: "unavailable" });
      return "unavailable";
    }
  })();
  try {
    return await permissionRequest;
  } finally {
    permissionRequest = null;
  }
}

export function readStoredRoundNotificationsEnabled(): boolean | null {
  try {
    const stored = window.localStorage.getItem(ROUND_NOTIFICATIONS_STORAGE_KEY);
    if (stored === "true") return true;
    if (stored === "false") return false;
  } catch {
    // The server-backed preference remains available when local storage is blocked.
  }
  return null;
}

export function setRoundNotificationsEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(ROUND_NOTIFICATIONS_STORAGE_KEY, String(enabled));
  } catch {
    // Notification behavior remains usable for the current page session.
  }
  publish({ enabled });
}

export function initializeRoundNotifications(): Promise<void> {
  if (notificationInitialization) return notificationInitialization;
  notificationInitialization = (async () => {
    const stored = readStoredRoundNotificationsEnabled();
    if (stored !== null) publish({ enabled: stored });
    const permission = await readPermission();
    publish({ permission });
  })();
  void notificationInitialization.finally(() => {
    notificationInitialization = null;
  });
  return notificationInitialization;
}

export function requestInitialDesktopNotificationPermission(
  alreadyAttempted: boolean | null,
  persistAttempt: () => Promise<void>,
): Promise<void> {
  if (
    automaticPermissionAttempt ||
    alreadyAttempted !== false ||
    !nativeInvoke() ||
    !snapshot.enabled ||
    snapshot.permission !== "default"
  ) {
    return automaticPermissionAttempt ?? Promise.resolve();
  }
  automaticPermissionAttempt = (async () => {
    try {
      // Persist before invoking the OS so a dismissal or app exit cannot prompt again.
      await persistAttempt();
      if (
        snapshot.enabled &&
        snapshot.permission === "default" &&
        !snapshot.permissionRequestAttempted
      ) {
        await requestRoundNotificationPermission();
      }
    } catch {
      // A failed marker write must not create an untracked automatic request.
    }
  })();
  return automaticPermissionAttempt;
}

export async function sendRoundNotification(copy: NotificationCopy): Promise<boolean> {
  if (!snapshot.enabled) return false;
  const invoke = nativeInvoke();
  if (!invoke && document.visibilityState === "visible" && document.hasFocus()) return false;
  const permission = await readPermission();
  publish({ permission });
  if (permission !== "granted") return false;
  try {
    if (invoke) {
      const result = await invoke<NativeRoundNotificationResult>("deliver_round_notification", {
        title: copy.title,
        body: copy.body,
      });
      return result.status === "queued";
    } else {
      new window.Notification(copy.title, { body: copy.body });
    }
    return true;
  } catch {
    publish({ permission: "unavailable" });
    return false;
  }
}

export function subscribeRoundNotifications(subscriber: () => void): () => void {
  subscribers.add(subscriber);
  return () => subscribers.delete(subscriber);
}

export function getRoundNotificationSnapshot(): RoundNotificationSnapshot {
  return snapshot;
}

export function resetRoundNotificationsForTests(): void {
  automaticPermissionAttempt = null;
  permissionRequest = null;
  notificationInitialization = null;
  snapshot = {
    enabled: true,
    permission: "unknown",
    permissionRequestAttempted: false,
  };
  subscribers.clear();
}
