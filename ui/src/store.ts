import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, STREAM_URL } from "./lib/api";
import { connectStream } from "./lib/sse";
import { NODE_BY_KEY, NODE_ORDER, type Severity } from "./lib/meta";
import type {
  ChatMessage,
  FeedbackVerdict,
  HealthResponse,
  IncidentSummary,
  SSEEvent,
  SSEType,
} from "./types";

export type NodePhaseState = "pending" | "running" | "done" | "skipped";

export interface NodeRuntime {
  key: string;
  state: NodePhaseState;
  ms?: number;
  badge?: string;
  summary?: string;
  startedAt?: number;
}

export interface TokenStat {
  tokens: number;
  cost: number;
  calls: number;
}

export interface LogItem {
  id: string;
  ts: number;
  type: SSEType;
  incidentKey?: string;
  system?: string;
  journey?: string;
  trnsId?: string;
  srvcId?: string;
  errCd?: string;
  level: Severity;
  bizFailInSuccess: boolean;
  message: string;
}

export type ConnState = "connecting" | "open" | "down";

export interface ChatFeedItem {
  sessionId: string;
  message: ChatMessage;
  incidentKey?: string;
}

export interface AppStore {
  conn: ConnState;
  health: HealthResponse | null;
  apiReachable: boolean;
  logs: LogItem[];
  incidents: IncidentSummary[];
  nodes: Record<string, NodeRuntime>;
  tokens: TokenStat;
  chatFeed: ChatFeedItem[];
  backEdgeAt: number;
  runIncidentKey: string | null;
  lastEventAt: number;
  refreshIncidents: () => void;
  fireScenario: (id: string) => Promise<{ ok: boolean }>;
  sendFeedback: (b: { incidentKey: string; verdict: FeedbackVerdict; note?: string }) => Promise<{ ok: boolean }>;
}

function freshNodes(): Record<string, NodeRuntime> {
  const out: Record<string, NodeRuntime> = {};
  for (const key of NODE_ORDER) {
    out[key] = { key, state: "pending", badge: NODE_BY_KEY[key]?.badge };
  }
  return out;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}
function bool(v: unknown): boolean | undefined {
  if (typeof v === "boolean") return v;
  if (v === "success" || v === "true" || v === 1 || v === "1") return true;
  if (v === "error" || v === "false" || v === 0 || v === "0" || v === "-2") return false;
  return undefined;
}

