"""Pure pieces of the Investigate chat backend: data-URL parsing and the
honest no-match reply. The LLM/db paths are covered by the e2e verification."""
import datetime as dt

import pytest

from nova_agent.api.chat import (
    JOURNEY_CATALOG,
    Triage,
    _entity_from_message,
    _entity_of,
    _no_match_reply,
    _render_activity,
    _split_data_url,
    _wants_rundown,
)


def test_split_data_url_parses_content_type():
    assert _split_data_url("data:image/png;base64,AAA") == ("image/png", "AAA")
    assert _split_data_url("data:image/jpeg;base64,BBBB") == ("image/jpeg", "BBBB")


def test_split_data_url_defaults_content_type():
    # header without a type still yields a usable default
    assert _split_data_url("data:;base64,AAA") == ("image/png", "AAA")


def test_split_data_url_rejects_malformed():
    with pytest.raises(ValueError):
        _split_data_url("no-comma-here")
    with pytest.raises(ValueError):
        _split_data_url("data:image/png;base64,")  # empty payload


def test_no_match_reply_names_every_journey_family():
    reply = _no_match_reply(30)
    assert "30 minutes" in reply
    families = {c.split("_")[0] for c, _ in JOURNEY_CATALOG}
    for fam in families:
        assert fam in reply, f"family {fam} missing from the no-match reply"
    # it must name the collections it searched — the multi-collection story
    for coll in ("audit_transaction", "audit_error", "audit_service"):
        assert coll in reply


def _triage(**kw) -> Triage:
    base = dict(intent="new_issue", journeys=[], errCds=[], trnsId="", sessnTknId="",
                usrId="", usrRltnshpNo="", timeframeMinutes=0, screenSummary="")
    base.update(kw)
    return Triage(**base)


def test_wants_rundown_detects_activity_language():
    for m in ["give me the rundown of activity", "what did this user do",
              "full history for the session", "run down of user activity",
              "show all transactions", "entire activity details"]:
        assert _wants_rundown(m), m
    for m in ["offers are failing", "login is broken", ""]:
        assert not _wants_rundown(m), m


def test_entity_of_prefers_most_specific():
    assert _entity_of(_triage(usrId="123", usrRltnshpNo="999")) == ("usr_id", "123")
    assert _entity_of(_triage(usrRltnshpNo="85002588087")) == ("usr_rltnshp_no", "85002588087")
    assert _entity_of(_triage(sessnTknId="S1")) == ("sessn_tkn_id", "S1")
    assert _entity_of(_triage(trnsId="T1")) == ("trns_id", "T1")
    assert _entity_of(_triage()) is None


def test_entity_from_message_extracts_19_digit_usr_id():
    assert _entity_from_message('rundown for usr_id "9480225321203284626"') == ("usr_id", "9480225321203284626")
    # an 11-digit relationship number is NOT a usr_id
    assert _entity_from_message("relationship 85002588087") is None
    assert _entity_from_message("no ids here") is None


def test_render_activity_empty_is_honest():
    txt = _render_activity({"field": "usr_id", "value": "9480225321203284626",
                            "minutes": 30, "rows": [], "total": 0, "failed": 0,
                            "journeys": [], "systems": []})
    assert "No activity" in txt
    assert "9480225321203284626" in txt
    assert "30 min" in txt


def test_render_activity_cites_real_evidence():
    row = {"ts": dt.datetime(2026, 8, 10, 10, 39, 0, tzinfo=dt.timezone.utc),
           "cmnd_id": "loan_personal_papl_getEligibleLoanDetails", "channel": "mobile",
           "failed": True, "codes": ["BS000001", "BSYHP003"], "err_msg": "offer rejected",
           "svc_fail": [{"system": "EIS", "srvc_id": "eis_marTech_getInteractOffers",
                         "trns_sts": "-2", "code": "TEEIS009"}],
           "systems": ["EIS"], "dur_ms": 10123, "trns_id": "TXN-1"}
    act = {"field": "usr_id", "value": "9480225321203284626", "minutes": 30,
           "rows": [row], "total": 1, "failed": 1,
           "journeys": ["loan_personal_papl_getEligibleLoanDetails"], "systems": ["EIS"]}
    txt = _render_activity(act)
    assert "1 action(s)" in txt and "1 failed" in txt
    assert "TXN-1" in txt                            # cites the real transaction id
    assert "FAILED" in txt
    assert "BS000001" in txt                         # cites the error code
    assert "eis_marTech_getInteractOffers" in txt    # cites the downstream route
    assert "pre-approved personal-loan eligibility" in txt  # journey in plain words
    assert "10:39:00" in txt                         # real event time
