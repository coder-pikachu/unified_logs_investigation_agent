"""GET /api/architecture — the live system topology the UI's ARCHITECTURE tab
renders: the simulated Java applications, per-collection ingestion rates and
sampled query latencies, a live cross-collection correlation example, and the
agent's change-stream state. Everything is measured against the one Atlas DB.
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter

from ..config import settings
from ..db import get_db, jsonable
from ..graph.nodes import _source_app

router = APIRouter(prefix="/api")

WINDOW_S = 60  # ingestion-rate window

# The simulated Java applications (static topology; live numbers filled per poll).
APPS: list[dict[str, Any]] = [
    {"id": "nova-app", "name": "NOVA App (journey tier)",
     "tech": "Java 21 · Log4j2 → NovaMongo appender",
     "writes": [settings.C_TXN, settings.C_ERR],
     "channels": ["mobile (2001)", "web (1001)"]},
    {"id": "eis-gateway", "name": "EIS Gateway",
     "tech": "Java connector · systm_nm 'EIS'",
     "writes": [settings.C_SVC],
     "destinations": ["IAM", "Martech", "THINK360", "CBS", "CustProfile"]},
    {"id": "unipay-bbps", "name": "UNIPAY BBPS",
     "tech": "Java connector · systm_nm ' UNIPAY' · UPI switch",
     "writes": [settings.C_SVC]},
    {"id": "metrics", "name": "Metrics emitter",
     "tech": "Java · both tiers", "writes": [settings.C_METRICS]},
]

# collection -> (role, time field for rate/latency sampling; None = unsampled)
COLLECTIONS: list[tuple[str, str, str | None]] = [
    (settings.C_TXN, "journey / API calls", "crtd_on"),
    (settings.C_ERR, "error events", "crtd_on"),
    (settings.C_SVC, "downstream / dependency calls", "crtd_on"),
    (settings.C_METRICS, "time-series metrics (ops sparklines + baselines)", "ts"),
    (settings.C_INCIDENTS, "agent RCA reports", "createdAt"),
    (settings.C_MEMORY, "distilled incident memory (autoEmbed)", "createdAt"),
    (settings.C_KB, "runbooks (autoEmbed)", None),
    (settings.C_CHECKPOINTS, "LangGraph short-term memory (MongoDBSaver)", None),
    (settings.C_CHECKPOINT_WRITES, "LangGraph short-term memory (MongoDBSaver)", None),
    (settings.C_STORE, "route playbooks (MongoDBStore)", None),
    (settings.C_FEEDBACK, "learn path", None),
    (settings.C_STATE, "resume tokens · heartbeat · sim command", None),
    (settings.C_CHAT, "investigation chat history", None),
]

HOT = {settings.C_TXN: "crtd_on", settings.C_ERR: "crtd_on",
       settings.C_SVC: "crtd_on", settings.C_METRICS: "ts"}


def _rate(db, coll: str, field: str, w: dt.datetime) -> float:
    return round(db[coll].count_documents({field: {"$gte": w}}) / WINDOW_S, 2)


def _last_write(db, coll: str, field: str, query: dict | None = None) -> Any:
    doc = db[coll].find_one(query or {}, {field: 1}, sort=[(field, -1)])
    return doc.get(field) if doc else None


def _timed_query(db, coll: str, field: str | None) -> float:
    t0 = time.perf_counter()
    if field:
        db[coll].find_one(sort=[(field, -1)])
    else:
        db[coll].find_one()
    return round((time.perf_counter() - t0) * 1000, 1)


@router.get("/architecture")
def architecture() -> dict:
    db = get_db()
    now = dt.datetime.now(dt.timezone.utc)
    w = now - dt.timedelta(seconds=WINDOW_S)

    # ---- gather everything in parallel: each row costs 2-3 WAN round-trips,
    # sequential would blow the 5s poll budget (PyMongo is thread-safe).
    def app_row(a: dict) -> dict:
        app = dict(a)
        if a["id"] == "nova-app":
            txn_n = db[settings.C_TXN].count_documents({"crtd_on": {"$gte": w}})
            err_n = db[settings.C_ERR].count_documents({"crtd_on": {"$gte": w}})
            app["ingestPerSec"] = round((txn_n + err_n) / WINDOW_S, 2)
            app["recentErrors"] = err_n
            app["lastWriteAt"] = _last_write(db, settings.C_TXN, "crtd_on")
        elif a["id"] in ("eis-gateway", "unipay-bbps"):
            # exact $in (index-friendly) - ' UNIPAY' leading space is authentic
            names = ["EIS", " EIS"] if a["id"] == "eis-gateway" else ["UNIPAY", " UNIPAY"]
            q = {"systm_nm": {"$in": names}, "crtd_on": {"$gte": w}}
            app["ingestPerSec"] = round(db[settings.C_SVC].count_documents(q) / WINDOW_S, 2)
            app["recentErrors"] = db[settings.C_SVC].count_documents(
                {**q, "err_cd": {"$ne": None, "$nin": ["", "200"]}})
            app["lastWriteAt"] = _last_write(db, settings.C_SVC, "crtd_on",
                                             {"systm_nm": {"$in": names}})
        else:  # metrics
            app["ingestPerSec"] = _rate(db, settings.C_METRICS, "ts", w)
            app["recentErrors"] = db[settings.C_METRICS].count_documents(
                {"ts": {"$gte": w}, "transportOk": False})
            app["lastWriteAt"] = _last_write(db, settings.C_METRICS, "ts")
        return app

    def coll_row(spec: tuple[str, str, str | None]) -> dict:
        name, role, field = spec
        docs = storage = None
        try:
            st = db.command("collStats", name)
            docs, storage = int(st.get("count", 0)), int(st.get("size", 0))
        except Exception:
            pass
        try:
            query_ms = _timed_query(db, name, field)
        except Exception:
            query_ms = None
        return {
            "name": name, "role": role, "docs": docs, "storageBytes": storage,
            "ingestPerSec": _rate(db, name, HOT[name], w) if name in HOT else None,
            "queryMs": query_ms,
        }

    with ThreadPoolExecutor(max_workers=10) as pool:
        app_futs = [pool.submit(app_row, a) for a in APPS]
        coll_futs = [pool.submit(coll_row, s) for s in COLLECTIONS]
        apps = [f.result() for f in app_futs]
        collections = [f.result() for f in coll_futs]

    # ---- live correlation example: one trns_id written by several services
    example = None
    for seed_coll in (settings.C_SVC, settings.C_ERR):
        seed = db[seed_coll].find_one({}, sort=[("crtd_on", -1)])
        if not seed or not seed.get("trns_id"):
            continue
        tr = seed["trns_id"]
        docs = []
        for coll in (settings.C_TXN, settings.C_ERR, settings.C_SVC):
            for d in db[coll].find({"trns_id": tr}).limit(3):
                evt = {"collection": coll, "system": d.get("systm_nm")}
                docs.append({
                    "collection": coll,
                    "sourceApp": _source_app(evt),
                    "label": d.get("cmnd_id") or d.get("srvc_id") or d.get("err_cd") or "doc",
                    "ts": d.get("crtd_on"),
                })
        if len({d["collection"] for d in docs}) >= 2:
            example = {"trnsId": tr, "sessnTknId": seed.get("sessn_tkn_id"), "docs": docs}
            break

    # ---- agent state (change streams + last run)
    hb = db[settings.C_STATE].find_one({"_id": "watcher:heartbeat"})
    streams = [str(d["_id"]).split(":", 1)[1] for d in
               db[settings.C_STATE].find({"_id": {"$regex": "^resume:"}}, {"_id": 1})]
    last = db[settings.C_INCIDENTS].find_one(
        {"status": "complete"}, {"incidentKey": 1, "durationMs": 1, "tokenUsage": 1},
        sort=[("analyzedAt", -1)])

    return jsonable({
        "apps": apps,
        "collections": collections,
        "correlationExample": example,
        "agent": {
            "watcherHeartbeatAt": hb.get("ts") if hb else None,
            "resumeStreams": streams,
            "lastRun": ({"incidentKey": last["incidentKey"], "durationMs": last.get("durationMs"),
                         "tokenUsage": last.get("tokenUsage")} if last else None),
        },
        "ts": int(time.time() * 1000),
    })
