"""Resume-token-safe Change Streams watcher — the event backbone (claim #2).

Two watches feed one debounce buffer:
  - audit_error  (every error insert; signature = err_cd)
  - audit_service failures (trns_sts '-2' or technical err_cd; signature = srvc_id)
Downstream-only degradation surfaces before user errors do.

Resume tokens persist in agent_state after every processed event, so a restart
resumes with no gaps and no replays. Dispatch is idempotent: a unique incidentKey
upsert plus a trns-overlap merge means one incident per cascade even if both
watches fire. Runs in plain threads; run_incident publishes to the SSE bus
(publish is thread-safe).
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time

from ..api.sse import bus
from ..config import settings
from ..db import get_db, jsonable
from ..graph.runner import run_incident
from .debounce import DebounceBuffer

_TECH = re.compile(r"^TE", re.I)


class Watcher:
    def __init__(self) -> None:
        self.buffer = DebounceBuffer(settings.debounce_window_seconds)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._log_times: list[float] = []
        self._log_lock = threading.Lock()

    # -------------------------------------------------- lifecycle
    def start(self) -> None:
        db = get_db()
        # idempotency substrate: unique incidentKey
        try:
            db[settings.C_INCIDENTS].create_index("incidentKey", unique=True)
        except Exception:
            pass
        self._threads = [
            threading.Thread(target=self._watch_errors, name="watch-error", daemon=True),
            threading.Thread(target=self._watch_services, name="watch-service", daemon=True),
            threading.Thread(target=self._flusher, name="debounce-flusher", daemon=True),
            threading.Thread(target=self._heartbeat, name="watcher-heartbeat", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------- token persistence
    def _load_token(self, stream: str):
        doc = get_db()[settings.C_STATE].find_one({"_id": f"resume:{stream}"})
        return doc.get("token") if doc else None

    def _save_token(self, stream: str, token) -> None:
        get_db()[settings.C_STATE].update_one(
            {"_id": f"resume:{stream}"},
            {"$set": {"token": token, "updatedAt": dt.datetime.now(dt.timezone.utc)}},
            upsert=True,
        )

    # -------------------------------------------------- watches
    def _watch_errors(self) -> None:
        self._watch(settings.C_ERR, "audit_error",
                    [{"$match": {"operationType": "insert"}}], self._ev_from_error)

    def _watch_services(self) -> None:
        # Catch hard technical failures (trns_sts -2 / TE codes) AND the silent
        # UNIPAY business-failure-inside-success (responseReason "Failure") — the
        # "no red status" trap. Deliberately NOT matched: generic
        # `"success":false` payloads (EIS 404-inside-success) — that's the
        # authentic 5% noise floor and would flood the board; scenarios that rely
        # on it (think360) also fan out hard 5151 journey errors that trigger the
        # audit_error watch.
        pipeline = [{"$match": {"operationType": "insert", "$or": [
            {"fullDocument.trns_sts": "-2"},
            {"fullDocument.trns_sts": -2},
            {"fullDocument.err_cd": {"$regex": "^TE"}},
            {"fullDocument.srvc_rspn": {"$regex": r'"responseReason"\s*:\s*"Failure"', "$options": "i"}},
        ]}}]
        self._watch(settings.C_SVC, "audit_service", pipeline, self._ev_from_service)

    def _watch(self, coll: str, stream: str, pipeline: list, build_ev) -> None:
        db = get_db()
        while not self._stop.is_set():
            token = self._load_token(stream)
            try:
                kwargs = {"max_await_time_ms": 1000, "full_document": "updateLookup"}
                if token:
                    kwargs["resume_after"] = token
                with db[coll].watch(pipeline, **kwargs) as cs:
                    while not self._stop.is_set():
                        doc = cs.try_next()
                        if doc is None:
                            continue
                        self._save_token(stream, cs.resume_token)
                        ev = build_ev(doc)
                        if ev:
                            self.buffer.add(ev, time.time())
                        self._publish_log(coll, doc.get("fullDocument"))
            except Exception as e:
                bus.publish({"type": "log", "level": "warn",
                             "summary": f"{stream} watch reconnecting: {str(e)[:120]}"})
                # invalid/expired token -> drop it and resume from now
                if "resume" in str(e).lower() or "ChangeStreamHistoryLost" in str(e):
                    self._save_token(stream, None)
                time.sleep(2)

    def _ev_from_error(self, doc: dict) -> dict | None:
        fd = doc.get("fullDocument") or {}
        # audit_error events are user-facing symptoms — not "hard" on their own;
        # a single benign business exception stays background noise.
        return {"trns_id": fd.get("trns_id"), "sessn_tkn_id": fd.get("sessn_tkn_id"),
                "signature": fd.get("err_cd") or "UNKNOWN", "source": "audit_error", "hard": False}

    def _ev_from_service(self, doc: dict) -> dict | None:
        fd = doc.get("fullDocument") or {}
        sig = fd.get("srvc_id") or fd.get("err_cd") or "UNKNOWN"
        sts = str(fd.get("trns_sts")).strip()
        errc = str(fd.get("err_cd") or "")
        hard = sts == "-2" or errc.upper().startswith("TE")  # transport/technical failure
        return {"trns_id": fd.get("trns_id"), "sessn_tkn_id": fd.get("sessn_tkn_id"),
                "signature": sig, "source": "audit_service", "hard": hard}

    # -------------------------------------------------- flusher / dispatch
    def _flusher(self) -> None:
        while not self._stop.is_set():
            for trigger in self.buffer.due(time.time()):
                try:
                    self._dispatch(trigger)
                except Exception as e:
                    bus.publish({"type": "log", "level": "error",
                                 "summary": f"dispatch failed: {str(e)[:150]}"})
            time.sleep(0.4)

    def _dispatch(self, trigger: dict) -> None:
        db = get_db()
        key = trigger["incident_key"]
        now = dt.datetime.now(dt.timezone.utc)

        # Significance gate: the authentic noise floor stays background. A hard
        # downstream failure (transport -2 / technical code) is always an incident,
        # even singly; softer signals (business-fail-inside-success payloads, lone
        # business exceptions) need a real burst — >=3 distinct trns in one debounce
        # window. The 5% noise floor almost never clusters 3 in 4s; a brownout or
        # fan-out does within a couple of windows.
        significant = bool(trigger.get("hard")) or trigger.get("distinctTrns", 0) >= 3
        if not significant:
            bus.publish({"type": "log", "level": "info",
                         "summary": f"noise: {trigger['signature']} "
                                    f"({trigger.get('distinctTrns', 0)} trns) — below incident threshold"})
            return

        # merge into a recent overlapping incident so one cascade = one incident.
        # Overlap on trns_id OR sessn_tkn_id: downstream latency shifts the
        # journey-error window past its service window, so the same cascade's
        # windows can have disjoint trns sets while sharing the user sessions.
        overlap_or = []
        if trigger["trns_ids"]:
            overlap_or.append({"trnsIds": {"$in": trigger["trns_ids"]}})
        if trigger["sessn_tkn_ids"]:
            overlap_or.append({"sessnTknIds": {"$in": trigger["sessn_tkn_ids"]}})
        if overlap_or:
            recent = db[settings.C_INCIDENTS].find_one({
                "createdAt": {"$gte": now - dt.timedelta(seconds=120)},
                "$or": overlap_or,
                "incidentKey": {"$ne": key},
            })
            if recent:
                db[settings.C_INCIDENTS].update_one({"_id": recent["_id"]}, {"$addToSet": {
                    "trnsIds": {"$each": trigger["trns_ids"]},
                    "sessnTknIds": {"$each": trigger["sessn_tkn_ids"]},
                }})
                return

        # same-downstream-family merge: srvc_id signatures on the SAME system
        # (unipay_*, eis_*) browning out within one scenario-length window (300s)
        # are one incident, even when their trns_ids are disjoint (different
        # journeys hit different routes, and a long ramp re-triggers).
        sig = str(trigger["signature"])
        if "_" in sig:
            fam = sig.split("_", 1)[0]
            recent = db[settings.C_INCIDENTS].find_one({
                "createdAt": {"$gte": now - dt.timedelta(seconds=300)},
                "signature": {"$regex": f"^{re.escape(fam)}_"},
                "incidentKey": {"$ne": key},
            })
            if recent:
                db[settings.C_INCIDENTS].update_one({"_id": recent["_id"]}, {"$addToSet": {
                    "trnsIds": {"$each": trigger["trns_ids"]},
                    "sessnTknIds": {"$each": trigger["sessn_tkn_ids"]},
                }})
                bus.publish({"type": "log", "level": "info",
                             "summary": f"merged {sig} burst into {recent['incidentKey']} (same {fam} family)"})
                return

        # idempotent claim: only the first upsert proceeds to a run
        res = db[settings.C_INCIDENTS].update_one(
            {"incidentKey": key},
            {"$setOnInsert": {"incidentKey": key, "status": "queued", "createdAt": now,
                              "signature": trigger["signature"],
                              "trnsIds": trigger["trns_ids"],
                              "sessnTknIds": trigger["sessn_tkn_ids"]}},
            upsert=True,
        )
        if res.upserted_id is None:
            return  # already claimed (restart-safe, no duplicate)

        bus.publish({"type": "log", "level": "info",
                     "summary": f"trigger {key}: {trigger['distinctTrns']} trns"
                                f"{' (escalated)' if trigger['escalated'] else ''}"})
        run_incident(trigger)

    # -------------------------------------------------- log firehose (<=20/s)
    def _publish_log(self, coll: str, fd: dict | None) -> None:
        if not fd:
            return
        now = time.time()
        with self._log_lock:
            self._log_times = [t for t in self._log_times if now - t < 1.0]
            if len(self._log_times) >= 20:
                return
            self._log_times.append(now)
        bus.publish({"type": "log", "collection": coll, "summary": _log_summary(coll, fd),
                     "payload": {"trnsId": fd.get("trns_id"), "srvcId": fd.get("srvc_id"),
                                 "errCd": fd.get("err_cd"), "cmndId": fd.get("cmnd_id")}})

    def _heartbeat(self) -> None:
        while not self._stop.is_set():
            get_db()[settings.C_STATE].update_one(
                {"_id": "watcher:heartbeat"},
                {"$set": {"ts": dt.datetime.now(dt.timezone.utc),
                          "openWindows": self.buffer.open_windows}},
                upsert=True,
            )
            time.sleep(5)


def _log_summary(coll: str, fd: dict) -> str:
    if coll == settings.C_ERR:
        return f"error {fd.get('err_cd')} on {fd.get('trns_id')}"
    if coll == settings.C_SVC:
        return f"service {fd.get('srvc_id')} sts={fd.get('trns_sts')} err={fd.get('err_cd')}"
    return f"txn {fd.get('cmnd_id')}"


_watcher: Watcher | None = None


def get_watcher() -> Watcher:
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher
