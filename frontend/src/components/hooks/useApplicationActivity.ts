import { useCallback, useEffect, useRef, useState } from "react";
import i18n from "../../i18n";
import { getApplicationActivity, type ApplicationActivityEvent } from "../../api";

export type ActivityEntry = {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  source: "discussion" | "server";
  message: string;
};

function formatServerActivity(event: ApplicationActivityEvent): string {
  const value = (name: string): string | number | boolean | undefined => event.params[name];
  const method = value("method") ?? "API";
  const route = value("route") ?? "request";
  const status = value("status");
  switch (event.code) {
    case "server_started":
      return i18n.t("activity.serverStarted");
    case "server_stopped":
      return i18n.t("activity.serverStopped");
    case "request_completed":
    case "http_rejection":
      return i18n.t("activity.serverRequest", { method, route, status });
    case "unexpected_failure":
      return i18n.t("activity.serverRequestFailed", { method, route });
    default:
      return i18n.t("activity.serverEvent", { code: event.code });
  }
}

function shouldDisplayServerActivity(event: ApplicationActivityEvent): boolean {
  return !(
    event.code === "request_completed" &&
    event.level === "info" &&
    event.params.method === "GET"
  );
}

export function useApplicationActivity() {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const cursorRef = useRef(0);
  const clearEpochRef = useRef(0);
  const entrySequenceRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  const add = useCallback(
    (entry: Omit<ActivityEntry, "id" | "timestamp"> & { timestamp?: string }) => {
      setEntries((previous) => {
        if (
          entry.source === "server" &&
          entry.level === "info" &&
          previous.some(
            (existing) =>
              existing.source === entry.source &&
              existing.level === entry.level &&
              existing.message === entry.message,
          )
        ) {
          return previous;
        }
        entrySequenceRef.current += 1;
        return [
          ...previous,
          {
            ...entry,
            id: `${entry.source}-${entrySequenceRef.current}`,
            timestamp: entry.timestamp ?? new Date().toISOString(),
          },
        ].slice(-500);
      });
    },
    [],
  );

  const addDiscussionActivity = useCallback(
    (message: string, level: ActivityEntry["level"] = "info") => {
      add({ source: "discussion", level, message });
    },
    [add],
  );

  const clear = useCallback(() => {
    clearEpochRef.current += 1;
    setEntries([]);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled || pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      const clearEpoch = clearEpochRef.current;
      try {
        const result = await getApplicationActivity(cursorRef.current);
        if (cancelled) return;
        cursorRef.current = result.next_cursor;
        if (clearEpoch !== clearEpochRef.current) return;
        result.events.forEach((event) => {
          if (!shouldDisplayServerActivity(event)) return;
          add({
            source: "server",
            level: event.level,
            message: formatServerActivity(event),
            timestamp: event.timestamp,
          });
        });
      } catch {
        // Activity polling must never add a repeating diagnostic entry.
      } finally {
        pollInFlightRef.current = false;
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [add]);

  useEffect(() => {
    if (!isOpen || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [entries.length, isOpen]);

  return { addDiscussionActivity, clear, entries, isOpen, logRef, setIsOpen };
}
