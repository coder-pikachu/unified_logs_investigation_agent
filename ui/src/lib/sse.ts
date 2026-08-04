// EventSource wrapper with auto-reconnect (exponential backoff) and typed
// events per contract §4. Server sends `data: {...}` lines; we also register
// named listeners in case the backend uses `event: <type>` framing.
import type { SSEEvent, SSEType } from "../types";

export interface StreamHandlers {
  onEvent?: (ev: SSEEvent) => void;
  onOpen?: () => void;
  onError?: () => void;
}

export interface StreamController {
  close: () => void;
}

const NAMED: SSEType[] = ["node", "incident", "log", "token", "chat"];

export function connectStream(url: string, handlers: StreamHandlers): StreamController {
  let es: EventSource | null = null;
  let closed = false;
  let retry = 1000;
  let timer: number | null = null;

  const dispatch = (raw: string, forcedType?: SSEType) => {
    if (!raw) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return; // ignore malformed frames
    }
    if (!parsed || typeof parsed !== "object") return;
    const ev = parsed as SSEEvent;
    if (forcedType && !ev.type) ev.type = forcedType;
    if (!ev.type) return;
    handlers.onEvent?.(ev);
  };

  const open = () => {
    if (closed) return;
    es = new EventSource(url);

    es.onopen = () => {
      retry = 1000;
      handlers.onOpen?.();
    };

    // Default (unnamed) frames — the primary path for sse-starlette.
    es.onmessage = (m) => dispatch(m.data);

    // Named frames — harmless if the server never uses them.
    for (const name of NAMED) {
      es.addEventListener(name, (m) => dispatch((m as MessageEvent).data, name));
    }

    es.onerror = () => {
      handlers.onError?.();
      es?.close();
      es = null;
      if (closed) return;
      timer = setTimeout(open, retry);
      retry = Math.min(retry * 2, 15000);
    };
  };

  open();

  return {
    close: () => {
      closed = true;
      clearTimeout(timer ?? undefined);
      es?.close();
      es = null;
    },
  };
}
