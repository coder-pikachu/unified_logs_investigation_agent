import { useMemo, useState } from "react";

import { Chip, EmptyState, JsonBlock } from "../components/primitives";
import { useIncidentDoc } from "../hooks";
import { cx, fmtCost, fmtInt, fmtMs, truncate } from "../lib/format";
import {
  NODES,
  NODE_BY_KEY,
  NODE_ORDER,
  PIPELINE_NODES,
  SEV_HEX,
  type NodeMeta,
} from "../lib/meta";
import type { AppStore, NodeRuntime } from "../store";
import type { Incident, NodeTraceEntry, RecallArms } from "../types";

// ---- fixed DAG geometry (contract §4: 9 nodes, verify->collect back-edge) ----
const NX = 40;
const GAP = 140;
const NW = 116;
const NH = 62;
const NY = 150;
const VBW = NX + NODES.length * GAP;
const VBH = 320;

function nodeX(i: number): number {
  return NX + i * GAP;
}

const STATE_COLOR: Record<NodeRuntime["state"], string> = {
  pending: "#2a3644",
  running: SEV_HEX.warn,
  done: SEV_HEX.ok,
  skipped: "#4a5a6e",
};

function GraphNode({
  meta,
  index,
  rt,
  selected,
  onSelect,
}: {
  meta: NodeMeta;
  index: number;
  rt: NodeRuntime;
  selected: boolean;
  onSelect: (k: string) => void;
}) {
  const x = nodeX(index);
  const color = STATE_COLOR[rt.state];
  const badge = rt.badge ?? meta.badge;
  return (
    <g className="cursor-pointer" onClick={() => onSelect(meta.key)}>
      <rect
        x={x}
        y={NY}
        width={NW}
        height={NH}
        rx={7}
        fill={selected ? "#182230" : "#131a25"}
        stroke={selected ? SEV_HEX.info : color}
        strokeWidth={selected ? 2.2 : 1.4}
        strokeDasharray={rt.state === "skipped" ? "4 3" : undefined}
      />
      <circle
        cx={x + 12}
        cy={NY + 13}
        r={3.5}
        fill={color}
        className={rt.state === "running" ? "animate-pulsedot" : undefined}
      />
      <text x={x + 22} y={NY + 17} fontSize={12} className="fill-fg font-mono" fontWeight={600}>
        {meta.label}
      </text>
      <text x={x + 10} y={NY + 36} fontSize={7.5} className="fill-accent font-mono">
        {truncate(badge, 22)}
      </text>
      <text x={x + 10} y={NY + 52} fontSize={8} className="fill-muted font-mono">
        {rt.state}
      </text>
      <text x={x + NW - 8} y={NY + 52} fontSize={8} textAnchor="end" className="fill-fgdim font-mono">
        {rt.state === "done" || rt.ms ? fmtMs(rt.ms) : ""}
      </text>
    </g>
  );
}

