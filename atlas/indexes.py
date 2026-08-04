#!/usr/bin/env python3
"""Provision all collections, regular indexes, TTL, time series, and the six
Atlas Search / Vector Search indexes for the NOVA RCA demo. Idempotent.

Run: python atlas/indexes.py            # create + wait for search indexes READY
     python atlas/indexes.py --no-wait  # create, don't block on search build
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import CollectionInvalid, OperationFailure

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from nova_agent import atlas_admin  # noqa: E402
from nova_agent.config import settings  # noqa: E402

IDX_DIR = Path(__file__).resolve().parent / "index_defs"
TTL = 7 * 24 * 3600  # 7 days

# search index name -> (collection, def-file)
SEARCH = {
    settings.IDX_ERR_SEARCH: (settings.C_ERR, "audit_error_search.json"),
    settings.IDX_SVC_SEARCH: (settings.C_SVC, "audit_service_search.json"),
    settings.IDX_MEM_SEARCH: (settings.C_MEMORY, "incident_memory_search.json"),
    settings.IDX_KB_SEARCH: (settings.C_KB, "kb_docs_search.json"),
    settings.IDX_MEM_VECTOR: (settings.C_MEMORY, "incident_memory_vector.json"),
    settings.IDX_KB_VECTOR: (settings.C_KB, "kb_docs_vector.json"),
}


def ensure_collection(db, name, **opts):
    try:
        db.create_collection(name, **opts)
        print(f"  created collection {name}")
    except (CollectionInvalid, OperationFailure) as e:
        if "already exists" in str(e) or getattr(e, "code", None) == 48:
            print(f"  collection {name} exists")
        else:
            raise


def main(wait: bool = True):
    cli = MongoClient(settings.mongodb_uri)
    db = cli[settings.mongodb_db]
    print(f"DB: {settings.mongodb_db} on {settings.atlas_cluster}")

    # --- plain collections ---
    for c in (
        settings.C_TXN, settings.C_ERR, settings.C_SVC, settings.C_INCIDENTS,
        settings.C_MEMORY, settings.C_KB, settings.C_FEEDBACK, settings.C_STATE,
        settings.C_CHAT, settings.C_CHAT_IMG,
    ):
        ensure_collection(db, c)

    # --- time series: service_metrics ---
    # metaField = static, moderate-cardinality {service, system, kind}; queried
    # with ts ranges. Per-series rate is ~0.25-2/s -> "minutes" granularity
    # (bucket spans ~24h) per the time-series sizing guidance.
    ensure_collection(
        db, settings.C_METRICS,
        timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
        expireAfterSeconds=TTL,
    )
    try:  # existing collections created at "seconds": coarsen in place
        db.command({"collMod": settings.C_METRICS,
                    "timeseries": {"granularity": "minutes"}})
    except OperationFailure:
        pass  # already "minutes" (or older server): keep as-is
    # Hot shape: meta.service equality + ts range (sparklines, agent baseline).
    # The auto {meta,ts} index covers whole-meta only, not the subfield.
    db[settings.C_METRICS].create_index([("meta.service", ASCENDING), ("ts", ASCENDING)])

    # --- regular + TTL indexes ---
    db[settings.C_TXN].create_index([("trns_id", ASCENDING)])
    db[settings.C_TXN].create_index([("sessn_tkn_id", ASCENDING), ("strt_time", ASCENDING)])
    db[settings.C_TXN].create_index([("cmnd_id", ASCENDING), ("strt_time", DESCENDING)])
    # Investigate-chat id ladder ("customer 85002719907 can't fetch offers")
    db[settings.C_TXN].create_index([("usr_id", ASCENDING), ("strt_time", DESCENDING)])
    db[settings.C_TXN].create_index([("usr_rltnshp_no", ASCENDING), ("strt_time", DESCENDING)])
    db[settings.C_TXN].create_index([("crtd_on", ASCENDING)], expireAfterSeconds=TTL)

    db[settings.C_ERR].create_index([("trns_id", ASCENDING)])
    db[settings.C_ERR].create_index([("err_cd", ASCENDING), ("err_time", DESCENDING)])
    db[settings.C_ERR].create_index([("crtd_on", ASCENDING)], expireAfterSeconds=TTL)

    db[settings.C_SVC].create_index([("trns_id", ASCENDING)])
    db[settings.C_SVC].create_index([("srvc_id", ASCENDING), ("strt_time", DESCENDING)])
    db[settings.C_SVC].create_index([("systm_nm", ASCENDING), ("strt_time", DESCENDING)])
    # Investigate-chat codes ladder (technical codes live on audit_service too)
    db[settings.C_SVC].create_index([("err_cd", ASCENDING), ("crtd_on", DESCENDING)])
    db[settings.C_SVC].create_index([("crtd_on", ASCENDING)], expireAfterSeconds=TTL)

    db[settings.C_INCIDENTS].create_index([("incidentKey", ASCENDING)], unique=True)
    # dispatch merge windows, recent-incident match, list/lastRun sorts
    db[settings.C_INCIDENTS].create_index([("createdAt", DESCENDING)])
    db[settings.C_MEMORY].create_index([("createdAt", DESCENDING)])
    db[settings.C_FEEDBACK].create_index([("incidentKey", ASCENDING)])
    db[settings.C_CHAT].create_index([("updatedAt", DESCENDING)])
    db[settings.C_CHAT_IMG].create_index([("ts", ASCENDING)], expireAfterSeconds=TTL)
    print("  regular + TTL indexes ensured")

    # --- search / vector indexes ---
    for name, (coll, deffile) in SEARCH.items():
        definition = json.loads((IDX_DIR / deffile).read_text())
        res = atlas_admin.create_search_index(settings.mongodb_db, coll, name, definition)
        print(f"  search index {name} on {coll}: {res.get('status')}")

    if wait:
        print("Waiting for search indexes to reach READY (autoEmbed can take ~1 min)...")
        for name, (coll, _) in SEARCH.items():
            ok = atlas_admin.wait_ready(settings.mongodb_db, coll, name, timeout_s=420)
            print(f"  {name}: {'READY' if ok else 'TIMEOUT (still building)'}")
    print("indexes.py done.")


if __name__ == "__main__":
    main(wait="--no-wait" not in sys.argv)
