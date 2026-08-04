"""Atlas Admin API helper for Search/Vector index lifecycle.

On this cluster the driver's `createSearchIndex` is blocked (Atlas Search DB
commands require extra local config), but the Atlas Admin API manages search
indexes fine and the driver can *query* them. So: create/delete via Admin API,
list/poll via either. Verified working against the M30 cluster in P0.
"""
from __future__ import annotations

import time
from typing import Any

import requests
from requests.auth import HTTPDigestAuth

from .config import settings

_API = "https://cloud.mongodb.com/api/atlas/v2"
_HDR = {
    "Accept": "application/vnd.atlas.2024-05-30+json",
    "Content-Type": "application/vnd.atlas.2024-05-30+json",
}


def _auth() -> HTTPDigestAuth:
    return HTTPDigestAuth(settings.atlas_pub_key, settings.atlas_priv_key)


def _base() -> str:
    return f"{_API}/groups/{settings.atlas_group_id}/clusters/{settings.atlas_cluster}/search/indexes"


def list_search_indexes() -> list[dict[str, Any]]:
    r = requests.get(_base(), auth=_auth(), headers=_HDR, timeout=30)
    r.raise_for_status()
    return r.json()


def find_index(db: str, coll: str, name: str) -> dict[str, Any] | None:
    for idx in list_search_indexes():
        if idx.get("database") == db and idx.get("collectionName") == coll and idx.get("name") == name:
            return idx
    return None


def create_search_index(db: str, coll: str, name: str, definition: dict[str, Any]) -> dict[str, Any]:
    """Idempotent: returns existing index if already present."""
    existing = find_index(db, coll, name)
    if existing:
        return {"status": "EXISTS", "indexID": existing.get("indexID"), "name": name}
    body = {
        "collectionName": coll,
        "database": db,
        "name": name,
        "type": "vectorSearch" if _is_vector(definition) else "search",
        "definition": definition,
    }
    r = requests.post(_base(), auth=_auth(), headers=_HDR, json=body, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"create_search_index {name} failed {r.status_code}: {r.text[:400]}")
    return r.json()


def _is_vector(definition: dict[str, Any]) -> bool:
    fields = definition.get("fields", [])
    return any(f.get("type") in ("vector", "autoEmbed") for f in fields if isinstance(f, dict))


def delete_search_index(db: str, coll: str, name: str) -> bool:
    idx = find_index(db, coll, name)
    if not idx:
        return False
    iid = idx["indexID"]
    r = requests.delete(f"{_base()}/{iid}", auth=_auth(), headers={"Accept": _HDR["Accept"]}, timeout=30)
    return r.status_code in (202, 204)


def wait_ready(db: str, coll: str, name: str, timeout_s: int = 300, poll_s: int = 5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        idx = find_index(db, coll, name)
        if idx:
            status = idx.get("status")
            if status == "READY":
                return True
            if status == "FAILED":
                raise RuntimeError(f"search index {name} FAILED: {idx}")
        time.sleep(poll_s)
    return False