// Classify a log/incident SSE frame into a board severity + the special
// "business failure inside a transport success" flag (claim §5 / demo tint).
function classifyLog(ev: SSEEvent): LogItem {
  const p = ev.payload ?? {};
  const transportOk = bool(p.transportOk ?? p.transport_ok ?? p.trns_sts ?? p.trns_stts);
  const businessOk = bool(p.businessOk ?? p.business_ok);
  const errTyp = str(p.err_typ ?? p.errTyp);
  const level = str(p.level);
  const bizFailInSuccess = transportOk === true && businessOk === false;

  let sev: Severity = "info";
  if (ev.type === "incident") sev = "crit";
  else if (bizFailInSuccess) sev = "biz";
  else if (transportOk === false || level === "error" || errTyp === "TECHNICAL_EXCEPTION") sev = "crit";
  else if (level === "warn" || errTyp === "BUSINESS_EXCEPTION" || businessOk === false) sev = "warn";
  else if (businessOk === true || transportOk === true || level === "info") sev = "ok";

  const message =
    str(p.message) ??
    str(p.err_dscrptn) ??
    str(p.err_msg) ??
    str(ev.summary) ??
    (ev.type === "incident" ? `incident ${ev.incidentKey ?? ""}` : ev.type);

  return {
    id: `${ev.type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    ts: Date.now(),
    type: ev.type,
    incidentKey: ev.incidentKey,
    system: str(p.system) ?? str(p.systm_nm) ?? str((p.meta as Record<string, unknown>)?.system),
    journey: str(p.journey) ?? str((p.meta as Record<string, unknown>)?.route),
    trnsId: str(p.trnsId) ?? str(p.trns_id),
    srvcId: str(p.srvcId) ?? str(p.srvc_id) ?? str(p.cmnd_id),
    errCd: str(p.errCd) ?? str(p.err_cd),
    level: sev,
    bizFailInSuccess,
    message: message ?? "",
  };
}

const LOG_CAP = 160;
const INCIDENT_CAP = 40;

export function useAppStore(): AppStore {
  const [conn, setConn] = useState<ConnState>("connecting");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [apiReachable, setApiReachable] = useState(false);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [nodes, setNodes] = useState<Record<string, NodeRuntime>>(freshNodes);
  const [tokens, setTokens] = useState<TokenStat>({ tokens: 0, cost: 0, calls: 0 });
  const [chatFeed, setChatFeed] = useState<ChatFeedItem[]>([]);
  const [backEdgeAt, setBackEdgeAt] = useState(0);
  const [runIncidentKey, setRunIncidentKey] = useState<string | null>(null);
  const [lastEventAt, setLastEventAt] = useState(0);

  const logBuf = useRef<LogItem[]>([]);

  const refreshIncidents = useCallback(() => {
    api
      .incidents(25)
      .then((rows) => {
        setIncidents(rows);
        setApiReachable(true);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 0) setApiReachable(false);
      });
  }, []);

  const applyNode = useCallback((ev: SSEEvent) => {
    const key = ev.node;
    if (!key || !(key in NODE_BY_KEY)) return;
    setNodes((prev) => {
      const next = { ...prev };
      const cur = next[key] ?? { key, state: "pending" as NodePhaseState };
      const badge = str(ev.payload?.badge) ?? cur.badge ?? NODE_BY_KEY[key]?.badge;
      const skipped = ev.payload?.skipped === true || /skip/i.test(ev.summary ?? "");

      if (key === "intake" && ev.phase === "start") {
        // new run — reset the graph
        const reset = freshNodes();
        reset.intake = { key: "intake", state: "running", startedAt: Date.now(), badge, summary: ev.summary };
        return reset;
      }
      if (skipped) {
        next[key] = { ...cur, state: "skipped", badge, summary: ev.summary, ms: ev.ms ?? cur.ms };
        return next;
      }
      if (ev.phase === "start") {
        next[key] = { ...cur, state: "running", startedAt: Date.now(), badge, summary: ev.summary ?? cur.summary };
      } else if (ev.phase === "end") {
        const ms = ev.ms ?? (cur.startedAt ? Date.now() - cur.startedAt : cur.ms);
        next[key] = { ...cur, state: "done", ms, badge, summary: ev.summary ?? cur.summary };
      } else {
        next[key] = { ...cur, badge, summary: ev.summary ?? cur.summary, ms: ev.ms ?? cur.ms };
      }
      return next;
    });

    // verify -> collect back-edge: collect starts again after verify has run.
    if (key === "collect" && ev.phase === "start") {
      setNodes((prev) => {
        const v = prev.verify?.state;
        if (v === "running" || v === "done") setBackEdgeAt(Date.now());
        return prev;
      });
    }
  }, []);

  const onEvent = useCallback(
    (ev: SSEEvent) => {
      setLastEventAt(Date.now());
      if (ev.incidentKey) setRunIncidentKey(ev.incidentKey);

      if (ev.type === "node") {
        applyNode(ev);
        return;
      }
      if (ev.type === "token") {
        const p = ev.payload ?? {};
        const dTok = Number(p.tokens ?? 0) || 0;
        const dCost = Number(p.cost ?? p.costUsd ?? 0) || 0;
        const absTok = p.totalTokens !== undefined ? Number(p.totalTokens) : undefined;
        const absCost = p.totalCost !== undefined ? Number(p.totalCost) : undefined;
        setTokens((prev) => ({
          tokens: absTok !== undefined ? absTok : prev.tokens + dTok,
          cost: absCost !== undefined ? absCost : prev.cost + dCost,
          calls: prev.calls + 1,
        }));
        return;
      }
      if (ev.type === "chat") {
        const p = ev.payload ?? {};
        const sessionId = String(ev.sessionId ?? (p.sessionId as string | undefined) ?? "");
        const message = p.message as ChatMessage | undefined;
        if (sessionId && message) {
          setChatFeed((prev) =>
            [...prev, { sessionId, message, incidentKey: ev.incidentKey }].slice(-50),
          );
        }
        return;
      }
      // log + incident frames both feed the firehose
      logBuf.current.push(classifyLog(ev));
      if (logBuf.current.length > LOG_CAP * 2) {
        logBuf.current = logBuf.current.slice(-LOG_CAP);
      }
      if (ev.type === "incident") {
        // an incident notification — refresh the list so cards render live
        setIncidents((prev) => {
          const key = ev.incidentKey;
          if (!key) return prev;
          const status = (ev.payload?.status as IncidentSummary["status"]) ?? "analyzing";
          const summary: IncidentSummary = {
            incidentKey: key,
            status,
            originComponent: str(ev.payload?.originComponent),
            journeysInvolved: (ev.payload?.journeysInvolved as string[]) ?? undefined,
            systemsInvolved: (ev.payload?.systemsInvolved as string[]) ?? undefined,
            errCds: (ev.payload?.errCds as string[]) ?? undefined,
          };
          const rest = prev.filter((i) => i.incidentKey !== key);
          return [summary, ...rest].slice(0, INCIDENT_CAP);
        });
        if ((ev.payload?.status ?? ev.phase) === "complete" || ev.phase === "end") {
          refreshIncidents();
        }
      }
    },
    [applyNode, refreshIncidents],
  );

  // Flush the throttled log buffer to state on a fixed cadence (<=~8 fps).
  useEffect(() => {
    const t = window.setInterval(() => {
      if (logBuf.current.length === 0) return;
      const batch = logBuf.current;
      logBuf.current = [];
      setLogs((prev) => [...batch.reverse(), ...prev].slice(0, LOG_CAP));
    }, 130);
    return () => window.clearInterval(t);
  }, []);

  // SSE lifecycle.
  useEffect(() => {
    const ctrl = connectStream(STREAM_URL, {
      onEvent,
      onOpen: () => {
        setConn("open");
        setApiReachable(true);
      },
      onError: () => setConn((c) => (c === "open" ? "down" : "connecting")),
    });
    return () => ctrl.close();
  }, [onEvent]);

  // Health poll + initial incident load.
  useEffect(() => {
    let live = true;
    const poll = () => {
      api
        .health()
        .then((h) => {
          if (!live) return;
          setHealth(h);
          setApiReachable(true);
        })
        .catch(() => {
          if (!live) return;
          setApiReachable(false);
        });
    };
    poll();
    refreshIncidents();
    const t = window.setInterval(poll, 15000);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, [refreshIncidents]);

  const fireScenario = useCallback((id: string) => api.fireScenario(id), []);
  const sendFeedback = useCallback(
    (b: { incidentKey: string; verdict: FeedbackVerdict; note?: string }) => api.feedback(b),
    [],
  );

  return {
    conn,
    health,
    apiReachable,
    logs,
    incidents,
    nodes,
    tokens,
    chatFeed,
    backEdgeAt,
    runIncidentKey,
    lastEventAt,
    refreshIncidents,
    fireScenario,
    sendFeedback,
  };
}
