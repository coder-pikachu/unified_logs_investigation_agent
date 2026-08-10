import { Chip } from "../components/primitives";

// Static explainer: what the novasim simulator is, what the logs are, and what
// each system in the NOVA 2.0 journey mesh does. Presentational only — no
// backend. Grounded in novasim RoutingTable + docs/SCHEMA.md; nothing here is
// written to any document (the agent never sees scenario names or this map).

interface SystemRow {
  key: string;
  label: string;
  what: string;
  routes: string[];
  journeys: string;
  viaEis: boolean;
}

const SYSTEMS: SystemRow[] = [
  {
    key: "EIS",
    label: "EIS",
    what: "The enterprise integration gateway every backend sits behind. Shared — so one failing route fans out across unrelated journeys.",
    routes: [
      "eis_iam_authenticate",
      "eis_marTech_getInteractOffers",
      "eis_financialfitness_accessToken",
      "eis_etb_customerprofile_querycustprofile",
      "eis_cc_branchportal_account_cifAssociatedAccount",
    ],
    journeys: "login · offers · PFM (kyc/consent/summary) · profile · cards",
    viaEis: false,
  },
  {
    key: "UNIPAY",
    label: "UNIPAY",
    what: "Payments platform — UPI switch and BBPS bill-pay / autopay. Note the authentic leading space in systm_nm: ' UNIPAY'.",
    routes: [
      "unipay_upi_payment_transfer",
      "unipay_payment_billpay_autopay_pendingbills",
      "unipay_payment_billpay_autopay_query_favouritebillers",
      "unipay_payment_billpay_autopay_get_active_activebillshistory",
    ],
    journeys: "UPI send-money · billpay autopay / favourites",
    viaEis: false,
  },
  {
    key: "MARTECH",
    label: "MARTECH",
    what: "Hyper-personalization / offers engine, reached through the shared EIS thirdParty/wrapper/Martech route.",
    routes: ["eis_marTech_getInteractOffers"],
    journeys: "offers fetch",
    viaEis: true,
  },
  {
    key: "THINK360",
    label: "THINK360",
    what: "Financial-fitness / PFM data provider, reached via EIS on a shared access-token route — one expired credential breaks every PFM journey at once.",
    routes: ["eis_financialfitness_accessToken", "eis_financialfitness_summary"],
    journeys: "PFM kyc / consent / summary",
    viaEis: true,
  },
];

interface DocRow {
  coll: string;
  one: string;
  is: string;
  fields: string;
  role: string;
}

const DOCS: DocRow[] = [
  {
    coll: "audit_transaction",
    one: "one per journey action",
    is: "what the user did",
    fields: "cmnd_id · channel · trns_stts · biz_req/resp",
    role: "the user-facing symptom",
  },
  {
    coll: "audit_service",
    one: "one per downstream call",
    is: "what a backend did",
    fields: "srvc_id · systm_nm · trns_sts · srvc_rqst/rspn",
    role: "where the ORIGIN usually hides",
  },
  {
    coll: "audit_error",
    one: "only on failure",
    is: "the error, with nested code chain",
    fields: "err_cd (BS*/TE*/5151) · err_typ · err_dtls",
    role: "the loud decoy",
  },
  {
    coll: "service_metrics",
    one: "one time-series point per call",
    is: "latency + status, per route",
    fields: "ts · durationMs · transportOk · businessOk",
    role: "sparklines + agent p95 baseline",
  },
];

const CMDS: { cmd: string; does: string }[] = [
  { cmd: "status", does: "throughput + open scenarios" },
  { cmd: "scenarios", does: "list injectable scenario ids" },
  { cmd: "fire <id>", does: "inject a scenario's effects into live traffic" },
  { cmd: "quit", does: "stop the simulator" },
];

function Section({ title, right, children }: { title: string; right?: string; children: React.ReactNode }) {
  return (
    <div className="panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-fg">{title}</span>
        {right && <span className="label">{right}</span>}
      </div>
      {children}
    </div>
  );
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[11px] text-accent">{children}</span>;
}

