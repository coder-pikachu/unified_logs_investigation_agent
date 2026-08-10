// Visual explainer for the novasim simulator + journey mesh. Diagram-first,
// low-prose — meant to be read across a room during a live demo. Presentational
// only; grounded in novasim RoutingTable + docs/SCHEMA.md.

function Arrow() {
  return <span className="select-none px-1 text-lg text-muted">→</span>;
}

function Stage({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="label mb-1.5 text-center">{label}</div>
      <div className="panel-2 flex flex-1 flex-col gap-1.5 border border-edge p-2.5">{children}</div>
    </div>
  );
}

function Pill({ children, tone = "fg" }: { children: React.ReactNode; tone?: "fg" | "accent" | "accent2" }) {
  const c = tone === "accent" ? "text-accent" : tone === "accent2" ? "text-accent2" : "text-fgdim";
  return <span className={`rounded bg-panel px-1.5 py-0.5 font-mono text-[10px] ${c}`}>{children}</span>;
}

// collection tiles — the four writes per action
const WRITES: { coll: string; role: string; sev: string; one: string }[] = [
  { coll: "audit_transaction", role: "the user-facing symptom", sev: "bg-sev-info", one: "what the user did" },
  { coll: "audit_service", role: "where the ORIGIN hides", sev: "bg-sev-ok", one: "what a backend did" },
  { coll: "audit_error", role: "the loud decoy", sev: "bg-sev-crit", one: "the error (nested codes)" },
  { coll: "service_metrics", role: "sparklines · p95 baseline", sev: "bg-sev-warn", one: "latency + status, time-series" },
];

const SYSTEMS: { key: string; one: string; routes: string[]; via?: boolean }[] = [
  {
    key: "EIS",
    one: "Gateway every backend sits behind — one bad route hits many journeys.",
    routes: ["eis_iam_authenticate", "eis_marTech_getInteractOffers", "eis_financialfitness_accessToken", "eis_etb_customerprofile_querycustprofile", "eis_cc_branchportal_account_cifAssociatedAccount"],
  },
  {
    key: "UNIPAY",
    one: "Payments — UPI switch + BBPS bill-pay / autopay.",
    routes: ["unipay_upi_payment_transfer", "unipay_payment_billpay_autopay_pendingbills", "unipay_payment_billpay_autopay_query_favouritebillers"],
  },
  { key: "MARTECH", one: "Offers / personalization engine.", routes: ["eis_marTech_getInteractOffers"], via: true },
  { key: "THINK360", one: "PFM data — shared access token; one expiry breaks all PFM.", routes: ["eis_financialfitness_accessToken", "eis_financialfitness_summary"], via: true },
];

