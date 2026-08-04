"""Pure pieces of the Investigate chat backend: data-URL parsing and the
honest no-match reply. The LLM/db paths are covered by the e2e verification."""
import pytest

from nova_agent.api.chat import JOURNEY_CATALOG, _no_match_reply, _split_data_url


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
