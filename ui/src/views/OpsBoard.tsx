import { useEffect, useMemo, useState } from "react";

import { Chip, EmptyState, FaultBadge, SevDot } from "../components/primitives";
import { Sparkline } from "../components/Sparkline";
import { useMetrics } from "../hooks";
import { api, ApiError } from "../lib/api";
import { cx, fmtClock, fmtInt, fmtMs, pct, truncate } from "../lib/format";
import {
  JOURNEYS,
  SCENARIOS,
  SEV_CLASS,
  SEV_HEX,
  SYSTEMS,
  type JourneyMeta,
  type Severity,
  type SystemMeta,
} from "../lib/meta";
import type { AppStore, LogItem } from "../store";
import type { ScenarioInfo, SearchResponse } from "../types";

function worse(a: Severity, b: Severity): Severity {
  const rank: Record<Severity, number> = { idle: 0, ok: 1, info: 1, warn: 2, biz: 2, crit: 3 };
  return rank[b] > rank[a] ? b : a;
}

// Build a per-tile escalation map from live incidents + recent firehose so a
// tile turns red the instant an incident references its journey/system.
function useEscalation(store: AppStore): Record<string, Severity> {
  return useMemo(() => {
    const map: Record<string, Severity> = {};
    const bump = (k: string | undefined, sev: Severity) => {
      if (!k) return;
      const key = k.toLowerCase();
      map[key] = worse(map[key] ?? "idle", sev);
    };
    for (const inc of store.incidents) {
      const active = inc.status === "analyzing";
      const sev: Severity = active ? "crit" : "warn";
      (inc.journeysInvolved ?? []).forEach((j) => bump(j, sev));
      (inc.systemsInvolved ?? []).forEach((s) => bump(s, sev));
      bump(inc.originComponent, sev);
    }
    for (const l of store.logs.slice(0, 60)) {
      if (l.level === "crit") {
        bump(l.system, "warn");
        bump(l.journey, "warn");
      }
      if (l.bizFailInSuccess) {
        bump(l.system, "biz");
        bump(l.journey, "biz");
      }
    }
    return map;
  }, [store.incidents, store.logs]);
}

function matchEscalation(map: Record<string, Severity>, keys: string[]): Severity {
  let sev: Severity = "idle";
  for (const k of keys) {
    const hit = map[k.toLowerCase()];
    if (hit) sev = worse(sev, hit);
  }
  return sev;
}

