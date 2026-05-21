import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import {
  ApiError,
  fetchBenativeArticles,
  fetchBenativeProgress,
  fetchBenativeResponses,
  type BenativeArticle,
  type BenativeProgress,
  type BenativeResponse,
} from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

/** Fetches benative articles for article selection. */
export function useBenativeArticles(
  enabled: boolean = false,
): {
  articles: BenativeArticle[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const { token } = useClient();
  const [articles, setArticles] = useState<BenativeArticle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchArticles = useCallback(async () => {
    try {
      const data = await fetchBenativeArticles(token);
      setArticles(data.articles);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message);
    }
  }, [token]);

  useEffect(() => {
    if (!enabled) {
      setArticles([]);
      setError(null);
      return;
    }

    setLoading(true);
    void fetchArticles()
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [enabled, fetchArticles]);

  return { articles, loading, error, refresh: fetchArticles };
}

/** Fetches benative progress for a session. */
export function useBenativeProgress(
  sessionKey: string | null,
  enabled: boolean = false,
): {
  progress: BenativeProgress | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const { token } = useClient();
  const [progress, setProgress] = useState<BenativeProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const fetchProgress = useCallback(async () => {
    if (!sessionKey) return;
    try {
      const data = await fetchBenativeProgress(token, sessionKey);
      setProgress(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message);
    }
  }, [sessionKey, token]);

  useEffect(() => {
    if (!enabled || !sessionKey) {
      setProgress(null);
      setError(null);
      return;
    }

    setLoading(true);
    void fetchProgress()
      .catch(() => {})
      .finally(() => setLoading(false));

    intervalRef.current = setInterval(() => {
      if (enabledRef.current) {
        void fetchProgress();
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, sessionKey, fetchProgress]);

  return { progress, loading, error, refresh: fetchProgress };
}

/** Fetches benative user responses for a session. */
export function useBenativeResponses(
  sessionKey: string | null,
  enabled: boolean = false,
): {
  responses: BenativeResponse[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
} {
  const { token } = useClient();
  const [responses, setResponses] = useState<BenativeResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const fetchResponses = useCallback(async () => {
    if (!sessionKey) return;
    try {
      const data = await fetchBenativeResponses(token, sessionKey);
      setResponses(data.responses);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message);
    }
  }, [sessionKey, token]);

  useEffect(() => {
    if (!enabled || !sessionKey) {
      setResponses([]);
      setError(null);
      return;
    }

    setLoading(true);
    void fetchResponses()
      .catch(() => {})
      .finally(() => setLoading(false));

    intervalRef.current = setInterval(() => {
      if (enabledRef.current) {
        void fetchResponses();
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, sessionKey, fetchResponses]);

  return { responses, loading, error, refresh: fetchResponses };
}
