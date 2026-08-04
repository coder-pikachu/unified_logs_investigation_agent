import { useCallback, useEffect, useRef, useState } from "react";

import { EmptyState, FaultBadge } from "../components/primitives";
import { api } from "../lib/api";
import { cx, fmtClock } from "../lib/format";
import { NODE_ORDER } from "../lib/meta";
import type { AppStore } from "../store";
import type { ChatMessage } from "../types";

const MAX_IMAGE_BYTES = 3 * 1024 * 1024; // backend caps base64 at 4MB

function msgKey(m: ChatMessage): string {
  return `${m.role}-${String(m.ts)}-${m.text.slice(0, 40)}`;
}

function faultOf(text: string): string | undefined {
  const m = /\*\*(technical|business|mixed)\*\*/i.exec(text);
  return m ? m[1].toLowerCase() : undefined;
}

/** Render **bold** minimally without a markdown lib. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**"))
          return <strong key={i} className="text-fg">{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`"))
          return <code key={i} className="font-mono text-accent">{p.slice(1, -1)}</code>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

function NodeDots({ store }: { store: AppStore }) {
  return (
    <div className="flex items-center gap-1" title="agent workflow progress">
      {NODE_ORDER.map((k) => {
        const st = store.nodes[k]?.state ?? "pending";
        return (
          <span
            key={k}
            title={k}
            className={cx(
              "inline-block h-1.5 w-1.5 rounded-full",
              st === "done" && "bg-sev-ok",
              st === "running" && "bg-sev-warn animate-pulsedot",
              st === "skipped" && "bg-edge",
              st === "pending" && "bg-edge/60",
            )}
          />
        );
      })}
    </div>
  );
}

function InvestigationCard({
  incidentKey,
  store,
  onOpenIncident,
  fault,
}: {
  incidentKey: string;
  store: AppStore;
  onOpenIncident: (k: string) => void;
  fault?: string;
}) {
  const live = store.runIncidentKey === incidentKey;
  return (
    <div className="mt-1.5 flex items-center gap-3 rounded border border-edge bg-ink px-2 py-1.5">
      {live && <NodeDots store={store} />}
      {fault && <FaultBadge fc={fault} />}
      <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted">{incidentKey}</span>
      <button
        className="btn !py-0.5 text-[10px]"
        onClick={() => onOpenIncident(incidentKey)}
      >
        open incident →
      </button>
    </div>
  );
}

function Bubble({
  m,
  store,
  onOpenIncident,
  localImage,
}: {
  m: ChatMessage;
  store: AppStore;
  onOpenIncident: (k: string) => void;
  localImage?: string;
}) {
  const user = m.role === "user";
  const imgSrc = localImage ?? (m.imageId ? `/api/chat/image/${m.imageId}` : undefined);
  return (
    <div className={cx("flex", user ? "justify-end" : "justify-start")}>
      <div
        className={cx(
          "max-w-[85%] rounded px-2.5 py-1.5 text-xs",
          user
            ? "border border-accent2/40 bg-accent2/10 text-fg"
            : "panel-2 border border-edge text-fgdim",
        )}
      >
        {imgSrc && (
          <img src={imgSrc} alt="attached screenshot" className="mb-1.5 max-h-40 rounded border border-edge" />
        )}
        <div className="whitespace-pre-wrap leading-relaxed">
          <RichText text={m.text} />
        </div>
        {!user && m.incidentKey && (
          <InvestigationCard
            incidentKey={m.incidentKey}
            store={store}
            onOpenIncident={onOpenIncident}
            fault={faultOf(m.text)}
          />
        )}
        <div className={cx("mt-1 text-[9px]", user ? "text-accent/70" : "text-muted")}>
          {typeof m.ts === "number" ? fmtClock(m.ts) : fmtClock(m.ts)}
        </div>
      </div>
    </div>
  );
}

export function InvestigateView({
  store,
  onOpenIncident,
}: {
  store: AppStore;
  onOpenIncident: (key: string) => void;
}) {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [localImages, setLocalImages] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState("");
  const [pendingImage, setPendingImage] = useState<{ dataUrl: string; name: string } | null>(null);
  const [imageWarn, setImageWarn] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Live assistant messages (investigation completions) arrive over SSE.
  useEffect(() => {
    const mine = store.chatFeed.filter((f) => f.sessionId === sessionId);
    if (!mine.length) return;
    setMessages((prev) => {
      const seen = new Set(prev.map(msgKey));
      const fresh = mine.map((f) => f.message).filter((m) => !seen.has(msgKey(m)));
      return fresh.length ? [...prev, ...fresh] : prev;
    });
  }, [store.chatFeed, sessionId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, sending]);

  const attach = useCallback((file: File) => {
    setImageWarn(null);
    if (file.size > MAX_IMAGE_BYTES) {
      setImageWarn(`image is ${(file.size / 1024 / 1024).toFixed(1)}MB — 3MB max`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setPendingImage({ dataUrl: String(reader.result), name: file.name });
    reader.readAsDataURL(file);
  }, []);

  const send = useCallback(() => {
    const text = draft.trim();
    if (!text || sending) return;
    const image = pendingImage?.dataUrl;
    const userMsg: ChatMessage = { role: "user", text, ts: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    if (image) setLocalImages((prev) => ({ ...prev, [msgKey(userMsg)]: image }));
    setDraft("");
    setPendingImage(null);
    setSending(true);
    api
      .chat({ sessionId, message: text, image })
      .then((res) => {
        setMessages((prev) => [...prev, res.reply]);
      })
      .catch((e: unknown) => {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: `⚠ agent unreachable: ${(e as Error).message}`, ts: Date.now() },
        ]);
      })
      .finally(() => setSending(false));
  }, [draft, pendingImage, sending, sessionId]);

  const reset = () => {
    setSessionId(crypto.randomUUID());
    setMessages([]);
    setLocalImages({});
    setPendingImage(null);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="panel flex items-center justify-between px-3 py-2">
        <div>
          <span className="text-sm font-medium text-fg">Investigate</span>
          <span className="label ml-3">describe an issue · attach a screenshot · the agent runs the RCA</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="label font-mono">{sessionId.slice(0, 8)}</span>
          <button className="btn !py-0.5 text-[10px]" onClick={reset}>
            new conversation
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="panel min-h-0 flex-1 space-y-2.5 overflow-auto p-3">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <EmptyState
              title="Describe a customer issue"
              hint="e.g. “customers say the offers section shows an error” — attach a screenshot if you have one. I'll find the matching audit evidence across the collections and run a full RCA."
              icon="🔎"
            />
          </div>
        ) : (
          messages.map((m) => (
            <Bubble
              key={msgKey(m)}
              m={m}
              store={store}
              onOpenIncident={onOpenIncident}
              localImage={localImages[msgKey(m)]}
            />
          ))
        )}
        {sending && (
          <div className="flex justify-start">
            <div className="panel-2 rounded border border-edge px-2.5 py-1.5 text-xs text-muted">
              triaging · searching audit_transaction / audit_error / audit_service…
            </div>
          </div>
        )}
      </div>

      <div className="panel p-2">
        {imageWarn && <div className="mb-1 text-[10px] text-sev-crit">{imageWarn}</div>}
        {pendingImage && (
          <div className="mb-1.5 flex items-center gap-2">
            <img src={pendingImage.dataUrl} alt="pending" className="h-10 rounded border border-edge" />
            <span className="text-[10px] text-muted">{pendingImage.name}</span>
            <button className="chip border border-edge text-muted" onClick={() => setPendingImage(null)}>
              ✕ remove
            </button>
          </div>
        )}
        <div className="flex items-end gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) attach(f);
              e.target.value = "";
            }}
          />
          <button
            className="btn !py-1.5"
            title="attach a screenshot"
            onClick={() => fileRef.current?.click()}
          >
            📎
          </button>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder="Describe the issue… (Enter to send, Shift+Enter for a new line)"
            className="min-h-[38px] flex-1 resize-none rounded border border-edge bg-ink px-2 py-1.5 text-xs text-fg outline-none placeholder:text-muted focus:border-accent"
          />
          <button className="btn !py-1.5" onClick={send} disabled={sending || !draft.trim()}>
            {sending ? "…" : "send"}
          </button>
        </div>
      </div>
    </div>
  );
}