function Tile({
  label,
  hint,
  service,
  escalate,
  active,
}: {
  label: string;
  hint: string;
  service: string;
  escalate: Severity;
  active: boolean;
}) {
  const m = useMetrics(service, "15m", active);
  const sev = worse(m.sev, escalate);
  const c = SEV_CLASS[sev];
  const latest = m.latest;
  return (
    <div className={cx("panel-2 flex flex-col gap-1.5 border p-2.5 transition-colors", c.ring)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <SevDot sev={sev} pulse={sev === "crit"} />
          <span className="font-mono text-xs font-medium text-fg">{label}</span>
        </div>
        <span className={cx("kpi text-[10px]", c.text)}>
          {latest ? pct(latest.errorRate ?? 0, latest.errorRate >= 0.1 ? 0 : 1) : "—"}
        </span>
      </div>
      <Sparkline data={m.p95Series} sev={sev} baseline={latest ? latest.p50 : undefined} width={150} height={30} />
      <div className="flex items-center justify-between text-[10px] text-muted">
        <span className="truncate" title={hint}>
          {truncate(hint, 22)}
        </span>
        <span className="kpi">{latest ? `p95 ${fmtMs(latest.p95)}` : m.reachable ? "idle" : "offline"}</span>
      </div>
    </div>
  );
}

function TileGrid({
  journeys,
  systems,
  esc,
  active,
}: {
  journeys: JourneyMeta[];
  systems: SystemMeta[];
  esc: Record<string, Severity>;
  active: boolean;
}) {
  return (
    <div className="space-y-3">
      <div>
        <div className="label mb-1.5">Journeys · one platform, six workloads</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
          {journeys.map((j) => (
            <Tile
              key={j.key}
              label={j.label}
              hint={j.hint}
              service={j.service}
              active={active}
              escalate={matchEscalation(esc, [j.key, j.label, j.service])}
            />
          ))}
        </div>
      </div>
      <div>
        <div className="label mb-1.5">Downstream systems</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {systems.map((s) => (
            <Tile
              key={s.key}
              label={s.label}
              hint={s.hint}
              service={s.service}
              active={active}
              escalate={matchEscalation(esc, [s.key, s.label])}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function LogRow({ log }: { log: LogItem }) {
  const c = SEV_CLASS[log.level];
  return (
    <div
      className={cx(
        "flex items-start gap-2 border-l-2 px-2 py-1 font-mono text-[11px] leading-tight",
        log.bizFailInSuccess ? "bg-sev-biz/5 text-sev-biz" : "border-transparent",
      )}
      style={{ borderLeftColor: log.bizFailInSuccess ? SEV_HEX.biz : SEV_HEX[log.level] }}
    >
      <span className="w-14 shrink-0 text-muted">{fmtClock(log.ts)}</span>
      <SevDot sev={log.level} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1">
          {log.bizFailInSuccess && <Chip sev="biz" title="Transport OK but business rule failed">biz-fail ∈ success</Chip>}
          {log.system && <span className="text-accent">{log.system}</span>}
          {log.journey && <span className="text-fgdim">{log.journey}</span>}
          {log.srvcId && <span className="text-muted">{truncate(log.srvcId, 28)}</span>}
          {log.errCd && log.errCd !== "NULL" && <span className={c.text}>{log.errCd}</span>}
        </div>
        <div className={cx("truncate", log.bizFailInSuccess ? "text-sev-biz/90" : "text-fgdim")}>
          {truncate(log.message, 90)}
        </div>
      </div>
    </div>
  );
}

function Firehose({ logs }: { logs: LogItem[] }) {
  const [bizOnly, setBizOnly] = useState(false);
  const shown = bizOnly ? logs.filter((l) => l.bizFailInSuccess) : logs;
  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-edge px-2.5 py-1.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-fg">Log firehose</span>
          <span className="label">SSE · ≤20/s</span>
        </div>
        <button
          className={cx("btn !py-0.5 text-[10px]", bizOnly && "border-sev-biz text-sev-biz")}
          onClick={() => setBizOnly((v) => !v)}
        >
          biz-fail only
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {shown.length === 0 ? (
          <EmptyState title="No log events yet" hint="Waiting on SSE. Fire a scenario or start novasim." icon="≋" />
        ) : (
          <div className="divide-y divide-edge/40">
            {shown.map((l) => (
              <LogRow key={l.id} log={l} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function IncidentCards({
  incidents,
  onOpen,
}: {
  incidents: AppStore["incidents"];
  onOpen: (key: string) => void;
}) {
  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="border-b border-edge px-2.5 py-1.5 text-sm font-medium text-fg">
        Live incidents
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
        {incidents.length === 0 ? (
          <EmptyState title="No incidents" hint="Incident cards appear here from SSE the moment the agent opens one." icon="◎" />
        ) : (
          incidents.map((inc) => {
            const sev: Severity =
              inc.status === "analyzing" ? "crit" : inc.status === "failed" ? "warn" : "info";
            return (
              <button
                key={inc.incidentKey}
                onClick={() => onOpen(inc.incidentKey)}
                className={cx(
                  "panel-2 block w-full animate-drawer border p-2 text-left transition-colors hover:border-accent",
                  SEV_CLASS[sev].ring,
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-fg">{truncate(inc.incidentKey, 30)}</span>
                  <div className="flex items-center gap-1">
                    <FaultBadge fc={inc.faultClass ?? inc.rca?.faultClass} />
                    <Chip sev={sev}>{inc.status ?? "—"}</Chip>
                  </div>
                </div>
                {inc.originComponent && (
                  <div className="mt-1 text-[11px] text-fgdim">
                    origin <span className="text-accent">{inc.originComponent}</span>
                  </div>
                )}
                <div className="mt-1 flex flex-wrap gap-1">
                  {(inc.journeysInvolved ?? []).slice(0, 4).map((j) => (
                    <span key={j} className="chip border border-edge text-muted">
                      {j}
                    </span>
                  ))}
                  {(inc.errCds ?? []).slice(0, 3).map((e) => (
                    <span key={e} className="chip border border-sev-crit/40 text-sev-crit">
                      {e}
                    </span>
                  ))}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function SearchPanel() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = () => {
    if (!q.trim()) return;
    setBusy(true);
    setErr(null);
    api
      .search(q.trim())
      .then((r) => {
        setRes(r);
        setBusy(false);
      })
      .catch((e: unknown) => {
        setBusy(false);
        setRes(null);
        setErr(e instanceof ApiError && e.status === 0 ? "API unreachable" : (e as Error).message);
      });
  };

  const hits = res ? [...(res.errors ?? []), ...(res.services ?? [])] : [];
  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-edge px-2.5 py-1.5">
        <span className="text-sm font-medium text-fg">Search</span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="err_cd, message, srvc_id…"
          className="min-w-0 flex-1 rounded border border-edge bg-ink px-2 py-1 font-mono text-xs text-fg outline-none focus:border-accent"
        />
        <button className="btn" onClick={run} disabled={busy}>
          {busy ? "…" : "$search"}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-2">
        {err && <div className="px-1 py-2 text-xs text-sev-warn">{err}</div>}
        {!err && !res && (
          <EmptyState title="Cross-collection $search" hint="Queries audit_error + audit_service, tagged by source." icon="⌕" />
        )}
        {res && hits.length === 0 && <EmptyState title="No matches" icon="∅" />}
        <div className="space-y-1">
          {hits.map((h, i) => {
            const src = String(h.source ?? (res?.errors.includes(h) ? "audit_error" : "audit_service"));
            const isErr = src.includes("error");
            return (
              <div key={`${src}-${i}`} className="panel-2 border border-edge p-1.5 font-mono text-[11px]">
                <div className="mb-0.5 flex items-center justify-between">
                  <Chip sev={isErr ? "crit" : "info"}>{src}</Chip>
                  {h.score !== undefined && <span className="kpi text-muted">score {Number(h.score).toFixed(2)}</span>}
                </div>
                <div className="text-fgdim">
                  {truncate(String(h.err_cd ?? h.srvc_id ?? h._id ?? ""), 40)}{" "}
                  <span className="text-muted">
                    {truncate(String(h.err_dscrptn ?? h.err_msg ?? h.systm_nm ?? ""), 60)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
function ScenarioBar({ fire }: { fire: (id: string) => Promise<{ ok: boolean }> }) {
  const [status, setStatus] = useState<Record<string, "idle" | "firing" | "ok" | "err">>({});
  const [meta, setMeta] = useState<Record<string, ScenarioInfo>>({});
  const [open, setOpen] = useState<string | null>(null);
  const set = (id: string, s: "idle" | "firing" | "ok" | "err") =>
    setStatus((prev) => ({ ...prev, [id]: s }));

  useEffect(() => {
    api
      .scenarios()
      .then((list) => setMeta(Object.fromEntries(list.map((s) => [s.id, s]))))
      .catch(() => {});
  }, []);

  const onFire = (id: string) => {
    set(id, "firing");
    fire(id)
      .then(() => {
        set(id, "ok");
        window.setTimeout(() => set(id, "idle"), 2500);
      })
      .catch(() => {
        set(id, "err");
        window.setTimeout(() => set(id, "idle"), 2500);
      });
  };

  return (
    <div className="panel p-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium text-fg">Scenarios</span>
        <span className="label">secondary path · CLI is primary</span>
      </div>
      <div className="space-y-1">
        {SCENARIOS.map((s) => {
          const st = status[s.id] ?? "idle";
          const info = meta[s.id];
          const isOpen = open === s.id;
          return (
            <div key={s.id} className="panel-2 overflow-hidden">
              <div className="flex items-center gap-2 px-2 py-1">
                <button
                  onClick={() => setOpen(isOpen ? null : s.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  title="show scenario context"
                >
                  <span className="w-2 text-muted">{isOpen ? "▾" : "▸"}</span>
                  <span className="truncate font-mono text-[11px] text-fg">{info?.title ?? s.label}</span>
                  <FaultBadge fc={info?.faultClass} />
                </button>
                <button
                  onClick={() => onFire(s.id)}
                  disabled={st === "firing"}
                  className={cx(
                    "btn font-mono !text-[10px]",
                    st === "ok" && "border-sev-ok text-sev-ok",
                    st === "err" && "border-sev-crit text-sev-crit",
                    st === "firing" && "opacity-60",
                  )}
                >
                  {st === "ok" ? "✓ fired" : st === "err" ? "✕ err" : st === "firing" ? "▸ …" : "fire"}
                </button>
              </div>
              {isOpen && (
                <div className="space-y-1 border-t border-edge/50 px-2 py-1.5 text-[10px]">
                  <div className="text-fgdim">{info?.description ?? s.note}</div>
                  {info?.expectedOrigin && (
                    <div>
                      <span className="text-muted">origin (expected): </span>
                      <span className="text-sev-info">{info.expectedOrigin}</span>
                    </div>
                  )}
                  {info?.decoy && (
                    <div>
                      <span className="text-muted">loud decoy: </span>
                      <span className="text-sev-crit">{info.decoy}</span>
                    </div>
                  )}
                  {info?.analyzes?.length ? (
                    <div>
                      <span className="text-muted">collections analyzed:</span>
                      <ul className="mt-0.5 list-inside list-disc text-fgdim">
                        {info.analyzes.map((a, i) => (
                          <li key={i}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function OpsBoard({
  store,
  active,
  onOpenIncident,
}: {
  store: AppStore;
  active: boolean;
  onOpenIncident: (key: string) => void;
}) {
  const esc = useEscalation(store);
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 xl:grid-cols-[1.5fr_1fr]">
      <div className="flex min-h-0 flex-col gap-3">
        <TileGrid journeys={JOURNEYS} systems={SYSTEMS} esc={esc} active={active} />
        <ScenarioBar fire={store.fireScenario} />
        <div className="min-h-[240px] flex-1">
          <Firehose logs={store.logs} />
        </div>
      </div>
      <div className="grid min-h-0 grid-rows-[1fr_1fr_auto] gap-3">
        <IncidentCards incidents={store.incidents} onOpen={onOpenIncident} />
        <SearchPanel />
        <div className="hidden xl:block">
          <MiniStat store={store} />
        </div>
      </div>
    </div>
  );
}

function MiniStat({ store }: { store: AppStore }) {
  const active = store.incidents.filter((i) => i.status === "analyzing").length;
  const biz = store.logs.filter((l) => l.bizFailInSuccess).length;
  return (
    <div className="panel grid grid-cols-3 gap-2 p-2.5 text-center">
      <div>
        <div className="kpi text-lg text-sev-crit">{fmtInt(active)}</div>
        <div className="label">analyzing</div>
      </div>
      <div>
        <div className="kpi text-lg text-sev-biz">{fmtInt(biz)}</div>
        <div className="label">biz-fail</div>
      </div>
      <div>
        <div className="kpi text-lg text-accent">{fmtInt(store.logs.length)}</div>
        <div className="label">log buffer</div>
      </div>
    </div>
  );
}
