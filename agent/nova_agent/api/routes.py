"""FastAPI routes (contract §5). Sync `def` handlers run in the threadpool so
PyMongo calls never block the event loop; only the SSE stream is async.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import time
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Body, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import REPO_ROOT, settings
from ..db import get_db, jsonable
from .. import llm
from ..memory import store as store_mod
from .sse import bus, sse_format

router = APIRouter(prefix="/api")

_ERR_PATHS = ["err_cd", "err_typ", "err_dscrptn", "err_dtls", "biz_err_cd_1",
              "biz_err_cd_2", "biz_err_cd_3", "biz_err_cd_4", "biz_err_cd_5", "biz_err_cd_1_msg"]
_SVC_PATHS = ["err_cd", "srvc_id", "systm_nm", "err_msg"]

SCENARIOS = [
    "login-failures", "upi-payment-failures",
    "eis-martech-brownout", "martech-cif-desync", "think360-token-expiry",
    "unipay-bbps-brownout", "gsa-validation-hang", "demand-loan-improper-response",
    "poison-retry-loop", "eis-gateway-pool-exhaustion",
]


# --------------------------------------------------------------- health
@router.get("/health")
def health() -> dict:
    db_ok = False
    try:
        get_db().command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    grove_ok = False
    try:
        grove_ok = llm.health()
    except Exception:
        grove_ok = False
    return {"mongo": db_ok, "grove": grove_ok, "ts": int(time.time() * 1000)}


# --------------------------------------------------------------- incidents
@router.get("/incidents")
def incidents(limit: int = 20) -> list[dict]:
    cur = get_db()[settings.C_INCIDENTS].find(
        {}, {"timeline": 0, "verifications": 0, "nodeTrace": 0, "recallArms": 0, "agentQueries": 0}
    ).sort("createdAt", -1).limit(limit)
    return [jsonable(d) for d in cur]


@router.get("/incidents/{key:path}")
def incident(key: str) -> dict:
    doc = get_db()[settings.C_INCIDENTS].find_one({"incidentKey": key})
    return jsonable(doc) if doc else {}


# --------------------------------------------------------------- logs
@router.get("/logs")
def logs(trnsId: str | None = None, sessnTknId: str | None = None,
         ids: str | None = None, limit: int = 100) -> list[dict]:
    """Merged, source-tagged, time-sorted audit docs across all three collections.
    `ids` = comma-separated `_id`s (evidence citations) fetched directly."""
    db = get_db()
    q: dict[str, Any] = {}
    if trnsId:
        q["trns_id"] = trnsId
    if sessnTknId:
        q["sessn_tkn_id"] = sessnTknId
    if ids:
        oids: list[Any] = []
        for raw in ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                oids.append(ObjectId(raw))
            except Exception:
                oids.append(raw)
        q = {"_id": {"$in": oids}}
    if not q:
        return []
    per = max(1, limit // 3)
    merged: list[dict] = []
    for coll, tfield in ((settings.C_TXN, "strt_time"), (settings.C_ERR, "err_time"),
                         (settings.C_SVC, "strt_time")):
        for d in db[coll].find(q).limit(per):
            doc = jsonable(d)
            doc["source"] = coll
            doc["ts"] = doc.get(tfield) or doc.get("crtd_on") or doc.get("err_time")
            merged.append(doc)
    merged.sort(key=lambda d: d.get("ts") or "")
    return merged


# --------------------------------------------------------------- search
def _search(coll: str, index: str, q: str, paths: list[str]) -> list[dict]:
    pipe = [
        {"$search": {"index": index, "text": {"query": q, "path": paths}}},
        {"$limit": 10},
        {"$addFields": {"_score": {"$meta": "searchScore"}}},
    ]
    try:
        return [jsonable(d) for d in get_db()[coll].aggregate(pipe)]
    except Exception as e:
        return [{"__error__": str(e)[:200]}]


@router.get("/search")
def search(q: str = "") -> dict:
    if not q.strip():
        return {"errors": [], "services": []}
    return {
        "errors": _search(settings.C_ERR, settings.IDX_ERR_SEARCH, q, _ERR_PATHS),
        "services": _search(settings.C_SVC, settings.IDX_SVC_SEARCH, q, _SVC_PATHS),
    }


def _parse_window(w: str) -> int:
    """Accept '15m' | '300s' | '2h' | '300' (bare = seconds); default 300s."""
    w = str(w).strip().lower()
    try:
        if w.endswith("ms"):
            return max(1, int(float(w[:-2]) / 1000))
        if w.endswith("s"):
            return int(float(w[:-1]))
        if w.endswith("m"):
            return int(float(w[:-1]) * 60)
        if w.endswith("h"):
            return int(float(w[:-1]) * 3600)
        return int(float(w))
    except Exception:
        return 300


# --------------------------------------------------------------- metrics
@router.get("/metrics")
def metrics(service: str | None = None, window: str = "5m") -> list[dict]:
    db = get_db()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=_parse_window(window))
    match: dict[str, Any] = {"ts": {"$gte": since}}
    if service:
        esc = re.escape(service)
        match["$or"] = [
            {"meta.service": service},
            {"meta.service": {"$regex": esc, "$options": "i"}},          # prefix/contains (MARTECH→eis_marTech)
            {"meta.system": {"$regex": f"^\\s*{esc}\\s*$", "$options": "i"}},  # system tiles (handles ' UNIPAY')
        ]
    group_id: Any = {"$dateTrunc": {"date": "$ts", "unit": "second", "binSize": 5}}
    if not service:
        group_id = {"bucket": {"$dateTrunc": {"date": "$ts", "unit": "second", "binSize": 5}},
                    "service": "$meta.service"}
    pipe = [
        {"$match": match},
        {"$group": {
            "_id": group_id,
            "p50": {"$percentile": {"input": "$durationMs", "p": [0.5], "method": "approximate"}},
            "p95": {"$percentile": {"input": "$durationMs", "p": [0.95], "method": "approximate"}},
            "count": {"$sum": 1},
            "errors": {"$sum": {"$cond": [
                {"$or": [{"$eq": ["$transportOk", False]}, {"$eq": ["$businessOk", False]}]}, 1, 0]}},
        }},
        {"$project": {
            "_id": 0,
            "bucketTs": ("$_id" if service else "$_id.bucket"),
            "service": ("$$REMOVE" if service else "$_id.service"),
            "p50": {"$round": [{"$arrayElemAt": ["$p50", 0]}, 0]},
            "p95": {"$round": [{"$arrayElemAt": ["$p95", 0]}, 0]},
            "count": 1,
            "errorRate": {"$round": [{"$cond": [{"$eq": ["$count", 0]}, 0,
                          {"$divide": ["$errors", "$count"]}]}, 3]},
        }},
        {"$sort": {"bucketTs": 1}},
    ]
    try:
        return [jsonable(d) for d in db[settings.C_METRICS].aggregate(pipe)]
    except Exception as e:
        return [{"__error__": str(e)[:200]}]


# --------------------------------------------------------------- memory
@router.get("/memory")
def memory() -> dict:
    db = get_db()
    mem = [jsonable(d) for d in db[settings.C_MEMORY].find().sort("createdAt", -1).limit(50)]
    return {"incidents": mem, "playbooks": store_mod.all_playbooks()}


# --------------------------------------------------------------- scenarios
@router.get("/scenarios")
def scenarios() -> list[dict]:
    out = []
    pattern = str(REPO_ROOT / "novasim" / "src" / "main" / "resources" / "scenarios" / "*.json")
    files = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(pattern)}
    for sid in SCENARIOS:
        meta: dict[str, Any] = {}
        if sid in files:
            try:
                with open(files[sid]) as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        out.append({
            "id": sid,
            "title": meta.get("title", sid),
            "faultClass": meta.get("faultClass"),
            "presenterNote": meta.get("presenterNote", ""),
            "description": meta.get("description", ""),
            "expectedOrigin": meta.get("expectedOrigin", ""),
            "decoy": meta.get("decoy", ""),
            "analyzes": meta.get("analyzes", []),
        })
    return out


@router.post("/scenarios/{scenario_id}/fire")
def fire(scenario_id: str) -> dict:
    get_db()[settings.C_STATE].update_one(
        {"_id": "sim:command"},
        {"$set": {"scenario": scenario_id, "ts": dt.datetime.now(dt.timezone.utc),
                  "nonce": int(time.time() * 1000)}},
        upsert=True,
    )
    bus.publish({"type": "log", "level": "info", "summary": f"scenario fired: {scenario_id}"})
    return {"ok": True, "scenario": scenario_id}


# --------------------------------------------------------------- feedback / learn
class Feedback(BaseModel):
    incidentKey: str
    verdict: str  # up | down
    note: str | None = None


@router.post("/feedback")
def feedback(fb: Feedback = Body(...)) -> dict:
    db = get_db()
    inc = db[settings.C_INCIDENTS].find_one({"incidentKey": fb.incidentKey})
    db[settings.C_FEEDBACK].insert_one({
        "incidentKey": fb.incidentKey, "verdict": fb.verdict, "note": fb.note,
        "ts": dt.datetime.now(dt.timezone.utc),
    })
    updated = None
    if inc:
        origin = inc.get("originComponent")
        err_cd = (inc.get("errCds") or [None])[0]
        route_key = f"route:{origin}:{err_cd}"
        updated = store_mod.apply_feedback(route_key, fb.verdict, fb.note)
    bus.publish({"type": "log", "level": "info",
                 "summary": f"feedback {fb.verdict} on {fb.incidentKey}"})
    return {"ok": True, "playbook": updated}


# --------------------------------------------------------------- SSE stream
@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    async def gen():
        async for event in bus.subscribe():
            if await request.is_disconnected():
                break
            yield sse_format(event)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
