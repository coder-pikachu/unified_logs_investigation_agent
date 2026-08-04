import { useEffect, useMemo, useRef, useState } from "react";

import { Chip, CopyButton, EmptyState, FaultBadge, StatBadge } from "../components/primitives";
import { useIncidentDoc } from "../hooks";
import { api, ApiError } from "../lib/api";
import { cx, fmtClockMs, fmtDateTime, fmtInt, fmtMs, pct, timeMs, truncate } from "../lib/format";
import { SEV_HEX, type Severity } from "../lib/meta";
import type { AppStore } from "../store";
import type { Incident, MergedLog, Recommendation, TimelineEntry } from "../types";

function isFalse(v: string | undefined): boolean {
  return v === "error" || v === "false" || v === "-2" || v === "0" || v === "fail" || v === "failed";
}
function isTrue(v: string | undefined): boolean {
  return v === "success" || v === "true" || v === "1" || v === "ok";
}

function sevOfEntry(e: TimelineEntry): Severity {
  const t = String(e.transportStatus ?? "");
  const b = String(e.businessStatus ?? "");
  if (isTrue(t) && isFalse(b)) return "biz"; // business failure inside transport success
  if (isFalse(t)) return "crit";
  if (isFalse(b)) return "warn";
  return "ok";
}

function isOrigin(e: TimelineEntry, origin: string): boolean {
  if (!origin) return false;
  const o = origin.toLowerCase();
  return (
    e.system?.toLowerCase() === o ||
    e.srvcId?.toLowerCase() === o ||
    e.journey?.toLowerCase() === o ||
    /origin|root cause/i.test(e.note ?? "")
  );
}

interface Lane {
  group: "journey" | "system";
  key: string;
  entries: { e: TimelineEntry; origin: boolean }[];
}

function buildLanes(inc: Incident): Lane[] {
  // exact origin doc when the agent recorded one; else first component match
  const originId =
    inc.originDocId ?? (inc.timeline ?? []).find((e) => isOrigin(e, inc.originComponent))?._id;
  const journeys = new Map<string, Lane>();
  const systems = new Map<string, Lane>();
  for (const e of inc.timeline ?? []) {
    const isO = e._id != null && e._id === originId;
    const hasSystem = Boolean(e.system && e.system !== "NULL");
    if (e.journey) {
      const l = journeys.get(e.journey) ?? { group: "journey", key: e.journey, entries: [] };
      // mark ORIGIN once: on the system lane when the event has one
      l.entries.push({ e, origin: isO && !hasSystem });
      journeys.set(e.journey, l);
    }
    if (hasSystem) {
      const l = systems.get(e.system) ?? { group: "system", key: e.system, entries: [] };
      l.entries.push({ e, origin: isO });
      systems.set(e.system, l);
    }
  }
  return [...journeys.values(), ...systems.values()];
}

