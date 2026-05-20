import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { ApiError, fetchSessionNotes, type SessionNotes } from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

/** Fetches session notes with polling support when enabled. */
export function useSessionNotes(
  sessionKey: string | null,
  enabled: boolean = false,
): {
  notes: SessionNotes;
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const { token } = useClient();
  const [notes, setNotes] = useState<SessionNotes>({ vocab: "", polisher: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const fetchNotes = useCallback(async () => {
    if (!sessionKey) return;
    try {
      const data = await fetchSessionNotes(token, sessionKey);
      setNotes(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message);
    }
  }, [sessionKey, token]);

  const refresh = useCallback(() => {
    void fetchNotes();
  }, [fetchNotes]);

  useEffect(() => {
    if (!enabled || !sessionKey) {
      setNotes({ vocab: "", polisher: "" });
      setError(null);
      return;
    }

    setLoading(true);
    void fetchNotes()
      .catch(() => {})
      .finally(() => setLoading(false));

    intervalRef.current = setInterval(() => {
      if (enabledRef.current) {
        void fetchNotes();
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, sessionKey, fetchNotes]);

  return { notes, loading, error, refresh };
}
