"""Offline demo fallback (brief §10 trap #6 / guardrail #6).

Two modes, one file — and the serve path imports NOTHING that touches Atlas or
Grove, so it runs with networking fully disabled:

  python agent/replay.py --record [--scenario eis-martech-brownout]
      Drives the LIVE agent (SSE + REST) through one incident and captures the
      node-event stream (with relative timing) plus REST snapshots into
      data/replay/session.json.

  REPLAY_MODE=1 python agent/replay.py         (== `make replay`)
      Serves a FastAPI app on AGENT_PORT that re-streams the recorded SSE with
      original timing on /api/stream and answers every §5 REST endpoint from the
      fixture. The unmodified UI proxies /api to it. No MongoDB, no Grove.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Imported at module level so FastAPI can resolve the `Request` type hint on the
# closure endpoints below (get_type_hints reads module globals). Safe for
# --record too — importing FastAPI touches no network.
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "data" / "replay" / "session.json"
PORT = int(os.getenv("AGENT_PORT", "8000"))
BASE = f"http://localhost:{PORT}"


# --------------------------------------------------------------------- record
def record(scenario: str) -> None:
    """Capture a real run from the already-running live agent."""
    import threading
    import urllib.request
    import datetime as dt
    import random

    sys.path.insert(0, str(REPO_ROOT / "agent"))
    from nova_agent.db import get_db          # network — recording only
    from nova_agent.config import settings

    db = get_db()
    events: list[dict] = []
    t0 = time.time()
    stop = threading.Event()

    def reader():
        try:
            with urllib.request.urlopen(f"{BASE}/api/stream", timeout=90) as r:
                for raw in r:
                    if stop.is_set():
                        break
                    line = raw.decode().strip()
                    if line.startswith("data:"):
                        try:
                            events.append({"t": int((time.time() - t0) * 1000),
                                           "data": json.loads(line[5:].strip())})
                        except Exception:
                            pass
        except Exception:
            pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(2)

    # inject a deterministic brownout cascade (recording is allowed to use the DB)
    now = dt.datetime.now(dt.timezone.utc)
    api = "https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Martech/services"
    trns = []
    for i in range(3):
        ts = now + dt.timedelta(milliseconds=200 * i)
        tr = f"178342{random.randint(10**9, 10**10)}rec{i}"
        se = f"178342{random.randint(10**9, 10**10)}s{i}"
        uid = str(1730709013340810000 + i)
        trns.append(tr)
        db[settings.C_TXN].insert_one({"msg_id": 95000+i, "trns_id": tr, "sessn_tkn_id": se,
            "clnt_ip_addr": "10.191.199.66", "req_no": f"r{i}", "usr_rltnshp_no": "85002719907",
            "trns_stts": "error", "strt_time": ts, "end_time": ts + dt.timedelta(seconds=10),
            "usr_id": uid, "usr_typ": "ETB_CUSTOMER",
            "cmnd_id": "martech_hyper-personalization_offers_fetch", "chnl_id": 2001,
            "channel": "mobile", "biz_req_input": "{}", "biz_resp_output": "{}",
            "crtd_by": "TransAdtUser", "crtd_on": ts, "trace_id": "NULL", "nfrchk": "NULL", "seq": 1})
        db[settings.C_SVC].insert_one({"msg_id": 95200+i, "trns_id": tr, "sessn_tkn_id": se,
            "trns_sts": -2, "err_cd": "TEEIS009", "err_msg": "Response Transformation failed.",
            "usr_id": uid, "srvc_rqst": "{}",
            "srvc_rspn": '{"ERROR_CODE":"TEEIS009","EIS_RESPONSE":{"status_code":500,"success":false}}',
            "srvc_id": "eis_marTech_getInteractOffers", "systm_nm": "EIS", "api_url": api,
            "rqst_id_sent": "SBIY22", "rqst_id_rcvd": "SB41", "crtd_by": "ServiceAdtUser",
            "crtd_on": ts, "strt_time": ts, "end_time": ts + dt.timedelta(seconds=10), "seq": 1})
        db[settings.C_ERR].insert_one({"msg_id": 95400+i, "trns_id": tr, "sessn_tkn_id": se,
            "err_cd": "BS000001", "err_typ": "BUSINESS_EXCEPTION",
            "err_dscrptn": "Exception during offer fetch",
            "err_dtls": '{"BSYHP003":{"message":"CIF Is Not Recognized By Martech."}}',
            "crtd_by": "ErrorAdtUser", "crtd_on": ts, "err_time": ts + dt.timedelta(seconds=10),
            "usr_id": uid, "biz_err_cd_1": "BSYHP003",
            "biz_err_cd_1_msg": "CIF Is Not Recognized By Martech.",
            "biz_err_cd_2": "NULL", "biz_err_cd_3": "NULL", "biz_err_cd_4": "NULL", "biz_err_cd_5": "NULL",
            "biz_err_cd_2_msg": "NULL", "biz_err_cd_3_msg": "NULL", "biz_err_cd_4_msg": "NULL",
            "biz_err_cd_5_msg": "NULL", "seq": 2})

    # wait for the incident to complete on the stream (or time out)
    deadline = time.time() + 45
    while time.time() < deadline:
        if any(e["data"].get("type") == "incident" and e["data"].get("phase") == "complete"
               for e in events):
            break
        time.sleep(0.5)
    time.sleep(1)
    stop.set()

    def get(path):
        try:
            with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
                return json.loads(r.read())
        except Exception:
            return None

    incidents = get("/api/incidents") or []
    key = incidents[0]["incidentKey"] if incidents else None
    fixture = {
        "recordedAt": now.isoformat(),
        "scenario": scenario,
        "events": events,
        "snapshots": {
            "incidents": incidents,
            "incidentByKey": {key: get(f"/api/incidents/{key}")} if key else {},
            "memory": get("/api/memory") or {"incidents": [], "playbooks": []},
            "logsByTrns": {t: get(f"/api/logs?trnsId={t}") or [] for t in trns},
            "metricsByService": {s: get(f"/api/metrics?service={s}&window=15m") or []
                                 for s in ("eis_marTech_getInteractOffers", "EIS", "MARTECH",
                                           "martech_hyper-personalization")},
        },
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, default=str))
    print(f"recorded {len(events)} events + snapshots → {FIXTURE} (incident {key})")


# ---------------------------------------------------------------------- serve
def build_app():
    """FastAPI app served entirely from the fixture — zero external network."""
    import asyncio

    if not FIXTURE.exists():
        raise SystemExit(f"no replay fixture at {FIXTURE}; run: python agent/replay.py --record")
    fx = json.loads(FIXTURE.read_text())
    snaps = fx["snapshots"]
    events = fx["events"]

    app = FastAPI(title="NOVA RCA Agent (REPLAY)")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"mongo": False, "grove": False, "replay": True, "ts": int(time.time() * 1000)}

    @app.get("/api/incidents")
    def incidents(limit: int = 20):
        return snaps.get("incidents", [])[:limit]

    @app.get("/api/incidents/{key:path}")
    def incident(key: str):
        return snaps.get("incidentByKey", {}).get(key) or (snaps.get("incidents") or [{}])[0]

    @app.get("/api/memory")
    def memory():
        return snaps.get("memory", {"incidents": [], "playbooks": []})

    @app.get("/api/metrics")
    def metrics(service: str | None = None, window: str = "5m"):
        m = snaps.get("metricsByService", {})
        if service and service in m:
            return m[service]
        # loose match so any tile finds something
        for k, v in m.items():
            if service and service.lower() in k.lower():
                return v
        return next(iter(m.values()), []) if not service else []

    @app.get("/api/logs")
    def logs(trnsId: str | None = None, sessnTknId: str | None = None, limit: int = 100):
        by = snaps.get("logsByTrns", {})
        if trnsId and trnsId in by:
            return by[trnsId]
        return next(iter(by.values()), [])

    @app.get("/api/search")
    def search(q: str = ""):
        return {"errors": [], "services": []}

    @app.post("/api/scenarios/{scenario_id}/fire")
    def fire(scenario_id: str):
        _replay_state["fire_at"] = time.time()
        return {"ok": True, "scenario": scenario_id, "replay": True}

    @app.post("/api/feedback")
    def feedback(body: dict):
        return {"ok": True, "replay": True}

    @app.get("/api/stream")
    async def stream(request: Request):
        async def gen():
            yield f"data: {json.dumps({'type': 'hello', 'replay': True})}\n\n"
            # wait for a fire, then replay events at recorded cadence
            start_fire = _replay_state.get("fire_at", 0)
            while _replay_state.get("fire_at", 0) <= start_fire:
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.3)
            base = time.time()
            for ev in events:
                delay = ev["t"] / 1000.0 - (time.time() - base)
                if delay > 0:
                    await asyncio.sleep(min(delay, 3.0))
                if await request.is_disconnected():
                    return
                yield f"data: {json.dumps(ev['data'], default=str)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


_replay_state: dict = {}


def main() -> None:
    if "--record" in sys.argv:
        scenario = "eis-martech-brownout"
        if "--scenario" in sys.argv:
            scenario = sys.argv[sys.argv.index("--scenario") + 1]
        record(scenario)
        return
    import uvicorn
    app = build_app()
    print(f"REPLAY server on :{PORT} — no Atlas, no Grove. Fire a scenario in the UI to replay.")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