function Swimlanes({
  inc,
  onPick,
}: {
  inc: Incident;
  onPick: (e: TimelineEntry) => void;
}) {
  const lanes = useMemo(() => buildLanes(inc), [inc]);
  const times = (inc.timeline ?? []).map((e) => timeMs(e.ts)).filter(Boolean);
  const t0 = times.length ? Math.min(...times) : 0;
  const t1 = times.length ? Math.max(...times) : 1;
  const span = t1 - t0 || 1;

  const GUTTER = 132;
  const W = 1000;
  const LH = 30;
  const top = 26;
  const H = top + lanes.length * LH + 12;
  const xOf = (ts: string) => GUTTER + (((timeMs(ts) - t0) / span) * (W - GUTTER - 20));

  if (lanes.length === 0) return <EmptyState title="No timeline entries" icon="—" />;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="incident swimlanes">
      {/* time axis */}
      <line x1={GUTTER} y1={top - 8} x2={W - 20} y2={top - 8} stroke="#2a3644" strokeWidth={1} />
      <text x={GUTTER} y={top - 12} fontSize={8} className="fill-muted font-mono">
        {fmtClockMs(new Date(t0))}
      </text>
      <text x={W - 20} y={top - 12} fontSize={8} textAnchor="end" className="fill-muted font-mono">
        {fmtClockMs(new Date(t1))}
      </text>

      {/* quarter-span gridlines make the ordering readable */}
      {[0.25, 0.5, 0.75].map((f) => {
        const gx = GUTTER + f * (W - GUTTER - 20);
        return (
          <g key={f}>
            <line x1={gx} y1={top - 8} x2={gx} y2={H - 8} stroke="#1a2430" strokeWidth={1} strokeDasharray="2,3" />
            <text x={gx} y={top - 12} fontSize={7} textAnchor="middle" className="fill-muted font-mono">
              {fmtClockMs(new Date(t0 + f * span))}
            </text>
          </g>
        );
      })}

      {lanes.map((lane, li) => {
        const y = top + li * LH + LH / 2;
        const groupColor = lane.group === "journey" ? "#3ad0c0" : "#5aa8f0";
        return (
          <g key={`${lane.group}-${lane.key}`}>
            <line x1={GUTTER} y1={y} x2={W - 20} y2={y} stroke="#171f2b" strokeWidth={1} />
            <text x={6} y={y + 3} fontSize={9} className="font-mono" fill={groupColor}>
              {truncate(lane.key, 18)}
            </text>
            <text x={6} y={y + 12} fontSize={6.5} className="fill-muted font-mono">
              {lane.group}
            </text>
            {lane.entries.map((it, i) => {
              const sev = sevOfEntry(it.e);
              const x = xOf(it.e.ts);
              const color = SEV_HEX[sev];
              if (it.origin) {
                return (
                  <g key={i} className="cursor-pointer" onClick={() => onPick(it.e)}>
                    <circle cx={x} cy={y} r={7} fill="none" stroke={SEV_HEX.info} strokeWidth={1.4} className="animate-pulsedot" />
                    <circle cx={x} cy={y} r={3.5} fill={SEV_HEX.info} />
                    <text x={x} y={y - 10} fontSize={7} textAnchor="middle" className="fill-sev-info font-mono">
                      ORIGIN
                    </text>
                  </g>
                );
              }
              return (
                <circle
                  key={i}
                  cx={x}
                  cy={y}
                  r={sev === "ok" ? 2.5 : 4}
                  fill={color}
                  className="cursor-pointer"
                  onClick={() => onPick(it.e)}
                >
                  <title>{`${fmtClockMs(it.e.ts)} · ${it.e.srvcId} · ${it.e.errCd} · ${it.e.note ?? ""}`}</title>
                </circle>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

const TIER_META: Record<Recommendation["tier"], { label: string; sev: Severity }> = {
  immediate: { label: "Immediate", sev: "crit" },
  fix: { label: "Fix", sev: "warn" },
  prevention: { label: "Prevention", sev: "info" },
};

function Recommendations({ recs }: { recs: Recommendation[] }) {
  const order: Recommendation["tier"][] = ["immediate", "fix", "prevention"];
  if (!recs?.length) return <EmptyState title="No recommendations" icon="—" />;
  return (
    <div className="space-y-2">
      {order.map((tier) => {
        const items = recs.filter((r) => r.tier === tier);
        if (!items.length) return null;
        const tm = TIER_META[tier];
        return (
          <div key={tier}>
            <div className="mb-1 flex items-center gap-2">
              <Chip sev={tm.sev}>{tm.label}</Chip>
            </div>
            <div className="space-y-1.5">
              {items.map((r, i) => (
                <div key={i} className="panel-2 border border-edge p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-sm text-fg">{r.action}</div>
                    <CopyButton text={r.action} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <span className="chip border border-edge text-fgdim">owner · {r.ownerSystem}</span>
                    <span className="chip border border-edge text-fgdim">effort · {r.effort}</span>
                    <span className="chip border border-edge text-fgdim">impact · {r.impact}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FeedbackBox({
  incidentKey,
  send,
}: {
  incidentKey: string;
  send: AppStore["sendFeedback"];
}) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "err">("idle");

  const submit = (verdict: "up" | "down") => {
    setState("sending");
    send({ incidentKey, verdict, note: note.trim() || undefined })
      .then(() => setState("sent"))
      .catch(() => setState("err"));
  };

  return (
    <div className="panel-2 border border-edge p-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="label">feedback · runs the learn path</span>
        {state === "sent" && <span className="text-[11px] text-sev-ok">✓ recorded</span>}
        {state === "err" && <span className="text-[11px] text-sev-crit">failed</span>}
      </div>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="optional note (what was right / wrong)…"
        rows={2}
        className="mb-1.5 w-full rounded border border-edge bg-ink px-2 py-1 text-xs text-fg outline-none focus:border-accent"
      />
      <div className="flex gap-2">
        <button className="btn hover:border-sev-ok hover:text-sev-ok" disabled={state === "sending"} onClick={() => submit("up")}>
          👍 helpful
        </button>
        <button className="btn hover:border-sev-crit hover:text-sev-crit" disabled={state === "sending"} onClick={() => submit("down")}>
          👎 off
        </button>
      </div>
    </div>
  );
}

function RawLogs({
  logs,
  loading,
  reachable,
  highlightId,
  citeMiss,
}: {
  logs: MergedLog[];
  loading: boolean;
  reachable: boolean;
  highlightId: string | null;
  citeMiss: string | null;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!highlightId) return;
    setOpenIds((prev) => {
      const next = new Set(prev);
      next.add(highlightId);
      return next;
    });
    // let the expanded row mount before scrolling to it
    const t = window.setTimeout(() => {
      const el = ref.current?.querySelector(`[data-id="${CSS.escape(highlightId)}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 60);
    return () => window.clearTimeout(t);
  }, [highlightId, logs]);

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="border-b border-edge px-3 py-2 text-sm font-medium text-fg">
        Raw logs / evidence
        <span className="label ml-2">GET /api/logs</span>
        {citeMiss && (
          <div className="mt-1 text-[10px] font-normal text-sev-warn">
            cited doc {truncate(citeMiss, 14)} is no longer in the audit window (7-day TTL)
          </div>
        )}
      </div>
      <div ref={ref} className="min-h-0 flex-1 overflow-auto p-2">
        {loading && <div className="p-2 text-xs text-muted">loading…</div>}
        {!loading && !reachable && <EmptyState title="API unreachable" hint="Logs load once the agent API is up." icon="⚠" />}
        {!loading && reachable && logs.length === 0 && <EmptyState title="No logs" icon="∅" />}
        <div className="space-y-1">
          {logs.map((l) => {
            const hit = highlightId != null && l._id === highlightId;
            const open = openIds.has(l._id);
            const code = String(l.err_cd ?? l.trns_stts ?? l.trns_sts ?? "");
            const name = String(l.srvc_id ?? l.cmnd_id ?? l.systm_nm ?? "");
            const msg = String(l.err_dscrptn ?? l.err_msg ?? "");
            const benign = /^(success|200|0|OK)$/i.test(code);
            return (
              <div
                key={l._id}
                data-id={l._id}
                onClick={() => toggle(l._id)}
                className={cx(
                  "panel-2 cursor-pointer border font-mono text-[10px] transition-colors",
                  hit ? "border-sev-info bg-sev-info/10" : "border-edge",
                )}
              >
                <div className="flex items-center gap-2 p-1.5">
                  <Chip sev={l.source?.includes("error") ? "crit" : l.source?.includes("service") ? "info" : "idle"}>
                    {(l.source ?? "").replace("audit_", "")}
                  </Chip>
                  <span className="min-w-0 flex-1 truncate text-fgdim">{truncate(name, 34)}</span>
                  {code && <span className={benign ? "text-muted" : "text-sev-crit"}>{code}</span>}
                  <span className="text-muted">{l.ts ? fmtClockMs(l.ts) : ""}</span>
                  <span className="text-muted">{open ? "−" : "+"}</span>
                </div>
                {msg && <div className="px-1.5 pb-1 text-fgdim">{truncate(msg, 90)}</div>}
                {open && (
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all border-t border-edge p-1.5 text-[9.5px] leading-snug text-fgdim">
                    {JSON.stringify(l, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Rca({
  inc,
  onCite,
}: {
  inc: Incident;
  onCite: (id: string) => void;
}) {
  const rca = inc.rca;
  if (!rca) return <EmptyState title="No RCA yet" icon="—" />;
  const conf = Math.max(0, Math.min(1, rca.confidence ?? 0));
  return (
    <div className="space-y-2.5">
      <div>
        <span className="label">root cause</span>
        <div className="mt-0.5 text-sm text-fg">{rca.rootCause}</div>
      </div>
      {rca.causalChain?.length ? (
        <div>
          <span className="label">causal chain</span>
          <ol className="mt-1 space-y-1">
            {rca.causalChain.map((step, i) => (
              <li key={i} className="flex gap-2 text-xs text-fgdim">
                <span className="kpi text-muted">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {rca.contributingFactors?.length ? (
        <div>
          <span className="label">contributing factors</span>
          <ul className="mt-1 list-inside list-disc text-xs text-fgdim">
            {rca.contributingFactors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {rca.evidence?.length ? (
        <div>
          <span className="label">evidence · click to locate the doc _id</span>
          <div className="mt-1 flex flex-wrap gap-1">
            {rca.evidence.map((id, i) => (
              <button
                key={id}
                onClick={() => onCite(id)}
                title={id}
                className="chip border border-sev-info/40 text-sev-info hover:bg-sev-info/10"
              >
                [{i + 1}] {truncate(id, 10)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className="grid grid-cols-[auto_1fr] items-center gap-2">
        <span className="label">confidence</span>
        <div className="flex items-center gap-2">
          <div className="h-2 flex-1 overflow-hidden rounded bg-edge">
            <div
              className={cx("h-full", conf > 0.66 ? "bg-sev-ok" : conf > 0.33 ? "bg-sev-warn" : "bg-sev-crit")}
              style={{ width: pct(conf) }}
            />
          </div>
          <span className="kpi text-xs text-fg">{pct(conf)}</span>
        </div>
      </div>
      {rca.unknowns?.length ? (
        <div>
          <span className="label">unknowns</span>
          <ul className="mt-1 list-inside list-disc text-xs text-sev-warn/90">
            {rca.unknowns.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function CollectionsPanel({ inc }: { inc: Incident }) {
  const cols = inc.collectionsAnalyzed ?? [];
  if (!cols.length) return null;
  return (
    <div className="panel p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium text-fg">Collections analyzed</span>
        <span className="label">one Atlas DB · {cols.length} collections</span>
      </div>
      <div className="space-y-1">
        {cols.map((c) => (
          <div key={c.collection} className="flex items-center gap-2 text-[11px]">
            <span className={cx("font-mono", c.examined > 0 ? "text-accent" : "text-muted")}>
              {c.collection}
            </span>
            <span className="min-w-0 flex-1 truncate text-muted">{c.role}</span>
            <span className={cx("kpi", c.examined > 0 ? "text-fg" : "text-muted")}>{c.examined}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function workloadTint(w?: string): string {
  if (!w) return "text-muted border-edge";
  if (/TIME SERIES/i.test(w)) return "text-sev-info border-sev-info/40";
  if (/rankFusion|Vector|Search/i.test(w)) return "text-accent border-accent/40";
  return "text-muted border-edge";
}

function AgentQueriesPanel({ inc }: { inc: Incident }) {
  const queries = inc.agentQueries ?? [];
  const [open, setOpen] = useState<number | null>(null);
  if (!queries.length) return null;
  return (
    <div className="panel p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium text-fg">Agent queries · MongoDB</span>
        <span className="label">{queries.length} queries · execution order</span>
      </div>
      <div className="space-y-1">
        {queries.map((q, i) => (
          <div key={i} className="panel-2 border border-edge">
            <button
              className="flex w-full items-center gap-2 px-2 py-1 text-left"
              onClick={() => setOpen(open === i ? null : i)}
            >
              <span className="kpi text-muted">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate text-[11px] text-fgdim">{q.purpose}</span>
              <span className="font-mono text-[10px] text-accent">{q.collection}</span>
              {q.workload && (
                <span className={cx("chip border text-[9px]", workloadTint(q.workload))}>{q.workload}</span>
              )}
              <span className="text-muted">{open === i ? "−" : "+"}</span>
            </button>
            {open === i && (
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all border-t border-edge p-2 font-mono text-[10px] leading-snug text-fgdim">
                {JSON.stringify(q.query, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}



export function IncidentDetail({
  store,
  selectedKey,
  onSelectKey,
}: {
  store: AppStore;
  selectedKey: string | null;
  onSelectKey: (k: string | null) => void;
}) {
  const key = selectedKey ?? store.incidents[0]?.incidentKey ?? null;
  const inc = useIncidentDoc(key);
  const doc = inc.data;

  const [logs, setLogs] = useState<MergedLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsReachable, setLogsReachable] = useState(true);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const [citeMiss, setCiteMiss] = useState<string | null>(null);

  useEffect(() => {
    setHighlightId(null);
    setCiteMiss(null);
    setLogs([]);
    if (!doc) return;
    const trnsId = doc.trnsIds?.[0];
    const sessnTknId = doc.sessnTknIds?.[0];
    const evidence = (doc.rca?.evidence ?? []).join(",");
    if (!trnsId && !sessnTknId && !evidence) return;
    setLogsLoading(true);
    const base: Promise<MergedLog[]> =
      trnsId || sessnTknId ? api.logs({ trnsId, sessnTknId, limit: 200 }) : Promise.resolve([]);
    const cited: Promise<MergedLog[]> = evidence
      ? api.logs({ ids: evidence }).catch(() => [])
      : Promise.resolve([]);
    Promise.all([base, cited])
      .then(([rows, ev]) => {
        const seen = new Set(rows.map((r) => r._id));
        const merged = [...rows, ...ev.filter((d) => !seen.has(d._id))];
        merged.sort((a, b) => String(a.ts ?? "").localeCompare(String(b.ts ?? "")));
        setLogs(merged);
        setLogsReachable(true);
        setLogsLoading(false);
      })
      .catch((e: unknown) => {
        setLogsLoading(false);
        if (e instanceof ApiError && e.status === 0) setLogsReachable(false);
      });
  }, [doc]);

  // evidence citation / timeline dot -> locate (fetching on miss) + expand the doc
  const onCite = (id: string) => {
    setCiteMiss(null);
    if (logs.some((l) => l._id === id)) {
      setHighlightId(id);
      return;
    }
    api
      .logs({ ids: id })
      .then((docs) => {
        if (docs.length) {
          setLogs((prev) => {
            const seen = new Set(prev.map((p) => p._id));
            return [...prev, ...docs.filter((d) => !seen.has(d._id))];
          });
          setHighlightId(id);
        } else {
          setCiteMiss(id);
        }
      })
      .catch(() => setCiteMiss(id));
  };

  const onPickEntry = (e: TimelineEntry) => {
    if (e._id) {
      onCite(e._id);
      return;
    }
    const match = logs.find((l) => l.trns_id === e.trnsId && (l.err_cd === e.errCd || l.srvc_id === e.srvcId));
    if (match) setHighlightId(match._id);
  };

  if (!key) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          title="No incident selected"
          hint="Open one from the OPS board, or it appears here once the agent persists an incident."
          icon="◎"
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="panel flex flex-wrap items-center justify-between gap-3 px-3 py-2">
        <div className="flex items-center gap-3">
          <select
            value={key}
            onChange={(e) => onSelectKey(e.target.value || null)}
            className="rounded border border-edge bg-ink px-2 py-1 font-mono text-xs text-fg outline-none focus:border-accent"
          >
            {store.incidents.length === 0 && <option value={key}>{truncate(key, 30)}</option>}
            {store.incidents.map((i) => (
              <option key={i.incidentKey} value={i.incidentKey}>
                {truncate(i.incidentKey, 30)}
              </option>
            ))}
          </select>
          {doc && (
            <>
              <Chip sev={doc.status === "complete" ? "ok" : doc.status === "failed" ? "crit" : "warn"}>
                {doc.status}
              </Chip>
              <FaultBadge fc={doc.faultClass ?? doc.rca?.faultClass} />
            </>
          )}
          <button className="btn !py-0.5 text-[10px]" onClick={inc.reload}>
            reload
          </button>
        </div>
        {doc && (
          <div className="flex flex-wrap items-center gap-4">
            <StatBadge label="origin" value={doc.originComponent || "—"} sev="info" />
            <StatBadge label="p95 base→inc" value={`${fmtMs(doc.metrics?.p95BaselineMs)} → ${fmtMs(doc.metrics?.p95IncidentMs)}`} sev="warn" />
            <StatBadge label="users" value={fmtInt(doc.metrics?.usersAffected ?? doc.blastRadius?.userCount)} />
            <StatBadge label="analyzed" value={fmtMs(doc.durationMs)} />
          </div>
        )}
      </div>

      {inc.loading && <div className="p-4 text-sm text-muted">loading incident…</div>}
      {inc.error === "api-unreachable" && (
        <EmptyState title="API unreachable" hint="Incident detail loads once the agent API is up." icon="⚠" />
      )}
      {inc.error && inc.error !== "api-unreachable" && (
        <div className="p-4 text-sm text-sev-crit">error: {inc.error}</div>
      )}

      {doc && (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[1.5fr_1fr]">
          <div className="flex min-h-0 flex-col gap-3 overflow-auto">
            <div className="panel p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-sm font-medium text-fg">Timeline · cross-collection swimlanes</span>
                <span className="label">
                  <span className="text-sev-info">◎ origin</span> vs loud symptoms
                </span>
              </div>
              {doc.correlation && (
                <div className="mb-2 rounded border border-accent2/30 bg-panel2 px-2 py-1.5">
                  <div className="text-[11px] text-fgdim">
                    <span className="text-accent font-mono">{doc.correlation.totalDocs}</span> documents ·{" "}
                    <span className="text-accent font-mono">{doc.correlation.services.length}</span>{" "}
                    Java {doc.correlation.services.length === 1 ? "service" : "services"} →{" "}
                    <span className="text-accent font-mono">{Object.keys(doc.correlation.collections).length}</span> collections
                    {" · joined on "}
                    <span className="font-mono text-sev-info">trns_id ({doc.correlation.joinKeys.trns_id ?? 0})</span>
                    {" + "}
                    <span className="font-mono text-sev-info">sessn_tkn_id ({doc.correlation.joinKeys.sessn_tkn_id ?? 0})</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {doc.correlation.services.map((s) => (
                      <span key={s.name} className="chip border border-edge text-fgdim">
                        {s.name} · {s.docs} docs → {s.collections.join(", ")}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <Swimlanes inc={doc} onPick={onPickEntry} />
              <div className="mt-1 flex flex-wrap gap-2 text-[10px]">
                {doc.journeysInvolved?.length ? (
                  <span className="text-muted">journeys: <span className="text-fgdim">{doc.journeysInvolved.join(", ")}</span></span>
                ) : null}
                {doc.systemsInvolved?.length ? (
                  <span className="text-muted">systems: <span className="text-fgdim">{doc.systemsInvolved.join(", ")}</span></span>
                ) : null}
                <span className="text-muted">errCds: <span className="text-sev-crit">{(doc.errCds ?? []).join(", ") || "—"}</span></span>
              </div>
            </div>

            <div className="panel p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-sm font-medium text-fg">Root-cause analysis</span>
                <FaultBadge fc={doc.faultClass ?? doc.rca?.faultClass} />
              </div>
              {(doc.faultReason ?? doc.rca?.faultReason) && (
                <div className="mb-1.5 text-[10px] text-muted">
                  fault class{" "}
                  <span className="text-fgdim">{doc.faultClass ?? doc.rca?.faultClass}</span>
                  {" — "}
                  {doc.faultReason ?? doc.rca?.faultReason}
                </div>
              )}
              <Rca inc={doc} onCite={onCite} />
            </div>

            <CollectionsPanel inc={doc} />
            <AgentQueriesPanel inc={doc} />

            <div className="panel p-3">
              <div className="mb-1.5 text-sm font-medium text-fg">Recommendations</div>
              <Recommendations recs={doc.recommendations ?? []} />
            </div>

            <FeedbackBox incidentKey={doc.incidentKey} send={store.sendFeedback} />
          </div>

          <RawLogs logs={logs} loading={logsLoading} reachable={logsReachable} highlightId={highlightId} citeMiss={citeMiss} />
        </div>
      )}
    </div>
  );
}
