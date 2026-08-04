"""API + serialization helpers: window parsing, BSON-safe JSON, ObjectId stripping."""
import datetime as dt

from bson import ObjectId

from nova_agent.api.routes import _parse_window
from nova_agent.db import jsonable, strip_oid


def test_parse_window_units():
    assert _parse_window("300s") == 300
    assert _parse_window("5m") == 300
    assert _parse_window("15m") == 900
    assert _parse_window("2h") == 7200
    assert _parse_window("300") == 300        # bare = seconds
    assert _parse_window("500ms") == 1        # sub-second floors to >=1


def test_parse_window_bad_input_defaults():
    assert _parse_window("garbage") == 300
    assert _parse_window("") == 300


def test_jsonable_stringifies_objectid_and_dates():
    oid = ObjectId()
    when = dt.datetime(2026, 7, 7, 16, 9, 38, tzinfo=dt.timezone.utc)
    out = jsonable({"_id": oid, "ts": when, "nested": [{"_id": oid}]})
    assert out["_id"] == str(oid)
    assert isinstance(out["ts"], str) and out["ts"].startswith("2026-07-07")
    assert out["nested"][0]["_id"] == str(oid)


def test_strip_oid_keeps_datetimes():
    # checkpointer msgpack can't take ObjectId, but MUST keep datetimes for ordering
    oid = ObjectId()
    when = dt.datetime(2026, 7, 7, tzinfo=dt.timezone.utc)
    out = strip_oid({"_id": oid, "strt_time": when, "kids": [{"_id": oid}]})
    assert out["_id"] == str(oid)
    assert out["strt_time"] is when          # datetime preserved, not stringified
    assert out["kids"][0]["_id"] == str(oid)
