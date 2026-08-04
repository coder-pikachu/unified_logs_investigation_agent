"""LangGraph long-term memory: per-route playbooks in Atlas via MongoDBStore
(collection `store`). Distilled, cross-thread learnings the agent recalls and
amends on feedback."""
from __future__ import annotations

import datetime as dt
from typing import Any

from langgraph.store.mongodb import MongoDBStore

from ..config import settings
from ..db import get_client, get_db

_NS = ("playbooks",)
_STORE_SINGLETON: "MongoDBStore | None" = None

def _store() -> MongoDBStore:
    global _STORE_SINGLETON
    if _STORE_SINGLETON is None:
        _STORE_SINGLETON = MongoDBStore(get_client()[settings.mongodb_db][settings.C_STORE])
    return _STORE_SINGLETON


def get_playbook(route: str) -> dict[str, Any] | None:
    st = _store()
    item = st.get((*_NS, route), route)
    return dict(item.value) if item else None


def upsert_playbook(route: str, signature: str, confirmed_fix: str | None = None) -> dict[str, Any]:
    st = _store()
    key = (*_NS, route)
    item = st.get(key, route)
    val = dict(item.value) if item else {
        "route": route, "signature": signature, "seenCount": 0,
        "confirmedFixes": [], "confidence": 0.5, "corrections": [],
    }
    val["seenCount"] = int(val.get("seenCount", 0)) + 1
    val["signature"] = signature
    val["lastSeen"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if confirmed_fix and confirmed_fix not in val["confirmedFixes"]:
        val["confirmedFixes"].append(confirmed_fix)
    st.put(key, route, val)
    return val


def apply_feedback(route: str, verdict: str, note: str | None) -> dict[str, Any] | None:
    """Down-vote lowers confidence and records the correction (the learn path)."""
    st = _store()
    key = (*_NS, route)
    item = st.get(key, route)
    if not item:
        return None
    val = dict(item.value)
    if verdict == "down":
        val["confidence"] = round(float(val.get("confidence", 0.5)) * 0.5, 3)
        if note:
            val.setdefault("corrections", []).append(note)
    elif verdict == "up":
        val["confidence"] = round(min(1.0, float(val.get("confidence", 0.5)) * 1.2 + 0.05), 3)
    st.put(key, route, val)
    return val


def all_playbooks() -> list[dict[str, Any]]:
    """Read playbooks directly for the Memory view (store collection layout)."""
    out = []
    for doc in get_db()[settings.C_STORE].find():
        v = doc.get("value")
        if isinstance(v, dict) and "route" in v:
            out.append(v)
    return out
