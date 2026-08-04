// Types mirror the shared build contract (§3 incident doc, §4 SSE, §5 API).
// Fields the live API may or may not send are optional so the UI degrades
// gracefully against an unbuilt / partial backend.

// ---------- incident doc (contract §3) ----------
export interface TimelineEntry {
  _id?: string;
  ts: string;
  trnsId: string;
  journey: string;
  system: string;
  srvcId: string;
  errCd: string;
  businessStatus: string;
  transportStatus: string;
  decodedErrorChain?: string[] | string | Record<string, unknown>;
  durationMs: number;
  note?: string;
  sourceApp?: string;
}

export interface CorrelationBlock {
  joinKeys: Record<string, number>;
  services: { name: string; collections: string[]; docs: number }[];
  collections: Record<string, number>;
  totalDocs: number;
}

export interface AgentQuery {
  collection: string;
  purpose: string;
  workload?: string;
  query: unknown;
}

export type RecTier = "immediate" | "fix" | "prevention";
export interface Recommendation {
  tier: RecTier;
  action: string;
  ownerSystem: string;
  effort: "S" | "M" | "L";
  impact: "H" | "M" | "L";
}

export interface RcaBlock {
  rootCause: string;
  faultClass?: "technical" | "business" | "mixed" | string;
  faultReason?: string;
  causalChain: string[];
  contributingFactors: string[];
  evidence: string[]; // ObjectId-as-str
  confidence: number; // 0..1
  unknowns: string[];
}

export interface CollectionAnalyzed {
  collection: string;
  role: string;
  examined: number;
}

export interface ScenarioInfo {
  id: string;
  title?: string;
  faultClass?: "technical" | "business" | string;
  presenterNote?: string;
  description?: string;
  expectedOrigin?: string;
  decoy?: string;
  analyzes?: string[];
}

export interface RecalledIncident {
  incidentKey: string;
  score: number;
  summary_text?: string;
  arm?: string;
  searchScore?: number;
  vectorScore?: number;
}
export interface RecalledKb {
  title: string;
  score: number;
}

// Recall arms detail, if the recall node exposes both arms + fusion.
export interface RecallArms {
  search?: { incidentKey?: string; title?: string; score: number }[];
  vector?: { incidentKey?: string; title?: string; score: number }[];
  fused?: { incidentKey?: string; title?: string; score: number }[];
  minVectorScore?: number;
}

export interface NodeTraceEntry {
  node: string;
  phase?: string;
  ms?: number;
  summary?: string;
  input?: unknown;
  output?: unknown;
  badge?: string;
  pipeline?: unknown; // literal aggregation pipeline (recall + verify)
  arms?: RecallArms;
  [k: string]: unknown;
}

export interface Incident {
  _id?: string;
  incidentKey: string;
  status: "analyzing" | "complete" | "failed";
  trnsIds: string[];
  sessnTknIds: string[];
  firstErrorAt: string;
  analyzedAt: string;
  durationMs: number;
  errCds: string[];
  journeysInvolved: string[];
  systemsInvolved: string[];
  originComponent: string;
  originDocId?: string | null;
  timeline: TimelineEntry[];
  metrics: { p95BaselineMs: number; p95IncidentMs: number; usersAffected: number };
  rca: RcaBlock;
  faultClass?: "technical" | "business" | "mixed" | string;
  faultReason?: string;
  collectionsAnalyzed?: CollectionAnalyzed[];
  correlation?: CorrelationBlock;
  agentQueries?: AgentQuery[];
  blastRadius: { journeys: string[]; channels: number[]; userCount: number };
  recommendations: Recommendation[];
  recalledIncidents: RecalledIncident[];
  recalledKb: RecalledKb[];
  nodeTrace: NodeTraceEntry[];
}

// The list endpoint returns a lighter summary; treat as a partial incident.
export type IncidentSummary = Partial<Incident> & { incidentKey: string };

// ---------- API responses (contract §5) ----------
export interface HealthResponse {
  mongo?: boolean | string;
  grove?: boolean | string;
  ts?: string;
  [k: string]: unknown;
}

export interface MergedLog {
  _id: string;
  source: "audit_transaction" | "audit_error" | "audit_service" | string;
  trns_id?: string;
  sessn_tkn_id?: string;
  ts?: string;
  [k: string]: unknown;
}

export interface SearchHit {
  _id?: string;
  source?: string;
  score?: number;
  [k: string]: unknown;
}
export interface SearchResponse {
  errors: SearchHit[];
  services: SearchHit[];
}

export interface MetricBucket {
  bucketTs: string;
  p50: number;
  p95: number;
  errorRate: number;
  count: number;
}

export interface IncidentMemory {
  incidentKey: string;
  summary_text: string;
  err_cds: string[];
  srvc_ids: string[];
  journeys: string[];
  createdAt: string;
  sourceIncidentKey?: string;
  [k: string]: unknown;
}

export interface Playbook {
  _id?: string;
  route?: string;
  key?: string;
  seenCount?: number;
  confidence?: number;
  confirmedFixes?: string[];
  value?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface MemoryResponse {
  incidents: IncidentMemory[];
  playbooks: Playbook[];
}

export type FeedbackVerdict = "up" | "down";

// ---------- SSE events (contract §4) ----------
export type SSEType = "node" | "incident" | "log" | "token" | "chat";
export interface SSEEvent {
  type: SSEType;
  incidentKey?: string;
  sessionId?: string;
  node?: string;
  phase?: "start" | "progress" | "end";
  ms?: number;
  summary?: string;
  payload?: Record<string, unknown> & { badge?: string };
}

// ---------- Investigate chat ----------
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  ts: number | string;
  incidentKey?: string | null;
  imageId?: string | null;
}
export interface ChatSession {
  _id: string;
  messages: ChatMessage[];
  lastIncidentKey?: string | null;
}

// ---------- Architecture page ----------
export interface ArchApp {
  id: string;
  name: string;
  tech: string;
  writes: string[];
  channels?: string[];
  destinations?: string[];
  ingestPerSec: number;
  lastWriteAt?: string | null;
  recentErrors: number;
}
export interface ArchCollection {
  name: string;
  role: string;
  docs: number | null;
  storageBytes: number | null;
  ingestPerSec: number | null;
  queryMs: number | null;
}
export interface ArchResponse {
  apps: ArchApp[];
  collections: ArchCollection[];
  correlationExample: {
    trnsId: string;
    sessnTknId?: string;
    docs: { collection: string; sourceApp: string; label: string; ts: string }[];
  } | null;
  agent: {
    watcherHeartbeatAt?: string | null;
    resumeStreams: string[];
    lastRun?: { incidentKey: string; durationMs?: number; tokenUsage?: Record<string, number> } | null;
  };
  ts: number;
}
