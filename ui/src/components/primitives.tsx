import { useState } from "react";

import { cx, pretty } from "../lib/format";
import { SEV_CLASS, type Severity } from "../lib/meta";

export function SevDot({ sev, pulse }: { sev: Severity; pulse?: boolean }) {
  return (
    <span
      className={cx(
        "inline-block h-2 w-2 rounded-full",
        SEV_CLASS[sev].dot,
        pulse && sev !== "idle" && "animate-pulsedot",
      )}
    />
  );
}

export function FaultBadge({ fc, className }: { fc?: string; className?: string }) {
  if (!fc) return null;
  const tech = fc === "technical";
  const biz = fc === "business";
  return (
    <span
      className={cx(
        "chip border !text-[9px] uppercase tracking-wide",
        tech && "border-sev-warn/50 text-sev-warn",
        biz && "border-accent2/50 text-accent",
        !tech && !biz && "border-edge text-muted",
        className,
      )}
      title={tech ? "technical / infrastructure root cause" : biz ? "business-rule / data root cause" : fc}
    >
      {tech ? "technical" : biz ? "business" : fc}
    </span>
  );
}

export function Chip({
  children,
  sev = "idle",
  title,
}: {
  children: React.ReactNode;
  sev?: Severity;
  title?: string;
}) {
  const c = SEV_CLASS[sev];
  return (
    <span
      title={title}
      className={cx("chip border", c.text, c.ring, "bg-black/20")}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  title,
  hint,
  icon = "∅",
}: {
  title: string;
  hint?: string;
  icon?: string;
}) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-1 py-8 text-center">
      <div className="font-mono text-2xl text-edge2">{icon}</div>
      <div className="text-sm text-fgdim">{title}</div>
      {hint && <div className="max-w-xs text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn !px-1.5 !py-0.5 text-[10px]"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => {
            setDone(true);
            window.setTimeout(() => setDone(false), 1200);
          },
          () => undefined,
        );
      }}
    >
      {done ? "✓ copied" : label}
    </button>
  );
}

export function JsonBlock({ value, maxH = 320 }: { value: unknown; maxH?: number }) {
  const text = pretty(value);
  return (
    <div className="relative">
      <div className="absolute right-1.5 top-1.5 z-10">
        <CopyButton text={text} />
      </div>
      <pre
        className="panel-2 overflow-auto rounded p-2 font-mono text-[11px] leading-relaxed text-fgdim"
        style={{ maxHeight: maxH }}
      >
        {text || "—"}
      </pre>
    </div>
  );
}

export function StatBadge({ label, value, sev }: { label: string; value: string; sev?: Severity }) {
  return (
    <div className="flex flex-col">
      <span className="label">{label}</span>
      <span className={cx("kpi text-sm", sev ? SEV_CLASS[sev].text : "text-fg")}>{value}</span>
    </div>
  );
}
