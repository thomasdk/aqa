import {
  getAppearanceRevision,
  hydrateAppearance,
  selectAppearance,
  type Appearance,
} from "./appearance";
import { getApplicationPreferences, updateApplicationPreferences } from "./api";
import { persistLastActiveDiscussionId } from "./components/lastActiveDiscussion";
import {
  persistPreferredAISource,
  readStoredPreferredAISource,
  type AISource,
} from "./components/aiSourceSelection";
import { readStoredLocale, setLocale, type AppLocale } from "./i18n";
import {
  readStoredRoundNotificationsEnabled,
  setRoundNotificationsEnabled,
} from "./roundNotifications";
import { setPreventSleepWhileGenerating } from "./generationSleepInhibition";

type PreferenceUpdate = {
  ui_locale?: AppLocale;
  ai_source?: AISource;
  notifications_enabled?: boolean;
  prevent_sleep_while_generating?: boolean;
};

let appearancePreferenceWrite: Promise<void> = Promise.resolve();

let preventSleepPreferenceWrite: Promise<void> = Promise.resolve();

/**
 * Restore server-backed preferences when this loopback origin is new. Existing
 * browser-local values remain authoritative and are backfilled to the server,
 * except appearance: the server owns it and its local cache only paints startup.
 */
export async function hydrateApplicationPreferences(): Promise<boolean | null> {
  const appearanceRevision = getAppearanceRevision();
  let persisted: Awaited<ReturnType<typeof getApplicationPreferences>>;
  try {
    persisted = await getApplicationPreferences();
  } catch {
    return null;
  }

  hydrateAppearance(persisted.appearance, appearanceRevision);

  const update: PreferenceUpdate = {};
  const storedLocale = readStoredLocale();
  if (storedLocale === null) await setLocale(persisted.ui_locale);
  else if (storedLocale !== persisted.ui_locale) update.ui_locale = storedLocale;

  const storedSource = readStoredPreferredAISource();
  if (storedSource === null) persistPreferredAISource(persisted.ai_source);
  else if (storedSource !== persisted.ai_source) update.ai_source = storedSource;

  const persistedNotifications = persisted.notifications_enabled !== false;
  const storedNotifications = readStoredRoundNotificationsEnabled();
  if (storedNotifications === null) setRoundNotificationsEnabled(persistedNotifications);
  else {
    setRoundNotificationsEnabled(storedNotifications);
    if (storedNotifications !== persistedNotifications) {
      update.notifications_enabled = storedNotifications;
    }
  }

  setPreventSleepWhileGenerating(persisted.prevent_sleep_while_generating !== false);

  const persistedLastDiscussion = persisted.last_active_discussion_id ?? null;
  if (persistedLastDiscussion !== null) {
    persistLastActiveDiscussionId(persistedLastDiscussion);
  }

  if (Object.keys(update).length > 0) {
    try {
      await updateApplicationPreferences(update);
    } catch {
      // Browser-local preferences remain usable if persistence is unavailable.
    }
  }
  return persisted.notification_permission_auto_attempted === true;
}

export async function persistNotificationPermissionAutoAttempt(): Promise<void> {
  await updateApplicationPreferences({ notification_permission_auto_attempted: true });
}

export async function selectPersistedLocale(locale: AppLocale): Promise<void> {
  await setLocale(locale);
  try {
    await updateApplicationPreferences({ ui_locale: locale });
  } catch {
    // The visible language change remains valid when persistence is unavailable.
  }
}

export function selectPersistedAISource(source: AISource): void {
  persistPreferredAISource(source);
  void updateApplicationPreferences({ ai_source: source }).catch(() => undefined);
}

export function selectPersistedRoundNotifications(enabled: boolean): void {
  setRoundNotificationsEnabled(enabled);
  void updateApplicationPreferences({ notifications_enabled: enabled }).catch(() => undefined);
}

export function selectPersistedPreventSleepWhileGenerating(enabled: boolean): void {
  setPreventSleepWhileGenerating(enabled);
  preventSleepPreferenceWrite = preventSleepPreferenceWrite
    .catch(() => undefined)
    .then(() => updateApplicationPreferences({ prevent_sleep_while_generating: enabled }))
    .then(() => undefined)
    .catch(() => undefined);
}

/** Serialize server writes while applying each selection immediately. */
export function selectPersistedAppearance(appearance: Appearance): Promise<void> {
  selectAppearance(appearance);
  appearancePreferenceWrite = appearancePreferenceWrite
    .catch(() => undefined)
    .then(() => updateApplicationPreferences({ appearance }))
    .then(() => undefined)
    .catch(() => undefined);
  return appearancePreferenceWrite;
}
