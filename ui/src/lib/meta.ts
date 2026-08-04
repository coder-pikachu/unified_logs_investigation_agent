// Domain maps derived from contract §2 (journeys/routing), §4 (nodes/badges),
// §6/§7 (scenarios). Kept UI-side only; nothing here is written to any doc.

export type Severity = "ok" | "warn" | "crit" | "info" | "biz" | "idle";

export interface JourneyMeta {
  key: string;
  label: string;
  service: string; // GET /api/metrics?service=
  hint: string;
}

// OPS-board journey tiles (headline journeys first).
export const JOURNEYS: JourneyMeta[] = [
  { key: "login", label: "Login", service: "auth_login", hint: "user authentication (IAM)" },
  { key: "upi", label: "UPI", service: "upi_payment", hint: "send money (UPI switch)" },
  { key: "dashboard", label: "Dashboard", service: "home_dashboard", hint: "notifications · cards · summary" },
  { key: "billpay", label: "BillPay", service: "billpay_autopay", hint: "autopay · pending · favourites" },
  { key: "pfm", label: "PFM", service: "pfm_financial-fitness", hint: "kyc · consent · summary" },
  { key: "lending", label: "Lending", service: "lending_demand", hint: "demand-loan-closure" },
  { key: "offers", label: "Offers", service: "martech_hyper-personalization", hint: "interact offers fetch" },
  { key: "insurance", label: "Insurance", service: "gi_gsa_purchase", hint: "validate checks (web)" },
  { key: "loan", label: "Loan", service: "loan_personal_papl", hint: "eligible loan details" },
];

export interface SystemMeta {
  key: string;
  label: string;
  service: string;
  hint: string;
}

// Downstream-system tiles.
export const SYSTEMS: SystemMeta[] = [
  { key: "EIS", label: "EIS", service: "EIS", hint: "enterprise integration svc" },
  { key: "UNIPAY", label: "UNIPAY", service: "UNIPAY", hint: "billpay / BBPS gateway" },
  { key: "MARTECH", label: "MARTECH", service: "MARTECH", hint: "interact offers (via EIS)" },
  { key: "THINK360", label: "THINK360", service: "THINK360", hint: "credit data · tokened" },
];

export interface NodeMeta {
  key: string;
  label: string;
  badge: string; // default badge (contract §4); runtime payload.badge overrides
  shortBadge: string;
  desc: string;
}

// Fixed 9-node graph (contract §4). verify may loop back to collect once.
export const NODES: NodeMeta[] = [
  { key: "intake", label: "intake", badge: "Change Streams", shortBadge: "Change Streams", desc: "Change Stream wakes the agent unprompted on a fresh error." },
  { key: "collect", label: "collect", badge: "Time Series", shortBadge: "Time Series", desc: "Pull the correlated window of txn/error/service + time-series metrics." },
  { key: "correlate", label: "correlate", badge: "layered-status decode", shortBadge: "status decode", desc: "Decode layered transport vs business status across collections." },
  { key: "recall", label: "recall", badge: "$rankFusion — Atlas Search + Vector Search (autoEmbed voyage-4-lite)", shortBadge: "$rankFusion", desc: "Hybrid recall of similar past incidents + KB (lexical + vector, fused)." },
  { key: "hypothesize", label: "hypothesize", badge: "reasoning LLM", shortBadge: "hypothesize", desc: "Form candidate root-cause hypotheses from evidence + memory." },
  { key: "verify", label: "verify", badge: "evidence check", shortBadge: "verify", desc: "Verify hypotheses against raw docs; may loop back to collect once." },
  { key: "rca", label: "rca", badge: "reasoning LLM", shortBadge: "rca", desc: "Assemble the causal chain, confidence and unknowns." },
  { key: "recommend", label: "recommend", badge: "tiered actions", shortBadge: "recommend", desc: "Produce tiered recommendations with owner/effort/impact." },
  { key: "persist", label: "persist", badge: "Automated Embedding — no client code", shortBadge: "AutoEmbed", desc: "Write the incident + memory; embeddings computed server-side." },
];

export const NODE_ORDER: string[] = NODES.map((n) => n.key);
export const NODE_BY_KEY: Record<string, NodeMeta> = Object.fromEntries(
  NODES.map((n) => [n.key, n]),
);
export const PIPELINE_NODES = new Set(["recall", "verify"]);

export interface ScenarioMeta {
  id: string;
  label: string;
  note: string;
}

// Scenarios (contract §6/§7) — simple headline stories first. Firing is a
// secondary path (CLI is primary).
export const SCENARIOS: ScenarioMeta[] = [
  { id: "login-failures", label: "User can't log in", note: "IAM outage behind the login journey" },
  { id: "upi-payment-failures", label: "UPI payments failing", note: "UPI switch timeout (U68) at UNIPAY" },
  { id: "eis-martech-brownout", label: "EIS·MarTech brownout", note: "EIS→MarTech latency ramp; offers slow" },
  { id: "martech-cif-desync", label: "MarTech CIF desync", note: "customer-profile lookup desync" },
  { id: "think360-token-expiry", label: "Think360 token expiry", note: "expired token on credit-data route" },
  { id: "unipay-bbps-brownout", label: "UNIPAY BBPS brownout", note: "billpay gateway slow / no-data" },
  { id: "gsa-validation-hang", label: "GSA validation hang", note: "insurance validate checks stall" },
  { id: "demand-loan-improper-response", label: "Demand-loan improper resp", note: "nested BSDML improper response" },
  { id: "poison-retry-loop", label: "Poison retry loop", note: "client replay storm on one cmnd" },
  { id: "eis-gateway-pool-exhaustion", label: "EIS pool exhaustion", note: "connection-pool starvation" },
];

// Map a journey/system error rate to a tile severity. Thresholds are the
// board's alerting contract: >=25% critical, >=5% warning, else healthy.
export function rateToSeverity(errorRate: number | undefined): Severity {
  if (errorRate === undefined || Number.isNaN(errorRate)) return "idle";
  if (errorRate >= 0.25) return "crit";
  if (errorRate >= 0.05) return "warn";
  return "ok";
}

export const SEV_CLASS: Record<Severity, { dot: string; text: string; ring: string; bar: string }> = {
  ok: { dot: "bg-sev-ok", text: "text-sev-ok", ring: "border-sev-ok/40", bar: "bg-sev-ok" },
  warn: { dot: "bg-sev-warn", text: "text-sev-warn", ring: "border-sev-warn/50", bar: "bg-sev-warn" },
  crit: { dot: "bg-sev-crit", text: "text-sev-crit", ring: "border-sev-crit/60", bar: "bg-sev-crit" },
  info: { dot: "bg-sev-info", text: "text-sev-info", ring: "border-sev-info/40", bar: "bg-sev-info" },
  biz: { dot: "bg-sev-biz", text: "text-sev-biz", ring: "border-sev-biz/50", bar: "bg-sev-biz" },
  idle: { dot: "bg-edge2", text: "text-muted", ring: "border-edge", bar: "bg-edge2" },
};

export const SEV_HEX: Record<Severity, string> = {
  ok: "#34d399",
  warn: "#f4b740",
  crit: "#f2686a",
  info: "#5aa8f0",
  biz: "#c084fc",
  idle: "#2a3644",
};
