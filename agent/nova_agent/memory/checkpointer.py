"""LangGraph short-term memory: MongoDBSaver in Atlas (collections
checkpoints / checkpoint_writes). This is the 'agent memory is native' proof."""
from __future__ import annotations

from langgraph.checkpoint.mongodb import MongoDBSaver

from ..config import settings
from ..db import get_client


def get_checkpointer() -> MongoDBSaver:
    return MongoDBSaver(get_client(), db_name=settings.mongodb_db)
