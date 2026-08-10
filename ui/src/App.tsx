import { useEffect, useState } from "react";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { SevDot } from "./components/primitives";
import { cx, fmtCost, fmtInt } from "./lib/format";
import { type Severity } from "./lib/meta";
import { useAppStore } from "./store";
import { AgentWorkflow } from "./views/AgentWorkflow";
import { ArchitectureView } from "./views/ArchitectureView";
import { IncidentDetail } from "./views/IncidentDetail";
import { InvestigateView } from "./views/InvestigateView";
import { MemoryView } from "./views/MemoryView";
import { OpsBoard } from "./views/OpsBoard";
import { SystemView } from "./views/SystemView";

type TabKey = "ops" | "system" | "investigate" | "workflow" | "incident" | "architecture" | "memory";

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "ops", label: "OPS BOARD", hint: "journeys · systems · firehose" },
  { key: "system", label: "SYSTEM", hint: "simulator · journeys · logs" },
  { key: "investigate", label: "INVESTIGATE", hint: "chat · screenshot → RCA" },
  { key: "workflow", label: "AGENT WORKFLOW", hint: "9-node DAG · live" },
  { key: "incident", label: "INCIDENT DETAIL", hint: "timeline · RCA · fixes" },
  { key: "architecture", label: "ARCHITECTURE", hint: "apps · collections · rates" },
  { key: "memory", label: "MEMORY", hint: "recall · playbooks" },
];

function boolish(v: unknown): boolean {
  return v === true || v === "ok" || v === "up" || v === "connected" || v === "healthy";
}

function ConnPill({ label, sev, text }: { label: string; sev: Severity; text: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <SevDot sev={sev} pulse={sev === "warn"} />
      <span className="label">{label}</span>
      <span className="kpi text-[11px] text-fgdim">{text}</span>
    </div>
  );
}

export default function App() {
  const store = useAppStore();
  const [tab, setTab] = useState<TabKey>("ops");
  const [incidentKey, setIncidentKey] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("nova-theme") as "dark" | "light") || "dark",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("nova-theme", theme);
  }, [theme]);

  const openIncident = (key: string) => {
    setIncidentKey(key);
    setTab("incident");
  };

  const connSev: Severity = store.conn === "open" ? "ok" : store.conn === "connecting" ? "warn" : "crit";
  const connText = store.conn === "open" ? "stream live" : store.conn === "connecting" ? "reconnecting…" : "stream down";
  const mongoSev: Severity = store.health ? (boolish(store.health.mongo) ? "ok" : "crit") : "idle";
  const groveSev: Severity = store.health ? (boolish(store.health.grove) ? "ok" : "crit") : "idle";

  return (
    <div className="flex h-full flex-col bg-ink text-fg">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-edge bg-panel px-4 py-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-bold tracking-tight text-accent">NOVA·RCA</span>
            <span className="label hidden sm:block">unified-platform ops console</span>
          </div>
          <nav className="flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                title={t.hint}
                className={cx(
                  "rounded px-2.5 py-1 font-mono text-[11px] tracking-wide transition-colors",
                  tab === t.key
                    ? "bg-accent2/20 text-accent ring-1 ring-accent2/50"
                    : "text-muted hover:bg-panel2 hover:text-fgdim",
                )}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <ConnPill label="sse" sev={connSev} text={connText} />
          <ConnPill label="mongo" sev={mongoSev} text={store.health ? (boolish(store.health.mongo) ? "up" : "down") : "—"} />
          <ConnPill label="grove" sev={groveSev} text={store.health ? (boolish(store.health.grove) ? "up" : "down") : "—"} />
          <div className="hidden items-center gap-1.5 md:flex">
            <span className="label">tok</span>
            <span className="kpi text-[11px] text-accent">{fmtInt(store.tokens.tokens)}</span>
            <span className="kpi text-[11px] text-sev-ok">{fmtCost(store.tokens.cost)}</span>
          </div>
          <button
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            title={`switch to ${theme === "dark" ? "light" : "dark"} mode`}
            className="rounded border border-edge2 px-2 py-1 font-mono text-[11px] text-fgdim transition-colors hover:border-accent hover:text-fg"
          >
            {theme === "dark" ? "☀ light" : "☾ dark"}
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        <ErrorBoundary resetKey={tab}>
          {tab === "ops" && <OpsBoard store={store} active onOpenIncident={openIncident} />}
          {tab === "system" && <SystemView />}
          {tab === "investigate" && <InvestigateView store={store} onOpenIncident={openIncident} />}
          {tab === "workflow" && <AgentWorkflow store={store} />}
          {tab === "incident" && (
            <IncidentDetail store={store} selectedKey={incidentKey} onSelectKey={setIncidentKey} />
          )}
          {tab === "architecture" && <ArchitectureView active={tab === "architecture"} />}
          {tab === "memory" && <MemoryView store={store} active />}
        </ErrorBoundary>
      </main>
    </div>
  );
}
