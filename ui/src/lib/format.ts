// Small pure formatters shared across views.

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function fmtMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m${s.toString().padStart(2, "0")}s`;
}

function toDate(v: string | number | Date | undefined): Date | null {
  if (v === undefined || v === null) return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtClock(v: string | number | Date | undefined): string {
  const d = toDate(v);
  if (!d) return "—";
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

export function fmtClockMs(v: string | number | Date | undefined): string {
  const d = toDate(v);
  if (!d) return "—";
  return `${d.toLocaleTimeString("en-GB", { hour12: false })}.${d
    .getMilliseconds()
    .toString()
    .padStart(3, "0")}`;
}

export function fmtDateTime(v: string | number | Date | undefined): string {
  const d = toDate(v);
  if (!d) return "—";
  return d.toLocaleString("en-GB", { hour12: false });
}

export function timeMs(v: string | number | Date | undefined): number {
  const d = toDate(v);
  return d ? d.getTime() : 0;
}

export function fmtCost(usd: number): string {
  if (!usd) return "$0.0000";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function fmtInt(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "0";
  return n.toLocaleString("en-US");
}

export function fmtBytes(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

export function pct(n: number, digits = 0): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

// A stable pretty JSON for pipeline / payload rendering.
export function pretty(v: unknown): string {
  if (v === undefined) return "";
  if (typeof v === "string") {
    // strings that are themselves JSON get re-parsed for nicer display
    const t = v.trim();
    if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
      try {
        return JSON.stringify(JSON.parse(t), null, 2);
      } catch {
        return v;
      }
    }
    return v;
  }
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
