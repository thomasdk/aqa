import { useCallback, useEffect, useRef, useState } from "react";
import { getLocalAIStatus } from "../../api";
import { nextPollDelay } from "../localAIState";
import type { LocalAIStatus } from "../types";

const STATUS_RETRY_DELAY_MS = 2_000;

export function useLocalAIStatus(view: string) {
  const [status, setStatus] = useState<LocalAIStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const requestRef = useRef(0);

  const acceptStatus = useCallback((next: LocalAIStatus) => {
    requestRef.current += 1;
    setStatus(next);
    setFailed(false);
  }, []);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    try {
      const next = await getLocalAIStatus();
      if (requestRef.current !== requestId) return;
      setStatus(next);
      setFailed(false);
    } catch {
      if (requestRef.current !== requestId) return;
      setStatus(null);
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    requestRef.current += 1;
    return () => {
      requestRef.current += 1;
    };
  }, [view]);

  useEffect(() => {
    if (view === "local-ai") return;
    void refresh();
  }, [refresh, view]);

  useEffect(() => {
    if (view === "local-ai") return;
    const delay = failed ? STATUS_RETRY_DELAY_MS : nextPollDelay(status?.state ?? null);
    if (delay === null) return;
    const timer = window.setTimeout(() => void refresh(), delay);
    return () => window.clearTimeout(timer);
  }, [failed, refresh, status, view]);

  return { acceptStatus, failed, refresh, status };
}
