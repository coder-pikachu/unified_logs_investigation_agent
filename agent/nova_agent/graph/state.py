"""AgentState: the typed blackboard threaded through the LangGraph run.

node_trace / errors accumulate (operator.add); token_usage merges by summing.
Everything else is set-once (last write wins), which matches the linear graph.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _merge_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + v
    return out


class AgentState(TypedDict, total=False):
    incident_key: str
    trns_ids: list[str]
    sessn_tkn_ids: list[str]
    trigger: dict[str, Any]

    txn_docs: list[dict]
    err_docs: list[dict]
    svc_docs: list[dict]
    context_docs: list[dict]
    metrics_baseline: dict[str, Any]
    collect_queries: list[dict]

    timeline: list[dict]
    origin_candidate: dict[str, Any] | None
    systems_involved: list[str]
    journeys_involved: list[str]
    signatures: list[dict]

    recalled_incidents: list[dict]
    recalled_kb: list[dict]
    recall_arms: dict[str, Any]
    recall_hit: bool
    playbook: dict[str, Any] | None

    hypotheses: list[dict]
    verifications: list[dict]

    rca: dict[str, Any] | None
    recommendations: list[dict]
    short_circuit: bool

    iteration: int
    started_ts: float
    node_trace: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[dict[str, int], _merge_usage]
