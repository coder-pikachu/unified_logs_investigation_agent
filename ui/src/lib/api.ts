// Typed fetchers for every API endpoint in contract §5.
// All calls go through the /api proxy (see vite.config.ts).
import type {
  ArchResponse,
  ChatMessage,
  ChatSession,
  FeedbackVerdict,
  HealthResponse,
  Incident,
  IncidentSummary,
  MemoryResponse,
  MergedLog,
  MetricBucket,
  SearchResponse,
  ScenarioInfo,
} from "../types";

export const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    // Network / proxy-down: surface a typed error the UI treats as "empty".
    throw new ApiError(0, `network: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${path} → ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => req<HealthResponse>("/health"),

  incidents: (limit = 25) => req<IncidentSummary[]>(`/incidents${qs({ limit })}`),

  incident: (key: string) => req<Incident>(`/incidents/${encodeURIComponent(key)}`),

  logs: (p: { trnsId?: string; sessnTknId?: string; ids?: string; limit?: number }) =>
    req<MergedLog[]>(`/logs${qs(p)}`),

  search: (q: string) => req<SearchResponse>(`/search${qs({ q })}`),

  metrics: (service: string, window = "15m") =>
    req<MetricBucket[]>(`/metrics${qs({ service, window })}`),

  memory: () => req<MemoryResponse>("/memory"),

  scenarios: () => req<ScenarioInfo[]>("/scenarios"),

  chat: (b: { sessionId?: string; message: string; image?: string }) =>
    req<{ sessionId: string; reply: ChatMessage; incidentKey: string | null }>("/chat", {
      method: "POST",
      body: JSON.stringify(b),
    }),

  chatSession: (id: string) => req<ChatSession>(`/chat/${encodeURIComponent(id)}`),

  architecture: () => req<ArchResponse>("/architecture"),

  fireScenario: (id: string) =>
    req<{ ok: boolean }>(`/scenarios/${encodeURIComponent(id)}/fire`, { method: "POST" }),

  feedback: (body: { incidentKey: string; verdict: FeedbackVerdict; note?: string }) =>
    req<{ ok: boolean }>("/feedback", { method: "POST", body: JSON.stringify(body) }),
};

export const STREAM_URL = `${API_BASE}/stream`;