function Dag({
  nodes,
  backEdgeAt,
  selected,
  onSelect,
}: {
  nodes: Record<string, NodeRuntime>;
  backEdgeAt: number;
  selected: string | null;
  onSelect: (k: string) => void;
}) {
  const reached = (k: string) => {
    const s = nodes[k]?.state;
    return s === "running" || s === "done";
  };

  // back-edge arc: verify(5) top -> collect(1) top
  const cxV = nodeX(5) + NW / 2;
  const cxC = nodeX(1) + NW / 2;
  const backPath = `M${cxV},${NY} C${cxV},50 ${cxC},50 ${cxC},${NY}`;

  return (
    <svg viewBox={`0 0 ${VBW} ${VBH}`} className="h-full w-full min-w-[1180px]" role="img" aria-label="agent workflow graph">
      <defs>
        <marker id="arw" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#3a475a" />
        </marker>
        <marker id="arwA" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={SEV_HEX.ok} />
        </marker>
        <marker id="arwL" markerWidth="9" markerHeight="9" refX="4" refY="7" orient="auto">
          <path d="M0,0 L8,0 L4,7 Z" fill={SEV_HEX.warn} />
        </marker>
      </defs>

      {/* forward edges */}
      {NODE_ORDER.slice(0, -1).map((k, i) => {
        const active = reached(NODE_ORDER[i + 1]);
        const x1 = nodeX(i) + NW;
        const x2 = nodeX(i + 1);
        const running = nodes[NODE_ORDER[i + 1]]?.state === "running";
        return (
          <line
            key={k}
            x1={x1}
            y1={NY + NH / 2}
            x2={x2 - 2}
            y2={NY + NH / 2}
            stroke={active ? SEV_HEX.ok : "#3a475a"}
            strokeWidth={active ? 1.8 : 1.2}
            strokeDasharray={running ? "4 3" : undefined}
            className={running ? "animate-flow" : undefined}
            markerEnd={active ? "url(#arwA)" : "url(#arw)"}
          />
        );
      })}

      {/* verify -> collect back-edge */}
      <path d={backPath} fill="none" stroke="#3a475a" strokeWidth={1.2} strokeDasharray="3 4" markerEnd="url(#arwL)" />
      {backEdgeAt > 0 && (
        <path
          key={backEdgeAt}
          d={backPath}
          fill="none"
          strokeWidth={2}
          className="animate-looppulse"
          markerEnd="url(#arwL)"
        />
      )}
      <text x={(cxV + cxC) / 2} y={42} textAnchor="middle" fontSize={9} className="fill-sev-warn font-mono">
        verify → collect · loop once
      </text>

      {NODES.map((m, i) => (
        <GraphNode
          key={m.key}
          meta={m}
          index={i}
          rt={nodes[m.key] ?? { key: m.key, state: "pending" }}
          selected={selected === m.key}
          onSelect={onSelect}
        />
      ))}
    </svg>
  );
}

function TokenMeter({ tokens }: { tokens: AppStore["tokens"] }) {
  return (
    <div className="flex items-center gap-4">
      <div className="text-right">
        <div className="kpi text-sm text-accent">{fmtInt(tokens.tokens)}</div>
        <div className="label">tokens</div>
      </div>
      <div className="text-right">
        <div className="kpi text-sm text-sev-ok">{fmtCost(tokens.cost)}</div>
        <div className="label">cost</div>
      </div>
      <div className="text-right">
        <div className="kpi text-sm text-fg">{fmtInt(tokens.calls)}</div>
        <div className="label">llm calls</div>
      </div>
    </div>
  );
}

function traceFor(inc: Incident | null, node: string): NodeTraceEntry | null {
  if (!inc?.nodeTrace) return null;
  const matches = inc.nodeTrace.filter((t) => t.node === node);
  return matches.length ? matches[matches.length - 1] : null;
}

function pipelineOf(entry: NodeTraceEntry | null): unknown {
  if (!entry) return undefined;
  const p = entry.payload as Record<string, unknown> | undefined;
  const o = entry.output as Record<string, unknown> | undefined;
  return entry.pipeline ?? p?.pipeline ?? o?.pipeline;
}