export function SystemView() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      {/* what the simulator is */}
      <Section title="The simulator — novasim" right="Java 21 · Log4j2 → one Atlas DB">
        <p className="text-xs leading-relaxed text-fgdim">
          <span className="text-fg">novasim</span> continuously plays the NOVA 2.0 banking super-app the
          way real users would — <Mono>~5 journey-actions/sec</Mono> across a pool of{" "}
          <Mono>~40 sessions</Mono>. It is a live traffic generator, not a mock: each action mints a
          fresh <Mono>trns_id</Mono>, walks a real journey → downstream route path, and writes
          documents in the exact production shapes through a custom Log4j2 Mongo appender. Firing a
          scenario injects <span className="text-fg">effects</span> (extra latency, an error rate, a
          business-failure ratio) into that live traffic — failures are woven into genuine noise.{" "}
          <span className="text-fg">No scenario name is ever written to the data</span>; the agent
          only ever sees the resulting logs.
        </p>
      </Section>

      {/* the flow */}
      <Section title="One user action → up to four writes" right="all share one trns_id">
        <div className="mb-3 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-fgdim">
          <span className="rounded bg-panel2 px-2 py-1 text-fg">session (user)</span>
          <span className="text-muted">→</span>
          <span className="rounded bg-panel2 px-2 py-1 text-accent">journey · cmnd_id</span>
          <span className="text-muted">→</span>
          <span className="rounded bg-panel2 px-2 py-1 text-accent2">downstream route · srvc_id</span>
          <span className="text-muted">→</span>
          <span className="rounded bg-panel2 px-2 py-1 text-fg">system (EIS / UNIPAY)</span>
          <span className="text-muted">→</span>
          <span className="rounded border border-edge px-2 py-1">Atlas collections</span>
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {DOCS.map((d) => (
            <div key={d.coll} className="panel-2 border border-edge p-2.5">
              <div className="mb-1 font-mono text-[11px] font-bold text-accent">{d.coll}</div>
              <div className="label mb-1">{d.one}</div>
              <div className="mb-1.5 text-xs text-fg">{d.is}</div>
              <div className="mb-1.5 font-mono text-[10px] leading-relaxed text-muted">{d.fields}</div>
              <div className="text-[10px] uppercase tracking-wide text-fgdim">{d.role}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* systems */}
      <Section title="The systems in the mesh" right="all reached through EIS except UNIPAY">
        <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
          {SYSTEMS.map((s) => (
            <div key={s.key} className="panel-2 border border-edge p-2.5">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-fg">{s.label}</span>
                {s.viaEis && <Chip title="reached through the EIS gateway">via EIS</Chip>}
              </div>
              <p className="mb-2 text-xs leading-relaxed text-fgdim">{s.what}</p>
              <div className="label mb-1">routes · srvc_id</div>
              <div className="mb-2 flex flex-wrap gap-1">
                {s.routes.map((r) => (
                  <span key={r} className="font-mono text-[10px] text-accent2">
                    {r}
                  </span>
                ))}
              </div>
              <div className="label mb-0.5">journeys that depend on it</div>
              <div className="text-[11px] text-muted">{s.journeys}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* journeys vs routes vs ops + the big idea */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Journeys · routes · ops jobs">
          <ul className="space-y-2 text-xs leading-relaxed text-fgdim">
            <li>
              <span className="text-fg">Journey</span> (<Mono>cmnd_id</Mono>, shaped{" "}
              <span className="font-mono text-[11px] text-muted">domain_module_feature_action</span>) —
              what the user did, e.g.{" "}
              <span className="font-mono text-[11px] text-muted">martech_hyper-personalization_offers_fetch</span>.
            </li>
            <li>
              <span className="text-fg">Route</span> (<Mono>srvc_id</Mono>) — the shared downstream
              endpoint a journey called. Many journeys share one route — which is exactly why the loud
              symptom and the quiet origin live in <span className="text-fg">different collections</span>.
            </li>
            <li>
              <span className="text-fg">Ops jobs</span> —{" "}
              <span className="font-mono text-[11px] text-muted">ops_martech_audience_refresh_execute</span>,{" "}
              <span className="font-mono text-[11px] text-muted">ops_eis_config_deploy_execute</span>:
              background maintenance that succeeds silently. In <Mono>martech-cif-desync</Mono> a{" "}
              <span className="text-fg">successful</span> ops job is the root cause of the failures
              that follow it.
            </li>
          </ul>
        </Section>

        <Section title="The one idea: origin ≠ loudest error">
          <p className="text-xs leading-relaxed text-fgdim">
            Every scenario is built so the error that screams loudest is never the root cause. Fifty
            users see login failures — but one shared IAM route is the origin. A dashboard fills with
            business errors — but a successful upstream ops job caused them. The agent joins the three
            audit collections on <Mono>trns_id</Mono> / <Mono>sessn_tkn_id</Mono>, orders by time,
            decodes transport-vs-business status, and names an{" "}
            <span className="text-fg">ORIGIN distinct from the symptoms</span>. A single-log grep can
            never do this.
          </p>
        </Section>
      </div>

      {/* commands */}
      <Section title="Driving the simulator" right="nova> prompt (make sim)">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {CMDS.map((c) => (
            <div key={c.cmd} className="panel-2 flex items-center gap-2 border border-edge p-2">
              <span className="font-mono text-[11px] font-bold text-accent">{c.cmd}</span>
              <span className="text-[11px] text-muted">{c.does}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-muted">
          <span className="text-fgdim">fire</span> writes a command into the{" "}
          <span className="font-mono text-accent2">agent_state</span> collection; the running simulator
          polls it — so the Ops-board fire buttons and the CLI drive the exact same path.
        </p>
      </Section>
    </div>
  );
}