export function SystemView() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      {/* stat strip */}
      <div className="panel flex flex-wrap items-center gap-x-4 gap-y-1 p-2.5 text-[11px]">
        <span className="text-sm font-medium text-fg">novasim</span>
        <span className="text-muted">live traffic generator — not a mock</span>
        <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-fgdim">
          <span><span className="text-accent">~5</span> actions/sec</span>
          <span><span className="text-accent">~40</span> sessions</span>
          <span>Java 21 · Log4j2</span>
          <span className="text-accent2">→ one Atlas DB</span>
        </span>
      </div>

      {/* hero pipeline */}
      <div className="panel p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-fg">How one user action becomes logs</span>
          <span className="label">no scenario name is ever written — the agent only sees logs</span>
        </div>
        <div className="flex items-stretch">
          <Stage label="users">
            <div className="text-center">
              <div className="font-mono text-2xl font-bold text-fg">≈40</div>
              <div className="label">sessions</div>
            </div>
          </Stage>
          <Arrow />
          <Stage label="journey · cmnd_id">
            <Pill tone="accent">Login</Pill>
            <Pill tone="accent">Offers</Pill>
            <Pill tone="accent">UPI</Pill>
            <Pill tone="accent">PFM</Pill>
            <Pill tone="accent">BillPay</Pill>
          </Stage>
          <Arrow />
          <Stage label="route · srvc_id → system">
            <div className="rounded border border-edge2 bg-panel px-2 py-1">
              <span className="font-mono text-[11px] font-bold text-fg">EIS</span>
              <span className="ml-1 text-[9px] text-muted">gateway · shared</span>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="chip border border-edge text-fgdim">Martech</span>
                <span className="chip border border-edge text-fgdim">THINK360</span>
              </div>
            </div>
            <div className="rounded border border-edge2 bg-panel px-2 py-1">
              <span className="font-mono text-[11px] font-bold text-fg">UNIPAY</span>
              <span className="ml-1 text-[9px] text-muted">UPI · BBPS</span>
            </div>
          </Stage>
          <Arrow />
          <Stage label="one Atlas DB · nova_rca">
            {WRITES.map((w) => (
              <div key={w.coll} className="flex items-center gap-1.5">
                <span className={`h-2 w-2 shrink-0 rounded-sm ${w.sev}`} />
                <span className="truncate font-mono text-[10px] text-fgdim">{w.coll}</span>
              </div>
            ))}
          </Stage>
        </div>
      </div>

      {/* four writes, expanded */}
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        {WRITES.map((w) => (
          <div key={w.coll} className="panel-2 overflow-hidden border border-edge">
            <div className={`h-1 w-full ${w.sev}`} />
            <div className="p-2.5">
              <div className="mb-0.5 font-mono text-[11px] font-bold text-accent">{w.coll}</div>
              <div className="text-xs text-fg">{w.one}</div>
              <div className="mt-1.5 text-[10px] uppercase tracking-wide text-muted">{w.role}</div>
            </div>
          </div>
        ))}
      </div>

      {/* systems */}
      <div className="panel p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-fg">Systems in the mesh</span>
          <span className="label">all reached through EIS except UNIPAY</span>
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {SYSTEMS.map((s) => (
            <div key={s.key} className="panel-2 flex flex-col gap-1.5 border border-edge p-2.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-fg">{s.key}</span>
                {s.via && <span className="chip border border-edge text-muted">via EIS</span>}
                <span className="ml-auto font-mono text-[10px] text-muted">{s.routes.length} routes</span>
              </div>
              <div className="text-[11px] text-fgdim">{s.one}</div>
              <div className="flex flex-wrap gap-1">
                {s.routes.map((r) => (
                  <span key={r} className="font-mono text-[9px] text-accent2">{r}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* the one idea */}
      <div className="panel p-3">
        <div className="mb-2 text-sm font-medium text-fg">The one idea · origin ≠ loudest error</div>
        <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
          <div className="flex-1 rounded border border-sev-crit/40 bg-sev-crit/5 p-2.5">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-sev-crit" />
              <span className="text-xs font-medium text-fg">LOUD symptom</span>
            </div>
            <div className="mt-1 text-[11px] text-fgdim">50 users see failures · a wall of red in <span className="font-mono text-muted">audit_error</span></div>
          </div>
          <span className="self-center text-lg text-muted">≠</span>
          <div className="flex-1 rounded border border-sev-ok/40 bg-sev-ok/5 p-2.5">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-sev-ok" />
              <span className="text-xs font-medium text-fg">QUIET origin</span>
            </div>
            <div className="mt-1 text-[11px] text-fgdim">one shared route in <span className="font-mono text-muted">audit_service</span> — often a <span className="text-fg">success</span> doc</div>
          </div>
          <div className="flex-1 rounded border border-accent/30 bg-accent/5 p-2.5">
            <div className="text-xs font-medium text-accent">the agent names the quiet one</div>
            <div className="mt-1 text-[11px] text-fgdim">joins 3 collections on <span className="font-mono text-muted">trns_id</span>, orders by time, decodes transport vs business status</div>
          </div>
        </div>
      </div>

      {/* commands */}
      <div className="panel flex flex-wrap items-center gap-x-4 gap-y-1.5 p-2.5 text-[11px]">
        <span className="label">drive it · nova&gt; prompt</span>
        <span><span className="font-mono font-bold text-accent">status</span> <span className="text-muted">throughput</span></span>
        <span><span className="font-mono font-bold text-accent">scenarios</span> <span className="text-muted">list ids</span></span>
        <span><span className="font-mono font-bold text-accent">fire &lt;id&gt;</span> <span className="text-muted">inject effects</span></span>
        <span><span className="font-mono font-bold text-accent">quit</span></span>
        <span className="ml-auto text-muted">fire → <span className="font-mono text-accent2">agent_state</span> — same path as the Ops-board buttons</span>
      </div>
    </div>
  );
}