function NodeInspector({
  node,
  rt,
  inc,
}: {
  node: string;
  rt: NodeRuntime | undefined;
  inc: Incident | null;
}) {
  const meta = NODE_BY_KEY[node];
  const entry = traceFor(inc, node);
  const pipeline = pipelineOf(entry);
  const showPipeline = PIPELINE_NODES.has(node);
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-base text-fg">{meta?.label ?? node}</span>
          <Chip sev={rt?.state === "done" ? "ok" : rt?.state === "running" ? "warn" : "idle"}>
            {rt?.state ?? "pending"}
          </Chip>
          {rt?.ms ? <span className="kpi text-xs text-fgdim">{fmtMs(rt.ms)}</span> : null}
        </div>
        <div className="mt-1 text-xs text-fgdim">{meta?.desc}</div>
        <div className="mt-1.5">
          <span className="label">capability</span>
          <div className="mt-0.5 rounded border border-accent2/40 bg-accent2/10 px-2 py-1 font-mono text-[11px] text-accent">
            {rt?.badge ?? meta?.badge}
          </div>
        </div>
      </div>

      {rt?.summary && (
        <div>
          <span className="label">live summary</span>
          <div className="mt-0.5 text-xs text-fgdim">{rt.summary}</div>
        </div>
      )}

      {showPipeline && (
        <div>
          <span className="label">literal aggregation pipeline</span>
          {pipeline !== undefined ? (
            <div className="mt-0.5">
              <JsonBlock value={pipeline} maxH={260} />
            </div>
          ) : (
            <div className="mt-0.5 rounded border border-dashed border-edge2 p-2 text-[11px] text-muted">
              Pipeline appears here from the incident nodeTrace once <span className="text-accent">{node}</span> has run.
            </div>
          )}
        </div>
      )}

      {entry?.input !== undefined && (
        <div>
          <span className="label">input</span>
          <div className="mt-0.5">
            <JsonBlock value={entry.input} maxH={180} />
          </div>
        </div>
      )}
      {entry?.output !== undefined && (
        <div>
          <span className="label">output</span>
          <div className="mt-0.5">
            <JsonBlock value={entry.output} maxH={180} />
          </div>
        </div>
      )}
      {!entry && !rt?.summary && (
        <div className="rounded border border-dashed border-edge2 p-2 text-[11px] text-muted">
          No trace yet for this node. It fills in live from SSE and from the persisted incident nodeTrace.
        </div>
      )}
    </div>
  );
}

function armsOf(inc: Incident | null): RecallArms | null {
  const entry = traceFor(inc, "recall");
  if (entry?.arms) return entry.arms;
  const p = entry?.payload as Record<string, unknown> | undefined;
  if (p?.arms) return p.arms as RecallArms;
  return null;
}

