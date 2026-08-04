"""LangGraph wiring: the fixed 9-node RCA workflow.

intake -> collect -> correlate -> recall -> hypothesize -> verify
verify --(best score weak & iteration<2)--> collect   (widen once)
verify --(otherwise)--> rca -> recommend -> persist -> END

Compiled with the Atlas MongoDBSaver checkpointer so every run's state is
durable in the `checkpoints` collection (claim #3, inspectable in the deep dive).
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from ..memory.checkpointer import get_checkpointer
from . import nodes
from .state import AgentState


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("intake", nodes.intake)
    g.add_node("collect", nodes.collect)
    g.add_node("correlate", nodes.correlate)
    g.add_node("recall", nodes.recall)
    g.add_node("hypothesize", nodes.hypothesize)
    g.add_node("verify", nodes.verify)
    g.add_node("rca", nodes.rca)
    g.add_node("recommend", nodes.recommend)
    g.add_node("confirm", nodes.confirm)
    g.add_node("persist", nodes.persist)

    g.set_entry_point("intake")
    g.add_edge("intake", "collect")
    g.add_edge("collect", "correlate")
    g.add_edge("correlate", "recall")
    g.add_conditional_edges("recall", nodes.recall_route,
                            {"cold": "hypothesize", "warm": "confirm"})
    g.add_edge("confirm", "persist")
    g.add_edge("hypothesize", "verify")
    g.add_conditional_edges("verify", nodes.verify_route,
                            {"collect": "collect", "rca": "rca"})
    g.add_edge("rca", "recommend")
    g.add_edge("recommend", "persist")
    g.add_edge("persist", END)
    return g


@lru_cache(maxsize=1)
def compiled_graph():
    return build_graph().compile(checkpointer=get_checkpointer())
