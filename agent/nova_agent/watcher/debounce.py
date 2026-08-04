"""Debounce + grouping for the change-stream watcher (pure, unit-testable).

First error for a signature opens a collection window (default 4s). Events
sharing that signature (err_cd or srvc_id) accrete into the window. When the
window closes, one trigger is emitted for the whole group; >=escalate_n distinct
trns_ids flags a systemic incident (grouped on the shared dimension, not a user).
Thread-safe: watcher threads add(), a flusher thread calls due().
"""
from __future__ import annotations

import datetime as dt
import threading


class DebounceBuffer:
    def __init__(self, window_s: float, escalate_n: int = 3) -> None:
        self.window_s = window_s
        self.escalate_n = escalate_n
        self._windows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def add(self, ev: dict, now: float) -> None:
        sig = ev.get("signature") or "UNKNOWN"
        with self._lock:
            w = self._windows.get(sig)
            if w is None:
                w = {"signature": sig, "opened": now, "deadline": now + self.window_s,
                     "events": [], "trns": set(), "sessions": set()}
                self._windows[sig] = w
            w["events"].append(ev)
            if ev.get("trns_id"):
                w["trns"].add(ev["trns_id"])
            if ev.get("sessn_tkn_id"):
                w["sessions"].add(ev["sessn_tkn_id"])

    def due(self, now: float) -> list[dict]:
        """Pop windows whose deadline passed; return one trigger each."""
        out = []
        with self._lock:
            for sig, w in list(self._windows.items()):
                if now >= w["deadline"]:
                    out.append(self._trigger(w))
                    del self._windows[sig]
        return out

    def _trigger(self, w: dict) -> dict:
        bucket = dt.datetime.fromtimestamp(w["opened"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
        distinct = len(w["trns"])
        sig = w["signature"]
        return {
            "incident_key": f"{sig}:{bucket}",
            "signature": sig,
            "trns_ids": sorted(w["trns"]),
            "sessn_tkn_ids": sorted(w["sessions"]),
            "distinctTrns": distinct,
            "escalated": distinct >= self.escalate_n,
            "sources": sorted({e.get("source") for e in w["events"] if e.get("source")}),
            "hard": any(e.get("hard") for e in w["events"]),
            "openedTs": w["opened"],
            "eventCount": len(w["events"]),
        }

    @property
    def open_windows(self) -> int:
        with self._lock:
            return len(self._windows)
