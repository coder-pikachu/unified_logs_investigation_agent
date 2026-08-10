import { Chip, EmptyState, SevDot } from "../components/primitives";
import { useArchitecture } from "../hooks";
import { cx, fmtBytes, fmtClock, fmtInt, fmtMs } from "../lib/format";
import type { Severity } from "../lib/meta";
import type { ArchApp, ArchCollection, ArchResponse } from "../types";

const HOT = ["audit_transaction", "audit_error", "audit_service", "service_metrics"];

function isActive(lastWriteAt?: string | null, nowMs?: number): boolean {
  if (!lastWriteAt) return false;
  const t = new Date(lastWriteAt).getTime();
  return Number.isFinite(t) && (nowMs ?? Date.now()) - t < 10_000;
}

function queryMsSev(ms: number | null): Severity {
  if (ms === null) return "idle";
  if (ms < 20) return "ok";
  if (ms < 100) return "warn";
  return "crit";
}

// ---------------------------------------------------------------- app cards

function AppCard({ app, nowMs }: { app: ArchApp; nowMs: number }) {
  const active = isActive(app.lastWriteAt, nowMs);
  return (
    <div className="panel-2 border border-edge p-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SevDot sev={active ? "ok" : "idle"} pulse={active} />
          <span className="text-xs font-medium text-fg">{app.name}</span>
        </div>
        {app.recentErrors > 0 && (
          <Chip sev="crit" title="errors written in the last 60s">
            {fmtInt(app.recentErrors)} err/60s
          </Chip>
        )}
      </div>
      <div className="mt-0.5 text-[10px] text-muted">{app.tech}</div>
      <div className="mt-2 flex items-end justify-between">
        <div>
          <div className="kpi text-lg text-accent">{app.ingestPerSec.toFixed(2)}</div>
          <div className="label">docs / sec</div>
        </div>
        <div className="text-right text-[10px] text-muted">
          last write
          <div className="font-mono text-fgdim">
            {app.lastWriteAt ? fmtClock(app.lastWriteAt) : "—"}
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {app.writes.map((c) => (
          <span key={c} className="chip border border-accent2/40 text-accent">
            → {c}
          </span>
        ))}
        {(app.channels ?? []).map((c) => (
          <span key={c} className="chip border border-edge text-muted">{c}</span>
        ))}
        {(app.destinations ?? []).map((d) => (
          <span key={d} className="chip border border-edge text-muted">{d}</span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- flow SVG

function FlowDiagram({ data, nowMs }: { data: ArchResponse; nowMs: number }) {
  const hot = data.collections.filter((c) => HOT.includes(c.name));
  const hbActive = isActive(data.agent.watcherHeartbeatAt, nowMs);
  const appY = (i: number) => 26 + i * 44;
  return (
    <svg viewBox="0 0 1000 210" className="w-full" role="img" aria-label="architecture flow">
      {/* apps column */}
      {data.apps.map((a, i) => (
        <g key={a.id}>
          <rect x={8} y={appY(i) - 15} width={196} height={34} rx={4}
                style={{ fill: "rgb(var(--c-panel2))", stroke: isActive(a.lastWriteAt, nowMs) ? "rgb(var(--c-sev-ok))" : "rgb(var(--c-edge2))" }} />
          <text x={18} y={appY(i) - 1} fontSize={10} className="fill-fg font-mono">{a.name}</text>
          <text x={18} y={appY(i) + 11} fontSize={8} className="fill-muted font-mono">
            {a.ingestPerSec.toFixed(2)} docs/s
          </text>
          <line x1={204} y1={appY(i)} x2={300} y2={104} style={{ stroke: "rgb(var(--c-edge2))" }} strokeWidth={1.2} />
        </g>
      ))}
      <text x={222} y={92} fontSize={8} className="fill-muted font-mono">Log4j2 inserts</text>

      {/* Atlas box */}
      <rect x={300} y={30} width={250} height={150} rx={6} style={{ fill: "rgb(var(--c-accent) / 0.12)", stroke: "rgb(var(--c-sev-ok))" }} />
      <text x={318} y={50} fontSize={11} className="fill-sev-ok font-mono">MongoDB ATLAS · nova_rca</text>
      {hot.map((c, i) => (
        <text key={c.name} x={318} y={72 + i * 18} fontSize={9} className="fill-fgdim font-mono">
          {c.name} · {(c.ingestPerSec ?? 0).toFixed(1)}/s
        </text>
      ))}
      <text x={318} y={168} fontSize={8} className="fill-muted font-mono">
        + incidents · memory · kb · checkpoints · store · chat
      </text>

      {/* change streams arrow */}
      <line x1={550} y1={105} x2={660} y2={105} style={{ stroke: "rgb(var(--c-accent))" }} strokeWidth={1.5} />
      <text x={556} y={96} fontSize={8} className="fill-accent font-mono">Change Streams</text>

      {/* agent box */}
      <rect x={660} y={70} width={190} height={70} rx={6} style={{ fill: "rgb(var(--c-panel2))", stroke: hbActive ? "rgb(var(--c-accent))" : "rgb(var(--c-edge2))" }} />
      <circle cx={676} cy={88} r={4} style={{ fill: hbActive ? "rgb(var(--c-sev-ok))" : "rgb(var(--c-muted))" }}
              className={hbActive ? "animate-pulsedot" : undefined} />
      <text x={688} y={92} fontSize={10} className="fill-fg font-mono">RCA agent</text>
      <text x={676} y={110} fontSize={8} className="fill-muted font-mono">watcher · 9-node LangGraph</text>
      <text x={676} y={124} fontSize={8} className="fill-muted font-mono">
        streams: {data.agent.resumeStreams.join(", ") || "—"}
      </text>

      {/* SSE arrow + console */}
      <line x1={850} y1={105} x2={912} y2={105} style={{ stroke: "rgb(var(--c-edge2))" }} strokeWidth={1.5} />
      <text x={858} y={96} fontSize={8} className="fill-muted font-mono">SSE</text>
      <rect x={912} y={82} width={80} height={46} rx={6} style={{ fill: "rgb(var(--c-panel2))", stroke: "rgb(var(--c-edge2))" }} />
      <text x={926} y={102} fontSize={10} className="fill-fg font-mono">Console</text>
      <text x={926} y={116} fontSize={8} className="fill-muted font-mono">this UI</text>
    </svg>
  );
}

// ---------------------------------------------------------------- collections

function CollectionsTable({ collections }: { collections: ArchCollection[] }) {
  return (
    <table className="w-full text-left text-[11px]">
      <thead>
        <tr className="label border-b border-edge">
          <th className="py-1 pr-2">collection</th>
          <th className="py-1 pr-2">role</th>
          <th className="py-1 pr-2 text-right">docs</th>
          <th className="py-1 pr-2 text-right">size</th>
          <th className="py-1 pr-2 text-right">ingest/s</th>
          <th className="py-1 text-right">query ms</th>
        </tr>
      </thead>
      <tbody>
        {collections.map((c) => (
          <tr key={c.name} className="border-b border-edge/40">
            <td className={cx("py-1 pr-2 font-mono", HOT.includes(c.name) ? "text-accent" : "text-fgdim")}>
              {c.name}
            </td>
            <td className="py-1 pr-2 text-muted">{c.role}</td>
            <td className="py-1 pr-2 text-right font-mono text-fgdim">{c.docs === null ? "—" : fmtInt(c.docs)}</td>
            <td className="py-1 pr-2 text-right font-mono text-fgdim">{fmtBytes(c.storageBytes)}</td>
            <td className="py-1 pr-2 text-right font-mono text-fgdim">
              {c.ingestPerSec === null ? "—" : c.ingestPerSec.toFixed(1)}
            </td>
            <td className={cx("py-1 text-right font-mono", {
              ok: "text-sev-ok", warn: "text-sev-warn", crit: "text-sev-crit", idle: "text-muted",
              info: "text-sev-info", biz: "text-sev-warn",
            }[queryMsSev(c.queryMs)])}>
              {c.queryMs === null ? "—" : fmtMs(c.queryMs)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------- correlation

function CorrelationLive({ data }: { data: ArchResponse }) {
  const ex = data.correlationExample;
  if (!ex) {
    return (
      <EmptyState
        title="No joinable trns_id yet"
        hint="Run the simulator; the newest downstream call joined across collections shows here."
        icon="⋈"
      />
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] text-fgdim">
        one transaction id · <span className="font-mono text-accent">{ex.trnsId}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {ex.docs.map((d, i) => (
          <span key={i} className="chip border border-edge text-fgdim" title={String(d.ts)}>
            <span className="font-mono text-accent">{d.collection}</span>
            {" · "}{d.sourceApp}{" · "}
            <span className="font-mono">{d.label}</span>
          </span>
        ))}
      </div>
      <div className="text-[10px] text-muted">
        These documents were written independently by different Java services; the agent joins them
        on <span className="font-mono text-sev-info">trns_id</span> in <span className="font-mono">collect</span>.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- view

export function ArchitectureView({ active }: { active: boolean }) {
  const { data, reachable } = useArchitecture(active);

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          title={reachable ? "Loading architecture…" : "API unreachable"}
          hint="Live topology, ingestion rates and query latencies load from /api/architecture."
          icon="⛁"
        />
      </div>
    );
  }

  const allIdle = data.apps.every((a) => a.ingestPerSec === 0);
  const nowMs = Date.now();

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      <div className="panel p-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-sm font-medium text-fg">Simulated Java applications</span>
          <span className="label">
            {allIdle ? "all idle — start the simulator: make sim" : "live · 60s ingestion window"}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {data.apps.map((a) => (
            <AppCard key={a.id} app={a} nowMs={nowMs} />
          ))}
        </div>
      </div>

      <div className="panel p-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-sm font-medium text-fg">Flow · services → one Atlas DB → agent</span>
          <span className="label">
            last agent run:{" "}
            {data.agent.lastRun
              ? `${data.agent.lastRun.incidentKey} (${fmtMs(data.agent.lastRun.durationMs)})`
              : "—"}
          </span>
        </div>
        <FlowDiagram data={data} nowMs={nowMs} />
      </div>

      <div className="grid min-h-0 grid-cols-1 gap-3 xl:grid-cols-[1.6fr_1fr]">
        <div className="panel p-3">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-sm font-medium text-fg">Collections · one Atlas DB</span>
            <span className="label">query ms = live sampled round-trip</span>
          </div>
          <CollectionsTable collections={data.collections} />
        </div>
        <div className="panel p-3">
          <div className="mb-1.5 text-sm font-medium text-fg">Correlation · live</div>
          <CorrelationLive data={data} />
        </div>
      </div>
    </div>
  );
}
