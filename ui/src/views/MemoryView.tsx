import { Chip, EmptyState } from "../components/primitives";
import { useIncidentDoc, useMemory } from "../hooks";
import { fmtDateTime, fmtInt, pct, truncate } from "../lib/format";
import type { AppStore } from "../store";
import type { Playbook } from "../types";

interface PlaybookView {
  title: string;
  seenCount?: number;
  confidence?: number;
  confirmedFixes: string[];
  extra?: string;
}

// The `store` collection is a generic langgraph KV; read a playbook defensively
// from either top-level fields or a nested `value` object.
function readPlaybook(p: Playbook): PlaybookView {
  const v = (p.value ?? {}) as Record<string, unknown>;
  const num = (a: unknown, b: unknown) =>
    typeof a === "number" ? a : typeof b === "number" ? b : undefined;
  const fixes = (p.confirmedFixes ?? (v.confirmedFixes as string[])) ?? [];
  return {
    title: String(p.route ?? p.key ?? v.route ?? p._id ?? "playbook"),
    seenCount: num(p.seenCount, v.seenCount),
    confidence: num(p.confidence, v.confidence),
    confirmedFixes: Array.isArray(fixes) ? fixes.map(String) : [],
    extra: typeof v.rootCause === "string" ? v.rootCause : undefined,
  };
}

export function MemoryView({ store, active }: { store: AppStore; active: boolean }) {
  const mem = useMemory(active);
  const currentKey = store.runIncidentKey ?? store.incidents[0]?.incidentKey ?? null;
  const inc = useIncidentDoc(active ? currentKey : null);

  const memories = mem.data?.incidents ?? [];
  const playbooks = (mem.data?.playbooks ?? []).map(readPlaybook);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-fg">Native memory · MongoDB is the memory tier</div>
          <div className="label mt-0.5">Automated Embedding (voyage-4-lite) — no embedding client in /agent</div>
        </div>
        <button className="btn !py-0.5 text-[10px]" onClick={mem.reload}>
          refresh
        </button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-3">
        {/* incident memories */}
        <div className="panel flex min-h-0 flex-col">
          <div className="border-b border-edge px-3 py-2 text-sm font-medium text-fg">
            Incident memories
            <span className="label ml-2">{fmtInt(memories.length)}</span>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
            {!mem.reachable ? (
              <EmptyState title="API unreachable" hint="incident_memory loads once the agent API is up." icon="⚠" />
            ) : memories.length === 0 ? (
              <EmptyState title="No memories yet" hint="Each analyzed incident writes a summary + auto-embedding here." icon="✷" />
            ) : (
              memories.map((m, i) => (
                <div key={`${m.incidentKey}-${i}`} className="panel-2 border border-edge p-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] text-fg">{truncate(m.incidentKey, 26)}</span>
                    <span className="label">{fmtDateTime(m.createdAt)}</span>
                  </div>
                  {m.summary_text && <div className="mt-1 text-xs text-fgdim">{m.summary_text}</div>}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(m.journeys ?? []).slice(0, 4).map((j) => (
                      <span key={j} className="chip border border-edge text-muted">{j}</span>
                    ))}
                    {(m.err_cds ?? []).slice(0, 4).map((e) => (
                      <span key={e} className="chip border border-sev-crit/40 text-sev-crit">{e}</span>
                    ))}
                  </div>
                  {m.sourceIncidentKey && (
                    <div className="mt-1 text-[10px] text-muted">from {truncate(m.sourceIncidentKey, 24)}</div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* playbooks */}
        <div className="panel flex min-h-0 flex-col">
          <div className="border-b border-edge px-3 py-2 text-sm font-medium text-fg">
            Route playbooks
            <span className="label ml-2">store · {fmtInt(playbooks.length)}</span>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
            {playbooks.length === 0 ? (
              <EmptyState title="No playbooks yet" hint="Confirmed fixes accrue per route with seenCount + confidence." icon="❏" />
            ) : (
              playbooks.map((p, i) => (
                <div key={`${p.title}-${i}`} className="panel-2 border border-edge p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-fg">{truncate(p.title, 30)}</span>
                    <div className="flex items-center gap-1">
                      {p.seenCount !== undefined && (
                        <span className="chip border border-edge text-fgdim">seen {p.seenCount}</span>
                      )}
                      {p.confidence !== undefined && (
                        <Chip sev={p.confidence > 0.66 ? "ok" : p.confidence > 0.33 ? "warn" : "crit"}>
                          {pct(p.confidence)}
                        </Chip>
                      )}
                    </div>
                  </div>
                  {p.extra && <div className="mt-1 text-[11px] text-fgdim">{truncate(p.extra, 120)}</div>}
                  {p.confirmedFixes.length > 0 && (
                    <ul className="mt-1 list-inside list-disc text-[11px] text-sev-ok/90">
                      {p.confirmedFixes.slice(0, 4).map((f, j) => (
                        <li key={j}>{truncate(f, 80)}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* recall impact on current analysis */}
        <div className="panel flex min-h-0 flex-col">
          <div className="border-b border-edge px-3 py-2 text-sm font-medium text-fg">
            How recall shaped this analysis
            {currentKey && <span className="label ml-2">{truncate(currentKey, 18)}</span>}
          </div>
          <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
            {!inc.data ? (
              <EmptyState title="No current analysis" hint="Open or run an incident to see what recall pulled in." icon="⋔" />
            ) : (
              <>
                {inc.data.recalledIncidents?.length ? (
                  <div>
                    <div className="label mb-1">recalled incidents (fused)</div>
                    <div className="space-y-1">
                      {inc.data.recalledIncidents.map((r, i) => (
                        <div key={`${r.incidentKey}-${i}`} className="flex items-center justify-between font-mono text-[11px]">
                          <span className="text-fgdim">{truncate(r.incidentKey, 26)}</span>
                          <span className="kpi text-accent">{Number(r.score).toFixed(3)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-muted">recall found no prior incidents for this one.</div>
                )}
                {inc.data.recalledKb?.length ? (
                  <div>
                    <div className="label mb-1">recalled KB</div>
                    <div className="space-y-1">
                      {inc.data.recalledKb.map((k, i) => (
                        <div key={`${k.title}-${i}`} className="flex items-center justify-between font-mono text-[11px]">
                          <span className="text-fgdim">{truncate(k.title, 26)}</span>
                          <span className="kpi text-muted">{Number(k.score).toFixed(3)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div className="rounded border border-edge2/60 bg-panel2 p-2 text-[11px] text-fgdim">
                  {inc.data.recalledIncidents?.length
                    ? "Prior incidents + KB above were fused via $rankFusion and fed to hypothesize/rca as prior evidence — sharpening confidence and shrinking unknowns."
                    : "This was analyzed without prior matches; its memory becomes prior evidence for the next similar incident."}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
