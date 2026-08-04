import { SEV_CLASS, type Severity } from "../lib/meta";

export interface SparklineProps {
  data: number[];
  sev?: Severity;
  baseline?: number;
  width?: number;
  height?: number;
}

// Hand-rolled inline-SVG sparkline (no chart libs, per contract).
export function Sparkline({ data, sev = "idle", baseline, width = 132, height = 34 }: SparklineProps) {
  const stroke =
    sev === "crit" ? "#f2686a" : sev === "warn" ? "#f4b740" : sev === "ok" ? "#34d399" : "#3ad0c0";
  const pad = 2;
  const w = width;
  const h = height;

  if (!data || data.length < 2) {
    return (
      <svg width={w} height={h} className="overflow-visible" role="img" aria-label="no data">
        <line
          x1={pad}
          y1={h / 2}
          x2={w - pad}
          y2={h / 2}
          stroke="#2a3644"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
        <text x={w / 2} y={h / 2 - 3} textAnchor="middle" className="fill-muted" fontSize={8}>
          no data
        </text>
      </svg>
    );
  }

  const min = Math.min(...data, baseline ?? Infinity);
  const max = Math.max(...data, baseline ?? -Infinity);
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (data.length - 1);
  const y = (v: number) => h - pad - ((v - min) / span) * (h - 2 * pad);

  const line = data.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(data.length - 1).toFixed(1)},${h - pad} L${x(0).toFixed(1)},${h - pad} Z`;
  const lastY = y(data[data.length - 1]);
  const lastX = x(data.length - 1);
  const gid = `sg-${sev}`;

  return (
    <svg width={w} height={h} className="overflow-visible" role="img" aria-label="latency sparkline">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      {baseline !== undefined && baseline >= min && baseline <= max && (
        <line
          x1={pad}
          y1={y(baseline)}
          x2={w - pad}
          y2={y(baseline)}
          stroke="#3a475a"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      )}
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={stroke} strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={1.8} fill={stroke} className={sev === "crit" ? "animate-pulsedot" : undefined} />
    </svg>
  );
}
