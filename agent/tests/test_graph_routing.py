"""Conditional-edge logic: recall→(warm|cold) short-circuit and verify→(collect|rca) loop."""
from nova_agent.graph import nodes


def test_recall_cold_when_no_memory():
    # run #1: nothing recalled, no playbook -> full LLM path
    assert nodes.recall_route({"recall_hit": False}) == "cold"
    assert nodes.recall_route({"recall_hit": True, "recalled_incidents": []}) == "cold"


def test_recall_warm_on_recalled_incident():
    # run #2: a prior incident recalled -> short-circuit
    st = {"recall_hit": True, "recalled_incidents": [{"incidentKey": "k", "score": 0.9}]}
    assert nodes.recall_route(st) == "warm"


def test_recall_warm_on_playbook_confirmed_fix():
    st = {"recall_hit": True, "recalled_incidents": [],
          "playbook": {"confirmedFixes": ["circuit-break offers"]}}
    assert nodes.recall_route(st) == "warm"


def test_recall_hit_but_empty_playbook_is_cold():
    st = {"recall_hit": True, "recalled_incidents": [], "playbook": {"confirmedFixes": []}}
    assert nodes.recall_route(st) == "cold"


def test_verify_loops_to_collect_on_weak_evidence():
    st = {"verifications": [{"score": 0.2}], "iteration": 1}
    assert nodes.verify_route(st) == "collect"     # < 0.34 and iteration < 2


def test_verify_proceeds_to_rca_when_supported():
    st = {"verifications": [{"score": 0.8}], "iteration": 1}
    assert nodes.verify_route(st) == "rca"


def test_verify_stops_looping_after_two_iterations():
    st = {"verifications": [{"score": 0.1}], "iteration": 2}
    assert nodes.verify_route(st) == "rca"          # give up looping, proceed honestly
