import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./lib/api";
import { rateToSeverity, type Severity } from "./lib/meta";
import type { ArchResponse, Incident, MemoryResponse, MetricBucket } from "./types";

export interface MetricsState {
  data: MetricBucket[];
  p95Series: number[];
  latest: MetricBucket | null;
  sev: Severity;
  reachable: boolean;
}

// Polls GET /api/metrics for one service. Slows down while the API is down so
// an unreachable backend never turns into a request storm.
export function useMetrics(service: string, windowSpec = "15m", enabled = true): MetricsState {
  const [state, setState] = useState<MetricsState>({
    data: [],
    p95Series: [],
    latest: null,
    sev: "idle",
    reachable: true,
  });
  const fails = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;

    const tick = () => {
      api
        .metrics(service, windowSpec)
        .then((rows) => {
          if (!live) return;
          fails.current = 0;
          const latest = rows.length ? rows[rows.length - 1] : null;
          setState({
            data: rows,
            p95Series: rows.map((r) => r.p95 ?? 0),
            latest,
            sev: rateToSeverity(latest?.errorRate),
            reachable: true,
          });
        })
        .catch((e: unknown) => {
          if (!live) return;
          fails.current += 1;
          if (e instanceof ApiError && e.status === 0) {
            setState((s) => ({ ...s, reachable: false, sev: "idle" }));
          }
        })
        .finally(() => {
          if (!live) return;
          timer = window.setTimeout(tick, fails.current > 2 ? 20000 : 6000);
        });
    };
    tick();

    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [service, windowSpec, enabled]);

  return state;
}

export interface ArchitectureState {
  data: ArchResponse | null;
  reachable: boolean;
}

// Polls GET /api/architecture while the tab is active (5s, backing off to 20s).
export function useArchitecture(enabled: boolean): ArchitectureState {
  const [state, setState] = useState<ArchitectureState>({ data: null, reachable: true });
  const fails = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;

    const tick = () => {
      api
        .architecture()
        .then((d) => {
          if (!live) return;
          fails.current = 0;
          setState({ data: d, reachable: true });
        })
        .catch((e: unknown) => {
          if (!live) return;
          fails.current += 1;
          if (e instanceof ApiError && e.status === 0) {
            setState((s) => ({ ...s, reachable: false }));
          }
        })
        .finally(() => {
          if (!live) return;
          timer = window.setTimeout(tick, fails.current > 2 ? 20000 : 5000);
        });
    };
    tick();

    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [enabled]);

  return state;
}

export interface IncidentState {
  data: Incident | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useIncidentDoc(key: string | null): IncidentState {
  const [data, setData] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!key) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .incident(key)
      .then((doc) => {
        setData(doc);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setData(null);
        setLoading(false);
        setError(e instanceof ApiError && e.status === 0 ? "api-unreachable" : (e as Error).message);
      });
  }, [key]);

  useEffect(load, [load]);
  return { data, loading, error, reload: load };
}

export interface MemoryState {
  data: MemoryResponse | null;
  loading: boolean;
  reachable: boolean;
  reload: () => void;
}

export function useMemory(enabled: boolean): MemoryState {
  const [data, setData] = useState<MemoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [reachable, setReachable] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .memory()
      .then((m) => {
        setData(m);
        setReachable(true);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setLoading(false);
        if (e instanceof ApiError && e.status === 0) setReachable(false);
      });
  }, []);

  useEffect(() => {
    if (enabled) load();
  }, [enabled, load]);

  return { data, loading, reachable, reload: load };
}
