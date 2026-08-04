"""DebounceBuffer: window open/close, signature grouping, escalation. Pure."""
from nova_agent.watcher.debounce import DebounceBuffer


def test_window_holds_until_deadline():
    b = DebounceBuffer(window_s=4)
    b.add({"signature": "TEEIS009", "trns_id": "t1", "sessn_tkn_id": "s1"}, now=100.0)
    assert b.due(now=101.0) == []          # window still open
    assert b.open_windows == 1
    out = b.due(now=105.0)                  # deadline passed
    assert len(out) == 1
    assert b.open_windows == 0


def test_same_signature_groups_one_trigger():
    b = DebounceBuffer(window_s=4)
    for i in range(3):
        b.add({"signature": "TEEIS009", "trns_id": f"t{i}", "sessn_tkn_id": f"s{i}"}, now=100.0 + i)
    out = b.due(now=110.0)
    assert len(out) == 1                     # one grouped incident, not three
    trig = out[0]
    assert trig["distinctTrns"] == 3
    assert set(trig["trns_ids"]) == {"t0", "t1", "t2"}


def test_escalation_threshold():
    b = DebounceBuffer(window_s=4, escalate_n=3)
    b.add({"signature": "BS000001", "trns_id": "a"}, now=0.0)
    b.add({"signature": "BS000001", "trns_id": "b"}, now=0.1)
    assert b.due(now=10.0)[0]["escalated"] is False   # 2 < 3
    b2 = DebounceBuffer(window_s=4, escalate_n=3)
    for i in range(3):
        b2.add({"signature": "BS000001", "trns_id": f"x{i}"}, now=0.0)
    assert b2.due(now=10.0)[0]["escalated"] is True


def test_distinct_signatures_are_distinct_windows():
    b = DebounceBuffer(window_s=4)
    b.add({"signature": "TEEIS009", "trns_id": "t1"}, now=0.0)
    b.add({"signature": "eis_marTech_getInteractOffers", "trns_id": "t1"}, now=0.0)
    assert b.open_windows == 2
    out = b.due(now=10.0)
    assert len(out) == 2


def test_incident_key_shape():
    b = DebounceBuffer(window_s=4)
    b.add({"signature": "TEEIS009", "trns_id": "t1"}, now=0.0)
    key = b.due(now=10.0)[0]["incident_key"]
    assert key.startswith("TEEIS009:")       # "<signature>:<UTC-minute>"


def test_trigger_hard_flag_drives_significance_gate():
    # gate: significant = hard OR distinctTrns>=3 (a real burst). A hard downstream failure
    # (transport -2 / TE) qualifies even singly; soft signals need a burst.
    b = DebounceBuffer(window_s=4)
    b.add({"signature": "eis_marTech_getInteractOffers", "trns_id": "t1",
           "source": "audit_service", "hard": True}, now=0.0)
    trig = b.due(now=10.0)[0]
    assert trig["hard"] is True and trig["distinctTrns"] == 1  # lone hard failure -> incident

    # a lone silent business-fail (not hard, 1 trns) is noise until it bursts
    b2 = DebounceBuffer(window_s=4)
    b2.add({"signature": "unipay_pendingbills", "trns_id": "t1",
            "source": "audit_service", "hard": False}, now=0.0)
    trig2 = b2.due(now=10.0)[0]
    assert trig2["hard"] is False and trig2["distinctTrns"] == 1  # gated out until burst

    # a lone benign business exception (audit_error) is never hard
    b3 = DebounceBuffer(window_s=4)
    b3.add({"signature": "BSPAPL010", "trns_id": "t1", "source": "audit_error", "hard": False}, now=0.0)
    trig3 = b3.due(now=10.0)[0]
    assert trig3["hard"] is False and trig3["sources"] == ["audit_error"]
