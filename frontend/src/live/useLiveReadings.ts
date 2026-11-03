/**
 * useLiveReadings — subscribe to the backend SSE live stream and maintain a
 * map of the most recent reading per sensor_id / machine_id.
 *
 * Readings are automatically marked stale after `staleAfterMs` milliseconds
 * (default 30 s) so the 3D overlay can show a grey "stale" colour instead of
 * falsely implying the sensor is active.
 *
 * Usage:
 *   const { readings, connected } = useLiveReadings(import.meta.env.VITE_API_BASE_URL ?? "/api/v1");
 */
import { useEffect, useRef, useState } from "react";

export type LiveReading = {
  sensor_id: string;
  machine_id: string;
  organization_id: string;
  quantity: string;
  unit: string;
  value: number;
  event_time_utc: string;
  received_at_utc: string;
  source: string;
  ts: number;       // Date.now() at receipt — used for staleness
  stale: boolean;
};

export type LiveReadingsMap = Record<string, LiveReading>;   // keyed by machine_id

const DEFAULT_STALE_MS = 30_000;

export function useLiveReadings(
  baseUrl: string,
  staleAfterMs = DEFAULT_STALE_MS,
): { readings: LiveReadingsMap; connected: boolean } {
  const [readings, setReadings] = useState<LiveReadingsMap>({});
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Normalise base URL — strip trailing slash, ensure no double /api/v1/api/v1
    const base = baseUrl.replace(/\/+$/, "");
    const url = `${base}/live/stream`;

    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onerror = () => {
      // EventSource reconnects automatically; just reflect disconnected state
      setConnected(false);
    };

    es.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as Omit<LiveReading, "ts" | "stale">;
        if (!msg.machine_id) return;
        setReadings((prev) => ({
          ...prev,
          [msg.machine_id]: { ...msg, ts: Date.now(), stale: false },
        }));
      } catch {
        // Ignore malformed frames
      }
    };

    // Staleness ticker — runs every 5 s, marks readings whose ts is old
    timerRef.current = setInterval(() => {
      const cutoff = Date.now() - staleAfterMs;
      setReadings((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const [key, r] of Object.entries(next)) {
          if (!r.stale && r.ts < cutoff) {
            next[key] = { ...r, stale: true };
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, 5_000);

    return () => {
      es.close();
      esRef.current = null;
      if (timerRef.current !== null) clearInterval(timerRef.current);
    };
  }, [baseUrl, staleAfterMs]);

  return { readings, connected };
}