function SimilarIncidents({ inc }: { inc: Incident | null }) {
  const arms = armsOf(inc);
  const fused: { incidentKey?: string; title?: string; score: number }[] =
    arms?.fused ?? inc?.recalledIncidents?.map((r) => ({ incidentKey: r.incidentKey, score: r.score })) ?? [];
  const hasAny = (arms?.search?.length || arms?.vector?.length || fused?.length || inc?.recalledKb?.length) ?? 0;

  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="border-b border-edge px-3 py-2">
        <div className="text-sm font-medium text-fg">Similar past incidents</div>
        <div className="label mt-0.5">$rankFusion · Atlas Search + Vector (autoEmbed)</div>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {!hasAny ? (
          <EmptyState title="No recall yet" hint="Runs at the recall node; both arms + fused ranking show here." icon="⋔" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              <ArmList title="lexical arm" tint="info" items={arms?.search} />
              <ArmList title="vector arm" tint="biz" items={arms?.vector} minScore={arms?.minVectorScore} />
            </div>
            <div>
              <div className="label mb-1">fused ranking</div>
              <div className="space-y-1">
                {(fused ?? []).map((f, i) => (
                  <div key={`${f.incidentKey ?? f.title ?? i}`} className="panel-2 flex items-center justify-between border border-edge px-2 py-1">
                    <span className="font-mono text-[11px] text-fg">
                      <span className="text-muted">#{i + 1}</span> {truncate(String(f.incidentKey ?? f.title ?? ""), 30)}
                    </span>
                    <span className="kpi text-[11px] text-accent">{Number(f.score ?? 0).toFixed(3)}</span>
                  </div>
                ))}
              </div>
            </div>
            {inc?.recalledKb?.length ? (
              <div>
                <div className="label mb-1">knowledge base</div>
                <div className="space-y-1">
                  {inc.recalledKb.map((k, i) => (
                    <div key={`${k.title}-${i}`} className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-fgdim">{truncate(k.title, 34)}</span>
                      <span className="kpi text-muted">{Number(k.score).toFixed(3)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function ArmList({
  title,
  tint,
  items,
  minScore,
}: {
  title: string;
  tint: "info" | "biz";
  items?: { incidentKey?: string; title?: string; score: number }[];
  minScore?: number;
}) {
  return (
    <div className="panel-2 border border-edge p-1.5">
      <div className={cx("label mb-1", tint === "info" ? "text-sev-info" : "text-sev-biz")}>
        {title}
        {minScore !== undefined ? ` · ≥${minScore}` : ""}
      </div>
      {!items?.length ? (
        <div className="text-[10px] text-muted">—</div>
      ) : (
        items.slice(0, 5).map((it, i) => (
          <div key={i} className="flex items-center justify-between font-mono text-[10px]">
            <span className="truncate text-fgdim">{truncate(String(it.incidentKey ?? it.title ?? ""), 20)}</span>
            <span className="kpi text-muted">{Number(it.score).toFixed(2)}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function AgentWorkflow({ store }: { store: AppStore }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [pickKey, setPickKey] = useState<string | null>(null);
  const key = pickKey ?? store.runIncidentKey ?? store.incidents[0]?.incidentKey ?? null;
  const inc = useIncidentDoc(key);

  const totalMs = useMemo(
    () => Object.values(store.nodes).reduce((a, n) => a + (n.state === "done" ? n.ms ?? 0 : 0), 0),
    [store.nodes],
  );
  const running = NODE_ORDER.find((k) => store.nodes[k]?.state === "running");
  const doneCount = NODE_ORDER.filter((k) => store.nodes[k]?.state === "done").length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="panel flex flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-3 py-2">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-fg">Agent workflow</span>
            <span className="kpi text-xs text-fgdim">
              {doneCount}/{NODE_ORDER.length} nodes · {fmtMs(totalMs)}
              {running ? (
                <span className="text-sev-warn"> · running {running}</span>
              ) : (
                <span className="text-sev-ok"> · idle</span>
              )}
            </span>
            <select
              value={key ?? ""}
              onChange={(e) => setPickKey(e.target.value || null)}
              className="rounded border border-edge bg-ink px-1.5 py-0.5 font-mono text-[11px] text-fgdim outline-none focus:border-accent"
            >
              <option value="">{store.runIncidentKey ? `live · ${truncate(store.runIncidentKey, 20)}` : "— pick incident —"}</option>
              {store.incidents.map((i) => (
                <option key={i.incidentKey} value={i.incidentKey}>
                  {truncate(i.incidentKey, 28)}
                </option>
              ))}
            </select>
          </div>
          <TokenMeter tokens={store.tokens} />
        </div>
        <div className="overflow-x-auto p-2" style={{ height: 260 }}>
          <Dag nodes={store.nodes} backEdgeAt={store.backEdgeAt} selected={selected} onSelect={setSelected} />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[1.4fr_1fr]">
        <div className="panel flex min-h-0 flex-col">
          <div className="flex items-center justify-between border-b border-edge px-3 py-2">
            <span className="text-sm font-medium text-fg">
              {selected ? `Inspector · ${selected}` : "Inspector"}
            </span>
            {selected && (
              <button className="btn !py-0.5 text-[10px]" onClick={() => setSelected(null)}>
                clear
              </button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-3">
            {selected ? (
              <NodeInspector node={selected} rt={store.nodes[selected]} inc={inc.data} />
            ) : (
              <EmptyState
                title="Click a node to inspect it"
                hint="recall + verify show their literal aggregation pipeline from the incident nodeTrace."
                icon="◉"
              />
            )}
          </div>
        </div>
        <SimilarIncidents inc={inc.data} />
      </div>
    </div>
  );
}
