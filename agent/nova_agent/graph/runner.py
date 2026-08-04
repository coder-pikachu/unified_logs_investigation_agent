"""Executes one incident through the compiled graph, streaming node events onto
the SSE bus. Sync (PyMongo + graph are sync); the watcher calls it via
asyncio.to_thread so the API event loop stays responsive.
"""
from __future__ import annotations

import time
from typing import Any

from ..api.sse import bus
from .graph import compiled_graph


def run_incident(trigger: dict[str, Any]) -> dict | None:
    key = trigger.get("incident_key") or trigger.get("incidentKey")
    config = {"configurable": {"thread_id": key}}
    state = {
        "incident_key": key,
        "trigger": trigger,
        "trns_ids": list(trigger.get("trns_ids", [])),
        "sessn_tkn_ids": list(trigger.get("sessn_tkn_ids", [])),
    }
    bus.publish({"type": "incident", "incidentKey": key, "phase": "start",
                 "summary": f"incident {key} detected — starting agent", "ts": int(time.time() * 1000)})
    final: dict | None = None
    try:
        for mode, chunk in compiled_graph().stream(state, config, stream_mode=["custom", "values"]):
            if mode == "custom":
                bus.publish(chunk)
            else:
                final = chunk
    except Exception as e:  # never crash the watcher on one bad incident
        bus.publish({"type": "incident", "incidentKey": key, "phase": "error", "summary": str(e)[:200]})
        raise
    bus.publish({"type": "incident", "incidentKey": key, "phase": "complete",
                 "summary": f"incident {key} complete", "ts": int(time.time() * 1000)})
    return final
