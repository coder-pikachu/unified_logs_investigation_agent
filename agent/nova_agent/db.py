"""Shared MongoDB client + small helpers."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

from .config import settings


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(settings.mongodb_uri, tz_aware=True)


def get_db() -> Database:
    return get_client()[settings.mongodb_db]


def jsonable(doc: Any) -> Any:
    """Recursively stringify ObjectId/datetime for JSON responses."""
    import datetime as _dt

    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, _dt.datetime):
        return doc.isoformat()
    if isinstance(doc, dict):
        return {k: jsonable(v) for k, v in doc.items()}
    if isinstance(doc, (list, tuple)):
        return [jsonable(v) for v in doc]
    return doc

def strip_oid(doc: Any) -> Any:
    """Recursively replace ObjectId with str but KEEP datetimes (so state docs
    stay sortable/subtractable). Needed because the checkpointer msgpack-encodes
    state and cannot serialize ObjectId."""
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, dict):
        return {k: strip_oid(v) for k, v in doc.items()}
    if isinstance(doc, (list, tuple)):
        return [strip_oid(v) for v in doc]
    return doc
