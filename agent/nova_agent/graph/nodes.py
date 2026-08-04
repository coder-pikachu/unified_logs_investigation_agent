"""The nine RCA nodes. Deterministic nodes (intake/collect/correlate/verify/
persist) carry the analytical weight; LLM nodes (hypothesize/rca/recommend)
narrate and rank over evidence the code already established.

Each node emits SSE-shaped node events via the LangGraph stream writer and
appends a node_trace entry (reduced by operator.add in AgentState).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from ..config import settings
from ..db import get_db, jsonable, strip_oid
from .. import llm
from ..memory import recall as recall_mod
from ..memory import store as store_mod
from .prompts import GLOSSARY
from .state import AgentState

try:
    from langgraph.config import get_stream_writer
except Exception:  # pragma: no cover
    get_stream_writer = None  # type: ignore

BADGES = {
    "intake": "Change Streams",
    "collect": "Time Series",
    "correlate": "layered-status decode",
    "recall": "$rankFusion — Atlas Search + Vector Search (autoEmbed voyage-4-lite)",
    "persist": "Automated Embedding — no client code",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _writer():
    if get_stream_writer is None:
        return lambda _e: None
    try:
        return get_stream_writer()
    except Exception:
        return lambda _e: None


def _emit(state: AgentState, node: str, phase: str, ms: int | None = None,
          summary: str | None = None, **payload: Any) -> None:
    ev: dict[str, Any] = {"type": "node", "incidentKey": state.get("incident_key"),
                          "node": node, "phase": phase}
    if ms is not None:
        ev["ms"] = ms
    if summary is not None:
        ev["summary"] = summary
    if payload:
        ev["payload"] = payload
    _writer()(ev)


def _trace(node: str, t0: float, summary: str, pipeline: Any = None, **payload: Any) -> dict:
    entry = {"node": node, "name": node, "ms": int((time.time() - t0) * 1000),
             "summary": summary, "payload": payload, "endedAt": _now().isoformat()}
    if pipeline is not None:
        entry["pipeline"] = pipeline
    return entry


# rough blended Grove pricing for the live cost meter (USD per token)
_COST_IN = 0.15 / 1_000_000
_COST_OUT = 0.60 / 1_000_000


def _emit_token(state: AgentState, node: str, usage: dict) -> None:
    """Stream an LLM token/cost delta so the UI meter ticks live (SSE type:token)."""
    if not usage:
        return
    prompt = int(usage.get("prompt", 0))
    completion = int(usage.get("completion", 0))
    total = int(usage.get("total", prompt + completion))
    cost = round(prompt * _COST_IN + completion * _COST_OUT, 6)
    _writer()({"type": "token", "incidentKey": state.get("incident_key"), "node": node,
               "payload": {"tokens": total, "cost": cost}})


# ---------------------------------------------------------------- JSON decode

def _loads2(s: Any) -> Any:
    """Attempt up to 2 levels of JSON decode (handles double-encoded payloads)."""
    v = s
    for _ in range(2):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                break
        else:
            break
    return v


def _unwrap_err_dtls(s: Any) -> list[dict]:
    """Walk nested err_dtls to the innermost cause; return the code/message chain."""
    obj = _loads2(s)
    chain: list[dict] = []
    cur = obj
    depth = 0
    while isinstance(cur, dict) and depth < 8:
        code_key = None
        for k, val in cur.items():
            if isinstance(val, dict) and ("data" in val or "message" in val):
                code_key = k
                break
        if code_key is None:
            # leaf dict — capture any message/reason text
            msg = cur.get("message") or cur.get("responseReason")
            if msg and chain:
                chain[-1]["leaf"] = msg
            break
        node = cur[code_key]
        chain.append({"code": code_key, "message": node.get("message")})
        cur = node.get("data")
        depth += 1
    return chain


def _svc_business(srvc_rspn: Any) -> tuple[bool, Any]:
    """Classify business status from a service response payload. Returns (ok, code)."""
    obj = _loads2(srvc_rspn)
    if not isinstance(obj, dict):
        return True, None
    reason = obj.get("reason")
    if isinstance(reason, dict):
        rr = reason.get("responseReason")
        if rr and str(rr).lower() == "failure":
            return False, reason.get("complianceReason") or reason.get("responseCode")
    eis = obj.get("EIS_RESPONSE")
    if isinstance(eis, dict):
        if eis.get("success") is False:
            return False, eis.get("status_code")
        sc = eis.get("status_code")
        if isinstance(sc, int) and sc >= 400:
            return False, sc
    ec = obj.get("ERROR_CODE")
    if ec not in (None, "", "NULL"):
        return False, ec
    return True, None


def _transport_ok(trns_sts: Any) -> bool:
    return str(trns_sts).strip() not in ("-2", "error", "false", "False")


def _norm(s: Any) -> str:
    return str(s).strip() if s is not None else ""


_TECH_HINT = re.compile(
    r"transform|time ?out|connection|conn pool|pool|socket|unavailable|latency|"
    r"gateway|token|expir|5\d\d|refused|reset|handshake|tls|ssl|malformed|improper",
    re.I,
)


def _classify_fault(origin_evt: dict | None) -> tuple[str, str]:
    """Classify the ROOT CAUSE nature: technical (infra/integration/timeout/
    transformation/credential) vs business (rule/data/compliance). A downstream
    transport or transformation failure is technical even when it surfaces to the
    user as a business error."""
    if not origin_evt:
        return "unknown", "no origin identified"
    ec = str(origin_evt.get("errCd") or "")
    note = str(origin_evt.get("note") or "")
    et = str(origin_evt.get("errType") or "")
    if et == "TECHNICAL_EXCEPTION":
        return "technical", "origin error typed TECHNICAL_EXCEPTION"
    if re.match(r"^TE", ec, re.I):
        return "technical", f"technical error code {ec}"
    if re.fullmatch(r"\d+", ec) and ec not in ("200", "0", "1"):
        return "technical", f"legacy technical exception code {ec}"
    if origin_evt.get("transportStatus") == "fail":
        return "technical", "transport-layer / integration failure"
    if _TECH_HINT.search(note):
        return "technical", "technical failure signature in the dependency response"
    if re.match(r"^BS", ec, re.I) or origin_evt.get("businessStatus") == "fail":
        return "business", f"business rule / data / compliance failure ({ec or 'business-fail'})"
    return "mixed", "indeterminate — inspect the evidence"


# ---------------------------------------------------------------- 1. intake

def intake(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "intake", "start", badge=BADGES["intake"])
    trig = state.get("trigger", {}) or {}
    key = state.get("incident_key") or trig.get("incident_key") or trig.get("incidentKey")
    trns_ids = list(dict.fromkeys(state.get("trns_ids") or trig.get("trns_ids") or []))
    sessn = list(dict.fromkeys(state.get("sessn_tkn_ids") or trig.get("sessn_tkn_ids") or []))

    db = get_db()
    db[settings.C_INCIDENTS].update_one(
        {"incidentKey": key},
        {"$set": {"status": "analyzing", "trnsIds": trns_ids, "sessnTknIds": sessn,
                  "updatedAt": _now()},
         "$setOnInsert": {"incidentKey": key, "createdAt": _now()}},
        upsert=True,
    )
    summary = f"intake: incident {key}, {len(trns_ids)} trns, {len(sessn)} sessions"
    _emit(state, "intake", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge=BADGES["intake"])
    return {"incident_key": key, "trns_ids": trns_ids, "sessn_tkn_ids": sessn,
            "iteration": 0, "started_ts": time.time(),
            "node_trace": [_trace("intake", t0, summary, badge=BADGES["intake"])]}


# ---------------------------------------------------------------- 2. collect

def _route_of(svc: dict) -> str:
    url = svc.get("api_url") or ""
    # route = last two path segments (the wrapper route), else srvc_id
    try:
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        segs = [p for p in path.split("/") if p]
        return "/".join(segs[-3:]) if segs else svc.get("srvc_id", "")
    except Exception:
        return svc.get("srvc_id", "")


def _route_metrics(key: str, first_at: dt.datetime, window_s: float) -> dict | None:
    """Baseline-vs-incident p95/err-rate for one service. Matches meta.service
    (srvc_id — unambiguous) OR meta.route so both the generator's routeLabel
    convention and injected fixtures resolve."""
    db = get_db()
    inc_lo = first_at - dt.timedelta(seconds=window_s)
    inc_hi = first_at + dt.timedelta(seconds=window_s)
    base_lo = inc_lo - dt.timedelta(minutes=30)

    def agg(match: dict) -> dict | None:
        pipe = [
            {"$match": match},
            {"$group": {
                "_id": None,
                "p95": {"$percentile": {"input": "$durationMs", "p": [0.95], "method": "approximate"}},
                "errRate": {"$avg": {"$cond": [
                    {"$or": [{"$eq": ["$transportOk", False]}, {"$eq": ["$businessOk", False]}]}, 1, 0]}},
                "count": {"$sum": 1},
            }},
        ]
        r = list(db[settings.C_METRICS].aggregate(pipe))
        if not r:
            return None
        d = r[0]
        p95 = d.get("p95") or [0]
        return {"p95": float(p95[0]) if p95 else 0.0, "errRate": round(float(d.get("errRate", 0)), 3),
                "count": int(d.get("count", 0))}

    m = {"$or": [{"meta.service": key}, {"meta.route": key}]}
    inc = agg({**m, "ts": {"$gte": inc_lo, "$lte": inc_hi}})
    base = agg({**m, "ts": {"$gte": base_lo, "$lt": inc_lo}})
    if inc is None and base is None:
        return None
    return {"route": key, "incident": inc or {}, "baseline": base or {}}


def collect(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "collect", "start", badge=BADGES["collect"])
    db = get_db()
    trns_ids = state.get("trns_ids", [])
    it = state.get("iteration", 0)
    # widen the window on a verify-triggered second pass
    window_s = settings.collect_window_seconds * (2 if it >= 1 else 1)

    queries: list[dict] = []  # the literal filters run — surfaced on the incident page

    def q(collection: str, purpose: str, flt: dict,
          workload: str = "document store · indexed find") -> None:
        queries.append({"collection": collection, "purpose": purpose,
                        "workload": workload, "query": jsonable(flt)})

    # rung 1: everything on the trigger trns_ids (the correlation join)
    f1 = {"trns_id": {"$in": trns_ids}}
    q(settings.C_TXN, "join the cascade on trns_id (correlation key)", f1)
    q(settings.C_ERR, "join the cascade on trns_id (correlation key)", f1)
    q(settings.C_SVC, "join the cascade on trns_id (correlation key)", f1)
    txn = list(db[settings.C_TXN].find(f1).limit(200))
    err = list(db[settings.C_ERR].find(f1).limit(200))
    svc = list(db[settings.C_SVC].find(f1).limit(200))

    # anchor time = earliest error
    err_times = [d.get("err_time") or d.get("crtd_on") for d in err if d.get("err_time") or d.get("crtd_on")]
    svc_times = [d.get("strt_time") for d in svc if d.get("strt_time")]
    first_at = min(err_times + svc_times) if (err_times or svc_times) else _now()

    # rung 2: session context
    sessions = list(dict.fromkeys(
        [d.get("sessn_tkn_id") for d in (txn + err + svc) if d.get("sessn_tkn_id")]))
    lo = first_at - dt.timedelta(seconds=window_s)
    hi = first_at + dt.timedelta(seconds=window_s)

    # rung 3: same cmnd_id / srvc_id across sessions in the window
    cmnd_ids = list(dict.fromkeys([d.get("cmnd_id") for d in txn if d.get("cmnd_id")]))
    srvc_ids = list(dict.fromkeys([d.get("srvc_id") for d in svc if d.get("srvc_id")]))
    context_docs: list[dict] = []
    if srvc_ids:
        f3s = {"srvc_id": {"$in": srvc_ids}, "strt_time": {"$gte": lo, "$lte": hi}}
        q(settings.C_SVC, "widen: same downstream routes across ALL sessions (±window)", f3s)
        context_docs += list(db[settings.C_SVC].find(f3s).limit(300))
    if cmnd_ids:
        f3t = {"cmnd_id": {"$in": cmnd_ids}, "strt_time": {"$gte": lo, "$lte": hi}}
        q(settings.C_TXN, "widen: same journeys across ALL sessions (±window)", f3t)
        context_docs += list(db[settings.C_TXN].find(f3t).limit(300))

    # widen trns/session set from context
    for d in context_docs:
        if d.get("trns_id"):
            trns_ids = list(dict.fromkeys(trns_ids + [d["trns_id"]]))
        if d.get("sessn_tkn_id"):
            sessions = list(dict.fromkeys(sessions + [d["sessn_tkn_id"]]))

    # rung 4: time-series baseline per downstream service (meta.service = srvc_id)
    svc_keys = list(dict.fromkeys(
        [d.get("srvc_id") for d in svc + [c for c in context_docs if "srvc_id" in c] if d.get("srvc_id")]))[:8]
    metrics = {k: m for k in svc_keys if (m := _route_metrics(k, first_at, window_s))}
    if svc_keys:
        q(settings.C_METRICS, "p95/err-rate: incident window vs 30-min baseline ($percentile)",
          {"$or": [{"meta.service": {"$in": svc_keys}}, {"meta.route": {"$in": svc_keys}}],
           "ts": {"$gte": lo, "$lte": hi}},
          workload="TIME SERIES · bucketed ts-range scan + $percentile aggregation")

    total = len(txn) + len(err) + len(svc) + len(context_docs)
    summary = (f"collected {total} docs across 3 collections + {len(metrics)} service baselines "
               f"(window ±{int(window_s)}s, {len(sessions)} sessions)")
    _emit(state, "collect", "progress", summary=summary)
    _emit(state, "collect", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge=BADGES["collect"])
    return {"txn_docs": strip_oid(txn), "err_docs": strip_oid(err), "svc_docs": strip_oid(svc),
            "context_docs": strip_oid(context_docs),
            "metrics_baseline": {"first_at": first_at.isoformat(), "window_s": window_s, "routes": metrics},
            "collect_queries": queries,
            "sessn_tkn_ids": sessions, "trns_ids": trns_ids,
            "node_trace": [_trace("collect", t0, summary, badge=BADGES["collect"], docCount=total)]}


# ---------------------------------------------------------------- 3. correlate

def _source_app(evt: dict) -> str:
    """Which simulated Java service wrote this document (multi-service story)."""
    if evt.get("collection") in (settings.C_TXN, settings.C_ERR):
        return "NOVA App"  # journey tier (Log4j2 -> audit_transaction/audit_error)
    s = str(evt.get("system") or "").strip().upper()
    if s.startswith("EIS"):
        return "EIS Gateway"
    if "UNIPAY" in s:
        return "UNIPAY BBPS"
    return s.title() or "Downstream"


def build_correlation(timeline: list[dict]) -> dict:
    """How the cross-collection join happened — surfaced verbatim in the UI."""
    services: dict[str, dict] = {}
    collections: dict[str, int] = {}
    trns = set()
    for e in timeline:
        app = e.get("sourceApp") or _source_app(e)
        coll = e.get("collection") or "?"
        svc = services.setdefault(app, {"name": app, "collections": [], "docs": 0})
        svc["docs"] += 1
        if coll not in svc["collections"]:
            svc["collections"].append(coll)
        collections[coll] = collections.get(coll, 0) + 1
        if e.get("trnsId"):
            trns.add(e["trnsId"])
    return {"joinKeys": {"trns_id": len(trns), "sessn_tkn_id": 0},
            "services": sorted(services.values(), key=lambda s: -s["docs"]),
            "collections": collections, "totalDocs": len(timeline)}


def correlate(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "correlate", "start", badge=BADGES["correlate"])
    txn = state.get("txn_docs", []) + [c for c in state.get("context_docs", []) if "cmnd_id" in c]
    err = state.get("err_docs", [])
    svc = state.get("svc_docs", []) + [c for c in state.get("context_docs", []) if "srvc_id" in c]

    # de-dup by _id
    def dedup(docs):
        seen, out = set(), []
        for d in docs:
            i = str(d.get("_id"))
            if i not in seen:
                seen.add(i)
                out.append(d)
        return out
    txn, err, svc = dedup(txn), dedup(err), dedup(svc)

    # journey lookup by trns_id
    journey_of = {d.get("trns_id"): d.get("cmnd_id") for d in txn}
    timeline: list[dict] = []

    for d in txn:
        ok = _norm(d.get("trns_stts")) != "error"
        timeline.append({
            "ts": d.get("strt_time"), "seq": d.get("seq", 0), "trnsId": d.get("trns_id"),
            "journey": d.get("cmnd_id"), "system": d.get("channel") or "app", "srvcId": None,
            "errCd": None, "businessStatus": "ok" if ok else "fail", "transportStatus": "ok",
            "decodedErrorChain": [], "durationMs": _dur(d), "note": "journey call",
            "_id": str(d.get("_id")), "collection": settings.C_TXN,
        })
    for d in svc:
        t_ok = _transport_ok(d.get("trns_sts"))
        b_ok, b_code = _svc_business(d.get("srvc_rspn"))
        timeline.append({
            "ts": d.get("strt_time"), "seq": d.get("seq", 0), "trnsId": d.get("trns_id"),
            "journey": journey_of.get(d.get("trns_id")), "system": _norm(d.get("systm_nm")),
            "srvcId": d.get("srvc_id"), "errCd": _norm(d.get("err_cd")) or (str(b_code) if b_code else None),
            "businessStatus": "ok" if b_ok else "fail", "transportStatus": "ok" if t_ok else "fail",
            "decodedErrorChain": [], "durationMs": _dur(d), "note": d.get("err_msg") or "downstream call",
            "route": _route_of(d), "apiUrl": d.get("api_url"),
            "_id": str(d.get("_id")), "collection": settings.C_SVC,
        })
    for d in err:
        chain = _unwrap_err_dtls(d.get("err_dtls"))
        timeline.append({
            "ts": d.get("err_time") or d.get("crtd_on"), "seq": d.get("seq", 0),
            "trnsId": d.get("trns_id"), "journey": journey_of.get(d.get("trns_id")),
            "system": "app", "srvcId": None, "errCd": _norm(d.get("err_cd")),
            "businessStatus": "fail", "transportStatus": "ok",
            "decodedErrorChain": chain, "durationMs": None,
            "note": (d.get("err_dscrptn") or "")[:160], "errType": d.get("err_typ"),
            "_id": str(d.get("_id")), "collection": settings.C_ERR,
        })

    # order by (strt_time, seq); tolerate None ts
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

    def _ts(e):
        v = e.get("ts")
        if isinstance(v, dt.datetime):
            return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
        return epoch
    timeline.sort(key=lambda e: (_ts(e), e.get("seq", 0)))
    for e in timeline:
        e["sourceApp"] = _source_app(e)

    # anomalies = business or transport failures
    anomalies = [e for e in timeline if e["businessStatus"] == "fail" or e["transportStatus"] == "fail"]

    # loudest = journey-side error code with highest count
    err_counter = Counter(e["errCd"] for e in timeline
                          if e["errCd"] and e["collection"] == settings.C_ERR)
    loudest_code, loudest_n = (err_counter.most_common(1)[0] if err_counter else (None, 0))
    loudest_journeys = list(dict.fromkeys(
        e["journey"] for e in timeline if e["errCd"] == loudest_code and e["journey"]))

    # origin = earliest downstream (audit_service) failure; falls back to earliest anomaly
    svc_anoms = [e for e in anomalies if e["collection"] == settings.C_SVC]
    origin_evt = (svc_anoms[0] if svc_anoms else (anomalies[0] if anomalies else None))
    origin = None
    if origin_evt:
        origin = {
            "srvcId": origin_evt.get("srvcId"), "system": origin_evt.get("system"),
            "route": origin_evt.get("route") or origin_evt.get("journey"),
            "apiUrl": origin_evt.get("apiUrl"), "errCd": origin_evt.get("errCd"),
            "firstAt": _ts(origin_evt).isoformat(), "docId": origin_evt.get("_id"),
            "distinctFromLoudest": (origin_evt.get("srvcId") or "") not in loudest_journeys,
            "loudest": {"code": loudest_code, "count": loudest_n, "journeys": loudest_journeys},
            "faultClass": _classify_fault(origin_evt)[0],
            "faultReason": _classify_fault(origin_evt)[1],
            "why": "earliest downstream failure; loud journey errors are downstream symptoms",
        }

    # signatures: srvcId/journey + errCd, with session/user spread
    sig_map: dict[str, dict] = {}
    for e in anomalies:
        comp = e.get("srvcId") or e.get("journey") or "unknown"
        sig = f"{comp}:{e.get('errCd')}"
        s = sig_map.setdefault(sig, {"signature": sig, "component": comp, "errCd": e.get("errCd"),
                                     "count": 0, "sessions": set(), "trns": set()})
        s["count"] += 1
        if e.get("trnsId"):
            s["trns"].add(e["trnsId"])
    session_of = {d.get("trns_id"): d.get("sessn_tkn_id") for d in (txn + svc + err)}
    signatures = []
    for s in sig_map.values():
        sess = {session_of.get(t) for t in s["trns"] if session_of.get(t)}
        signatures.append({"signature": s["signature"], "component": s["component"], "errCd": s["errCd"],
                           "count": s["count"], "sessionCount": len(sess), "trnsCount": len(s["trns"])})
    signatures.sort(key=lambda x: x["count"], reverse=True)

    systems = list(dict.fromkeys(_norm(e["system"]) for e in timeline if e.get("system")))
    journeys = list(dict.fromkeys(e["journey"] for e in timeline if e.get("journey")))

    summary = (f"correlated {len(timeline)} events; {len(anomalies)} anomalies; "
               f"origin={origin['srvcId'] if origin else '?'} vs loudest={loudest_code}")
    _emit(state, "correlate", "progress", summary=summary,
          originDistinctFromLoudest=bool(origin and origin["distinctFromLoudest"]))
    _emit(state, "correlate", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge=BADGES["correlate"])
    return {"timeline": timeline, "origin_candidate": origin, "systems_involved": systems,
            "journeys_involved": journeys, "signatures": signatures,
            "node_trace": [_trace("correlate", t0, summary, badge=BADGES["correlate"],
                                  events=len(timeline), anomalies=len(anomalies))]}


def _dur(d: dict) -> int | None:
    s, e = d.get("strt_time"), d.get("end_time")
    if isinstance(s, dt.datetime) and isinstance(e, dt.datetime):
        return int((e - s).total_seconds() * 1000)
    return None


# ---------------------------------------------------------------- 4. recall

def _narrative(state: AgentState) -> str:
    origin = state.get("origin_candidate") or {}
    journeys = ", ".join(state.get("journeys_involved", [])[:5])
    sigs = "; ".join(s["signature"] for s in state.get("signatures", [])[:4])
    return (f"Origin {origin.get('srvcId')} on {origin.get('system')} route "
            f"{origin.get('route')} errCd {origin.get('errCd')}. Journeys: {journeys}. "
            f"Failure signatures: {sigs}.")


def recall(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "recall", "start", badge=BADGES["recall"])
    origin = state.get("origin_candidate") or {}
    err_cds = list(dict.fromkeys(
        [s.get("errCd") for s in state.get("signatures", []) if s.get("errCd")]))
    srvc_ids = list(dict.fromkeys(
        [s.get("component") for s in state.get("signatures", []) if s.get("component")]))
    narrative = _narrative(state)

    res = recall_mod.recall(narrative, err_cds, srvc_ids)
    route_key = f"route:{origin.get('srvcId')}:{origin.get('errCd')}"
    playbook = store_mod.get_playbook(route_key)

    recalled_incidents = [{"incidentKey": d.get("incidentKey"), "score": d.get("score"),
                           "summary_text": d.get("summary_text")}
                          for d in res["incidents"]["fused"]]
    recalled_kb = [{"title": d.get("title"), "score": d.get("score")} for d in res["kb"]["fused"]]

    summary = (f"hybrid recall: {len(recalled_incidents)} incidents, {len(recalled_kb)} kb; "
               f"vectorTop={res['incidents']['vectorTop']:.2f}; "
               f"hit={res['hit']}; playbook={'yes' if playbook else 'no'}")
    _emit(state, "recall", "progress", summary=summary,
          arms={"incident": res["incidents"], "kb": res["kb"]},
          pipelines=res["pipelines"], threshold=res["threshold"])
    _emit(state, "recall", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge=BADGES["recall"])
    literal_pipeline = {
        "incident_memory": [{"$rankFusion": {
            "input": {"pipelines": {
                "vector": [{"$vectorSearch": {"index": settings.IDX_MEM_VECTOR, "path": "summary_text",
                                              "query": {"text": narrative[:100] + "…"},
                                              "numCandidates": 50, "limit": 5}}],
                "lexical": [{"$search": {"index": settings.IDX_MEM_SEARCH,
                                         "compound": {"should": "<err_cd/srvc_id exact tokens>"}}},
                            {"$limit": 5}],
            }},
            "combination": {"weights": {"vector": 1.0, "lexical": 1.0}}, "scoreDetails": True}}],
        "kb_docs": "same $rankFusion shape over kb_docs (path=body, indexes kb_docs_vector/kb_docs_search)",
    }
    return {"recalled_incidents": recalled_incidents, "recalled_kb": recalled_kb,
            "recall_arms": {"incident": jsonable(res["incidents"]), "kb": jsonable(res["kb"]),
                            "pipelines": res["pipelines"], "threshold": res["threshold"]},
            "recall_hit": bool(res["hit"]), "playbook": playbook,
            "node_trace": [_trace("recall", t0, summary, pipeline=literal_pipeline,
                                  badge=BADGES["recall"], hit=bool(res["hit"]))]}


def recall_route(state: AgentState) -> str:
    """Conditional edge after recall: a confident memory hit short-circuits the
    expensive hypothesize/verify/rca/recommend LLM path (claim #3 — run 2 is
    faster and cites the prior incident)."""
    warm = bool(state.get("recall_hit")) and bool(
        state.get("recalled_incidents") or (state.get("playbook") or {}).get("confirmedFixes"))
    return "warm" if warm else "cold"


def confirm(state: AgentState) -> dict:
    """Warm path: reuse the recalled incident + playbook to confirm a recurrence
    deterministically (no LLM), so run 2 short-circuits to a confident RCA."""
    t0 = time.time()
    _emit(state, "confirm", "start", badge="Agent memory — recurrence confirmed")
    db = get_db()
    origin = state.get("origin_candidate") or {}
    playbook = state.get("playbook") or {}
    recalled = state.get("recalled_incidents", [])
    prior_key = recalled[0]["incidentKey"] if recalled else None
    prior = db[settings.C_INCIDENTS].find_one({"incidentKey": prior_key}) if prior_key else None
    prior_rca = (prior or {}).get("rca") or {}

    conf = round(min(0.97, float(prior_rca.get("confidence", 0.8)) + 0.1), 3)
    rca_res = {
        "rootCause": prior_rca.get("rootCause") or f"Recurrence on {origin.get('srvcId')}.",
        "faultClass": prior_rca.get("faultClass") or origin.get("faultClass", "mixed"),
        "faultReason": prior_rca.get("faultReason") or origin.get("faultReason", ""),
        "causalChain": prior_rca.get("causalChain", []),
        "contributingFactors": prior_rca.get("contributingFactors", []),
        "evidence": [x for x in [origin.get("docId")] if x] + (prior_rca.get("evidence", [])[:1]),
        "confidence": conf,
        "unknowns": [],
        "recalledFrom": prior_key,
    }
    recs = (prior or {}).get("recommendations") or []
    if not recs and playbook.get("confirmedFixes"):
        recs = [{"tier": "fix", "action": playbook["confirmedFixes"][0],
                 "ownerSystem": origin.get("system") or "EIS", "effort": "M", "impact": "H"}]
    verifications = [{
        "hypothesis": "memory-confirmed recurrence", "implicatedComponent": origin.get("srvcId"),
        "score": conf,
        "checks": {"memory": {"recalledIncident": prior_key,
                              "playbookHits": playbook.get("seenCount"),
                              "playbookConfidence": playbook.get("confidence")}},
    }]
    summary = f"confirm: recurrence of {prior_key} (conf {conf}) — short-circuited via memory"
    _emit(state, "confirm", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge="Agent memory — recurrence confirmed")
    return {"rca": rca_res, "recommendations": recs, "verifications": verifications,
            "short_circuit": True,
            "node_trace": [_trace("confirm", t0, summary, recalledFrom=prior_key)]}


# ---------------------------------------------------------------- 5. hypothesize

class Hypothesis(BaseModel):
    statement: str = Field(description="candidate root cause, one sentence")
    implicatedComponent: str = Field(description="srvc_id / route / journey most implicated")
    citedDocIds: list[str] = Field(description="_id strings from the timeline that support this")
    rationale: str


class Hypotheses(BaseModel):
    hypotheses: list[Hypothesis]


def hypothesize(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "hypothesize", "start")
    origin = state.get("origin_candidate") or {}
    tl = state.get("timeline", [])
    valid_ids = {e["_id"] for e in tl}
    tl_brief = [{"_id": e["_id"], "ts": jsonable(e["ts"]), "journey": e["journey"],
                 "system": e["system"], "srvcId": e["srvcId"], "errCd": e["errCd"],
                 "businessStatus": e["businessStatus"], "transportStatus": e["transportStatus"],
                 "decodedErrorChain": e["decodedErrorChain"], "note": e["note"]}
                for e in tl if e["businessStatus"] == "fail" or e["transportStatus"] == "fail"][:40]

    playbook = state.get("playbook")
    recall_ctx = {"recalledIncidents": state.get("recalled_incidents", []),
                  "recalledKb": state.get("recalled_kb", []), "playbook": playbook}
    system = (f"You are an SRE root-cause analyst for the NOVA 2.0 banking platform. "
              f"{GLOSSARY}\nStatus fields lie: classify on BOTH transport and business status. "
              f"The loudest error is usually a downstream symptom, not the origin. "
              f"Every hypothesis MUST cite specific _id values from the provided timeline. "
              f"Propose 2-4 candidate root causes.")
    user = json.dumps({"origin_candidate": origin, "failing_timeline": tl_brief,
                       "recall": recall_ctx, "systems": state.get("systems_involved"),
                       "signatures": state.get("signatures")}, default=str)[:12000]

    errors: list[str] = []
    hyps: list[dict] = []
    usage = {"prompt": 0, "completion": 0, "total": 0}
    try:
        out, usage = llm.structured(Hypotheses, system, user, role="reasoning")
        for h in out.hypotheses:
            cited = [c for c in h.citedDocIds if c in valid_ids]
            if not cited:
                continue  # discard uncited hypotheses (guardrail)
            hyps.append({"statement": h.statement, "implicatedComponent": h.implicatedComponent,
                         "citedDocIds": cited, "rationale": h.rationale})
    except Exception as e:
        errors.append(f"hypothesize: {e}")

    if not hyps and origin:  # deterministic fallback so verify always has something
        seed = [e["_id"] for e in tl if e.get("srvcId") == origin.get("srvcId")][:3]
        hyps.append({"statement": f"{origin.get('srvcId')} degradation on route {origin.get('route')} "
                                  f"is the origin; downstream journeys fail as symptoms.",
                     "implicatedComponent": origin.get("srvcId") or origin.get("route"),
                     "citedDocIds": seed or [origin.get("docId")], "rationale": "deterministic origin seed"})

    summary = f"hypothesize: {len(hyps)} cited candidates"
    _emit_token(state, "hypothesize", usage)
    _emit(state, "hypothesize", "end", ms=int((time.time() - t0) * 1000), summary=summary)
    return {"hypotheses": hyps, "token_usage": usage,
            "errors": errors,
            "node_trace": [_trace("hypothesize", t0, summary, count=len(hyps))]}


# ---------------------------------------------------------------- 6. verify

def verify(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "verify", "start")
    db = get_db()
    origin = state.get("origin_candidate") or {}
    mb = state.get("metrics_baseline", {})
    first_at = mb.get("first_at")
    window_s = mb.get("window_s", settings.collect_window_seconds)
    try:
        anchor = dt.datetime.fromisoformat(first_at) if first_at else _now()
    except Exception:
        anchor = _now()
    lo = anchor - dt.timedelta(seconds=window_s)
    hi = anchor + dt.timedelta(seconds=window_s)

    verifications = []
    for h in state.get("hypotheses", []):
        comp = h.get("implicatedComponent")
        # incidence check: distinct users hitting the implicated component OR the
        # deterministic origin service in the window (robust to LLM component phrasing)
        candidates = [c for c in {comp, origin.get("srvcId")} if c]
        pipe_incidence = [
            {"$match": {"srvc_id": {"$in": candidates}, "strt_time": {"$gte": lo, "$lte": hi}}},
            {"$group": {"_id": "$usr_id"}},
            {"$count": "distinctUsers"},
        ]
        try:
            r = list(db[settings.C_SVC].aggregate(pipe_incidence))
            distinct_users = r[0]["distinctUsers"] if r else 0
        except Exception:
            distinct_users = 0

        route_metrics = (mb.get("routes") or {})
        rm = next((v for k, v in route_metrics.items()
                   if any(c and c in k for c in candidates)), None) \
            or route_metrics.get(origin.get("route")) \
            or (next(iter(route_metrics.values()), None) if route_metrics else None)
        p95_inc = (rm or {}).get("incident", {}).get("p95", 0)
        p95_base = (rm or {}).get("baseline", {}).get("p95", 0)
        latency_regression = bool(p95_base and p95_inc >= max(1.5 * p95_base, p95_base + 1000))

        # precursor check: any ops/config txn on the component in the prior 10 min
        pipe_precursor = [
            {"$match": {"cmnd_id": {"$regex": "^ops_"},
                        "strt_time": {"$gte": anchor - dt.timedelta(minutes=10), "$lt": anchor}}},
            {"$project": {"_id": 1, "cmnd_id": 1, "strt_time": 1}},
            {"$limit": 5},
        ]
        try:
            precursors = jsonable(list(db[settings.C_TXN].aggregate(pipe_precursor)))
        except Exception:
            precursors = []

        score = 0.0
        if distinct_users >= 2:
            score += 0.45
        elif distinct_users == 1:
            score += 0.15
        if latency_regression:
            score += 0.35
        if precursors:
            score += 0.2
        if any(c in valid_id_set(state) for c in h.get("citedDocIds", [])):
            score += 0.0  # citations already required; no double count
        score = round(min(1.0, score), 3)

        verifications.append({
            "hypothesis": h["statement"], "implicatedComponent": comp, "score": score,
            "checks": {
                "incidence": {"pipeline": jsonable(pipe_incidence), "distinctUsers": distinct_users,
                              "collection": settings.C_SVC},
                "latency": {"p95IncidentMs": p95_inc, "p95BaselineMs": p95_base,
                            "regression": latency_regression},
                "precursor": {"pipeline": jsonable(pipe_precursor), "found": precursors},
            },
        })

    verifications.sort(key=lambda v: v["score"], reverse=True)
    best = verifications[0]["score"] if verifications else 0.0
    it = state.get("iteration", 0)
    summary = f"verify: {len(verifications)} checked; best score {best:.2f}; iteration {it}"
    _emit(state, "verify", "progress", summary=summary,
          pipelines=[v["checks"] for v in verifications[:1]])
    _emit(state, "verify", "end", ms=int((time.time() - t0) * 1000), summary=summary)
    top_checks = verifications[0]["checks"] if verifications else {}
    verify_pipeline = {
        "incidence": (top_checks.get("incidence") or {}).get("pipeline"),
        "precursor": (top_checks.get("precursor") or {}).get("pipeline"),
    }
    return {"verifications": verifications, "iteration": it + 1,
            "node_trace": [_trace("verify", t0, summary, pipeline=verify_pipeline, bestScore=best)]}


def valid_id_set(state: AgentState) -> set:
    return {e["_id"] for e in state.get("timeline", [])}


def verify_route(state: AgentState) -> str:
    """Conditional edge: loop back to collect once if everything failed."""
    vers = state.get("verifications", [])
    best = vers[0]["score"] if vers else 0.0
    if best < 0.34 and state.get("iteration", 0) < 2:
        return "collect"
    return "rca"


# ---------------------------------------------------------------- 7. rca

class RCA(BaseModel):
    rootCause: str
    faultClass: str = Field(
        description="'technical' or 'business': is the ROOT CAUSE a technical/infrastructure/"
        "integration failure (transformation, timeout, credential/token, connection pool, malformed "
        "response) or a business-rule/data/compliance failure? A downstream technical failure is "
        "TECHNICAL even when it surfaces to the user as a business error.")
    faultReason: str = Field(description="one short clause justifying faultClass")
    causalChain: list[str]
    contributingFactors: list[str]
    evidence: list[str] = Field(description="_id strings that substantiate the root cause")
    confidence: float = Field(ge=0.0, le=1.0)
    unknowns: list[str]


def rca(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "rca", "start")
    vers = state.get("verifications", [])
    best = vers[0] if vers else None
    valid_ids = valid_id_set(state)

    origin = state.get("origin_candidate") or {}
    det_fault = origin.get("faultClass", "mixed")
    system = (f"You are the lead RCA analyst. {GLOSSARY}\n"
              f"State the single most-supported root cause. Cite ONLY _id values that appear in the "
              f"evidence. If the best verification score is weak (<0.34), be honest: say what could NOT "
              f"be determined in `unknowns` rather than fabricating. Origin must be the upstream cause, "
              f"not the loudest downstream symptom.\n"
              f"Also classify `faultClass`: 'technical' vs 'business'. A downstream transformation, "
              f"timeout, credential/token, connection-pool, or malformed-response failure is TECHNICAL "
              f"even if the user-facing error is a business code. A rule/eligibility/compliance/data "
              f"desync is 'business'. The deterministic pre-classification is '{det_fault}' — agree "
              f"unless the evidence clearly says otherwise.")
    user = json.dumps({"origin_candidate": origin,
                       "verifications": vers, "signatures": state.get("signatures"),
                       "recalledIncidents": state.get("recalled_incidents"),
                       "playbook": state.get("playbook"),
                       "metrics": state.get("metrics_baseline", {}).get("routes")}, default=str)[:12000]

    usage = {"prompt": 0, "completion": 0, "total": 0}
    errors: list[str] = []
    try:
        out, usage = llm.structured(RCA, system, user, role="reasoning")
        evidence = [e for e in out.evidence if e in valid_ids] or (
            best["hypothesis"] and [c for c in _cited_for(state, best)] or [])
        fc = out.faultClass.strip().lower()
        if fc not in ("technical", "business", "mixed"):
            fc = det_fault
        result = {"rootCause": out.rootCause, "faultClass": fc, "faultReason": out.faultReason,
                  "causalChain": out.causalChain,
                  "contributingFactors": out.contributingFactors, "evidence": evidence,
                  "confidence": round(float(out.confidence), 3), "unknowns": out.unknowns}
    except Exception as e:
        errors.append(f"rca: {e}")
        result = {"rootCause": "Insufficient evidence to determine a confident root cause.",
                  "faultClass": det_fault, "faultReason": origin.get("faultReason", ""),
                  "causalChain": [], "contributingFactors": [],
                  "evidence": list(valid_ids)[:3], "confidence": 0.2,
                  "unknowns": ["LLM synthesis failed; see verifications for raw evidence."]}

    summary = f"rca: {result['rootCause'][:70]} (conf {result['confidence']})"
    _emit_token(state, "rca", usage)
    _emit(state, "rca", "end", ms=int((time.time() - t0) * 1000), summary=summary)
    return {"rca": result, "token_usage": usage, "errors": errors,
            "node_trace": [_trace("rca", t0, summary, confidence=result["confidence"])]}


def _cited_for(state: AgentState, best: dict) -> list[str]:
    for h in state.get("hypotheses", []):
        if h["statement"] == best.get("hypothesis"):
            return h.get("citedDocIds", [])
    return []


# ---------------------------------------------------------------- 8. recommend

class Recommendation(BaseModel):
    tier: str = Field(description="immediate | fix | prevention")
    action: str
    ownerSystem: str
    effort: str = Field(description="S | M | L")
    impact: str = Field(description="H | M | L")


class Recommendations(BaseModel):
    recommendations: list[Recommendation]


def recommend(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "recommend", "start")
    rca_res = state.get("rca") or {}
    origin = state.get("origin_candidate") or {}
    system = (f"You are an SRE proposing fixes. {GLOSSARY}\n"
              f"Return exactly three recommendations, one per tier: immediate mitigation, the fix "
              f"(name the route/config/contract), and prevention (the alert or test that should have "
              f"caught it — often a service_metrics threshold). Be concrete and owner-attributed.")
    user = json.dumps({"rca": rca_res, "origin": origin,
                       "systems": state.get("systems_involved")}, default=str)[:8000]

    usage = {"prompt": 0, "completion": 0, "total": 0}
    errors: list[str] = []
    recs: list[dict] = []
    try:
        out, usage = llm.structured(Recommendations, system, user, role="fast")
        recs = [r.model_dump() for r in out.recommendations]
    except Exception as e:
        errors.append(f"recommend: {e}")
        recs = [{"tier": "immediate", "action": f"Circuit-break {origin.get('srvcId')} and degrade the "
                 f"dependent journeys gracefully.", "ownerSystem": origin.get("system") or "EIS",
                 "effort": "S", "impact": "H"}]

    summary = f"recommend: {len(recs)} tiers"
    _emit_token(state, "recommend", usage)
    _emit(state, "recommend", "end", ms=int((time.time() - t0) * 1000), summary=summary)
    return {"recommendations": recs, "token_usage": usage, "errors": errors,
            "node_trace": [_trace("recommend", t0, summary, count=len(recs))]}


# ---------------------------------------------------------------- 9. persist

def persist(state: AgentState) -> dict:
    t0 = time.time()
    _emit(state, "persist", "start", badge=BADGES["persist"])
    db = get_db()
    key = state.get("incident_key")
    origin = state.get("origin_candidate") or {}
    rca_res = state.get("rca") or {}
    tl = state.get("timeline", [])
    mb = state.get("metrics_baseline", {})
    routes = mb.get("routes", {})
    rm = (routes.get(origin.get("srvcId")) or routes.get(origin.get("route"))
          or (next(iter(routes.values()), {}) if routes else {}))

    # blast radius
    journeys = state.get("journeys_involved", [])
    channels = list(dict.fromkeys(d.get("chnl_id") for d in state.get("txn_docs", []) if d.get("chnl_id")))
    users = {d.get("usr_id") for d in (state.get("txn_docs", []) + state.get("svc_docs", []))
             if d.get("usr_id")}

    first_err_at = None
    for e in tl:
        if e["businessStatus"] == "fail" or e["transportStatus"] == "fail":
            first_err_at = e.get("ts")
            break

    err_cds = list(dict.fromkeys(e["errCd"] for e in tl if e.get("errCd")))
    started = state.get("started_ts", time.time())

    # incident_memory: distilled text only — Atlas Automated Embedding vectorizes it (no client)
    summary_text = (f"{rca_res.get('rootCause', '')} Origin {origin.get('srvcId')} on "
                    f"{origin.get('system')} route {origin.get('route')}. "
                    f"Journeys affected: {', '.join(journeys[:6])}. "
                    f"Error codes: {', '.join(err_cds[:6])}. "
                    f"Causal chain: {' -> '.join(rca_res.get('causalChain', [])[:4])}.")
    db[settings.C_MEMORY].update_one(
        {"incidentKey": key},
        {"$set": {"incidentKey": key, "summary_text": summary_text, "err_cds": err_cds,
                  "srvc_ids": [origin.get("srvcId")] if origin.get("srvcId") else [],
                  "journeys": journeys, "createdAt": _now(), "sourceIncidentKey": key}},
        upsert=True,
    )

    # playbook upsert (long-term store) — the learn substrate
    route_key = f"route:{origin.get('srvcId')}:{origin.get('errCd')}"
    signature = state.get("signatures", [{}])[0].get("signature", route_key) if state.get("signatures") else route_key
    fix = next((r["action"] for r in state.get("recommendations", []) if r.get("tier") == "fix"), None)
    playbook = store_mod.upsert_playbook(route_key, signature, confirmed_fix=fix)

    summary = f"persist: incident {key} complete; memory + playbook (seen {playbook.get('seenCount')})"
    persist_trace = _trace("persist", t0, summary, badge=BADGES["persist"],
                           playbookHits=playbook.get("seenCount"))
    node_trace_full = state.get("node_trace", []) + [persist_trace]
    # Which collections the agent actually queried, and their role — surfaced in the UI
    ctx = state.get("context_docs", [])
    routes = (state.get("metrics_baseline", {}) or {}).get("routes", {})
    collections_analyzed = [
        {"collection": settings.C_TXN, "role": "journey / API calls",
         "examined": len(state.get("txn_docs", [])) + sum(1 for c in ctx if "cmnd_id" in c)},
        {"collection": settings.C_ERR, "role": "error events",
         "examined": len(state.get("err_docs", []))},
        {"collection": settings.C_SVC, "role": "downstream / dependency calls",
         "examined": len(state.get("svc_docs", [])) + sum(1 for c in ctx if "srvc_id" in c)},
        {"collection": settings.C_METRICS, "role": "time-series baseline (p95 vs 30-min)",
         "examined": len(routes)},
        {"collection": settings.C_MEMORY, "role": "prior incidents (hybrid $rankFusion)",
         "examined": len(state.get("recalled_incidents", []))},
        {"collection": settings.C_KB, "role": "runbooks (hybrid $rankFusion)",
         "examined": len(state.get("recalled_kb", []))},
        {"collection": settings.C_STORE, "role": "route playbook (long-term memory)",
         "examined": 1 if state.get("playbook") else 0},
    ]
    correlation = build_correlation(tl)
    correlation["joinKeys"]["sessn_tkn_id"] = len(state.get("sessn_tkn_ids", []))

    # Every MongoDB query the agent fired for this investigation, in order —
    # correlation joins, the time-series baseline, hybrid recall, verification.
    agent_queries = list(state.get("collect_queries", []))
    for nt in state.get("node_trace", []):
        if (nt.get("node") or nt.get("name")) == "recall" and nt.get("pipeline") is not None:
            agent_queries.append({
                "collection": f"{settings.C_MEMORY} + {settings.C_KB}",
                "purpose": "hybrid recall of similar incidents + runbooks",
                "workload": "$rankFusion — Vector Search (autoEmbed) + Atlas Search",
                "query": jsonable(nt["pipeline"])})
            break
    for v in (state.get("verifications") or [])[:1]:
        checks = v.get("checks") or {}
        inc_p = (checks.get("incidence") or {}).get("pipeline")
        if inc_p:
            agent_queries.append({"collection": settings.C_SVC,
                                  "purpose": "verify: distinct users hitting the implicated component",
                                  "workload": "aggregation · $group distinct usr_id",
                                  "query": jsonable(inc_p)})
        pre_p = (checks.get("precursor") or {}).get("pipeline")
        if pre_p:
            agent_queries.append({"collection": settings.C_TXN,
                                  "purpose": "verify: ops/config precursor in the prior 10 min",
                                  "workload": "aggregation · regex on cmnd_id",
                                  "query": jsonable(pre_p)})

    incident_doc = {
        "incidentKey": key, "status": "complete",
        "trnsIds": state.get("trns_ids", []), "sessnTknIds": state.get("sessn_tkn_ids", []),
        "firstErrorAt": first_err_at, "analyzedAt": _now(),
        "durationMs": int((time.time() - started) * 1000),
        "errCds": err_cds, "journeysInvolved": journeys, "systemsInvolved": state.get("systems_involved", []),
        "originComponent": origin.get("srvcId") or origin.get("route"),
        "originDocId": origin.get("docId"),
        "timeline": jsonable(tl),
        "metrics": {"p95BaselineMs": round((rm.get("baseline", {}) or {}).get("p95", 0)),
                    "p95IncidentMs": round((rm.get("incident", {}) or {}).get("p95", 0)),
                    "usersAffected": len(users)},
        "rca": rca_res,
        "faultClass": rca_res.get("faultClass"), "faultReason": rca_res.get("faultReason"),
        "collectionsAnalyzed": collections_analyzed,
        "correlation": correlation,
        "agentQueries": jsonable(agent_queries),
        "blastRadius": {"journeys": journeys, "channels": channels, "userCount": len(users)},
        "recommendations": state.get("recommendations", []),
        "recalledIncidents": state.get("recalled_incidents", []),
        "recalledKb": state.get("recalled_kb", []),
        "recallArms": state.get("recall_arms", {}),
        "verifications": jsonable(state.get("verifications", [])),
        "nodeTrace": jsonable(node_trace_full),
        "tokenUsage": state.get("token_usage", {}),
        "updatedAt": _now(),
    }
    db[settings.C_INCIDENTS].update_one({"incidentKey": key}, {"$set": incident_doc}, upsert=True)

    _emit(state, "persist", "progress", summary=summary, playbookHits=playbook.get("seenCount"))
    _emit(state, "persist", "end", ms=int((time.time() - t0) * 1000), summary=summary,
          badge=BADGES["persist"])
    _emit(state, "incident", "end", summary=f"incident {key} complete")
    return {"node_trace": [persist_trace]}
