"""Hybrid recall over Atlas: $rankFusion fusing a Vector Search arm
(autoEmbed voyage-4-lite, query:{text}) and an Atlas Search lexical arm, run
per collection (incident_memory, kb_docs). $rankFusion is single-collection, so
we run it once per collection. We ALSO run each arm standalone so the UI can
show both arms + the fused ranking (claim #4), and so we can apply the
vector-score / exact-token hit threshold.

No embedding client anywhere: the vector arm passes raw text; Atlas embeds it.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..db import get_db


def _vector_arm(coll: str, index: str, path: str, text: str, project: dict, limit: int = 5) -> list[dict]:
    db = get_db()
    pipe = [
        {"$vectorSearch": {"index": index, "path": path, "query": {"text": text},
                           "numCandidates": 50, "limit": limit}},
        {"$project": {**project, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(db[coll].aggregate(pipe))


def _lexical_arm(coll: str, index: str, should: list[dict], project: dict, limit: int = 5) -> list[dict]:
    db = get_db()
    pipe = [
        {"$search": {"index": index, "compound": {"should": should}}},
        {"$limit": limit},
        {"$project": {**project, "score": {"$meta": "searchScore"}}},
    ]
    return list(db[coll].aggregate(pipe))


def _rank_fusion(coll: str, vindex: str, path: str, lindex: str, should: list[dict],
                 text: str, project: dict, limit: int = 5) -> list[dict]:
    db = get_db()
    pipe = [
        {"$rankFusion": {
            "input": {"pipelines": {
                "vector": [{"$vectorSearch": {"index": vindex, "path": path,
                                              "query": {"text": text},
                                              "numCandidates": 50, "limit": limit}}],
                "lexical": [{"$search": {"index": lindex, "compound": {"should": should}}},
                            {"$limit": limit}],
            }},
            "combination": {"weights": {"vector": 1.0, "lexical": 1.0}},
            "scoreDetails": True,
        }},
        {"$limit": limit},
        {"$project": {**project, "score": {"$meta": "score"},
                      "scoreDetails": {"$meta": "scoreDetails"}}},
    ]
    return list(db[coll].aggregate(pipe))


def recall(narrative: str, err_cds: list[str], srvc_ids: list[str], limit: int = 5) -> dict[str, Any]:
    err_cds = [c for c in err_cds if c]
    srvc_ids = [s for s in srvc_ids if s]
    tokens = " ".join(err_cds + srvc_ids) or narrative[:64]

    mem_proj = {"_id": 0, "incidentKey": 1, "summary_text": 1, "err_cds": 1, "srvc_ids": 1, "journeys": 1}
    kb_proj = {"_id": 0, "title": 1, "codes": 1, "tags": 1, "body": 1}

    mem_should = [
        {"text": {"query": narrative, "path": "summary_text"}},
        {"text": {"query": err_cds or ["_none_"], "path": "err_cds"}},
        {"text": {"query": srvc_ids or ["_none_"], "path": "srvc_ids"}},
    ]
    kb_should = [
        {"text": {"query": narrative, "path": "body"}},
        {"text": {"query": (err_cds + srvc_ids) or ["_none_"], "path": "codes"}},
    ]

    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:  # keep the demo alive if a stage hiccups
            return {"__error__": str(e)[:200]}

    mem_vec = safe(_vector_arm, settings.C_MEMORY, settings.IDX_MEM_VECTOR, "summary_text", narrative, mem_proj, limit)
    mem_lex = safe(_lexical_arm, settings.C_MEMORY, settings.IDX_MEM_SEARCH, mem_should, mem_proj, limit)
    mem_fused = safe(_rank_fusion, settings.C_MEMORY, settings.IDX_MEM_VECTOR, "summary_text",
                     settings.IDX_MEM_SEARCH, mem_should, narrative, mem_proj, limit)

    kb_vec = safe(_vector_arm, settings.C_KB, settings.IDX_KB_VECTOR, "body", narrative, kb_proj, limit)
    kb_lex = safe(_lexical_arm, settings.C_KB, settings.IDX_KB_SEARCH, kb_should, kb_proj, limit)
    kb_fused = safe(_rank_fusion, settings.C_KB, settings.IDX_KB_VECTOR, "body",
                    settings.IDX_KB_SEARCH, kb_should, narrative, kb_proj, limit)

    def top_vec(arm) -> float:
        if isinstance(arm, list) and arm:
            return float(arm[0].get("score", 0.0))
        return 0.0

    def lexical_exact(arm) -> bool:
        return isinstance(arm, list) and len(arm) > 0

    incident_hit = top_vec(mem_vec) >= settings.recall_min_vector_score or lexical_exact(mem_lex)

    def as_list(x):
        return x if isinstance(x, list) else []

    return {
        "incidents": {"fused": as_list(mem_fused), "vector": as_list(mem_vec), "lexical": as_list(mem_lex),
                      "vectorTop": top_vec(mem_vec)},
        "kb": {"fused": as_list(kb_fused), "vector": as_list(kb_vec), "lexical": as_list(kb_lex),
               "vectorTop": top_vec(kb_vec)},
        "hit": bool(incident_hit),
        "threshold": settings.recall_min_vector_score,
        "pipelines": {
            "incident_rankFusion": "$rankFusion(vector=$vectorSearch autoEmbed voyage-4-lite, lexical=$search) on incident_memory",
            "kb_rankFusion": "$rankFusion(vector=$vectorSearch autoEmbed voyage-4-lite, lexical=$search) on kb_docs",
        },
    }
