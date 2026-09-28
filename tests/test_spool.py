"""Crash recovery and capacity rules for the telemetry fallback."""

import sqlite3

from api_service.spool import TelemetrySpool


def test_committed_event_survives_reopening_and_is_removed_after_replay(tmp_path):
    path = tmp_path / "spool.sqlite"
    first = TelemetrySpool(path, capacity=2)
    identifier = first.enqueue({"sessionId": "one", "_buffered_analysis": {"verdict": "HUMAN"}})
    assert identifier is not None

    reopened = TelemetrySpool(path, capacity=2)
    assert reopened.load() == [{
        "sessionId": "one", "_buffered_analysis": {"verdict": "HUMAN"},
        "_spool_id": identifier,
    }]
    reopened.delete(identifier)
    assert TelemetrySpool(path, capacity=2).load() == []


def test_full_or_unwritable_spool_does_not_acknowledge(tmp_path):
    spool = TelemetrySpool(tmp_path / "spool.sqlite", capacity=1)
    spool.enqueue({"sessionId": "existing"})
    assert spool.enqueue({"sessionId": "new"}) is None
    assert [event["sessionId"] for event in spool.load()] == ["existing"]

    unavailable = TelemetrySpool(tmp_path / "not-a-directory" / "spool.sqlite", capacity=1)
    (tmp_path / "not-a-directory").write_text("occupied", encoding="utf-8")
    try:
        unavailable.enqueue({"sessionId": "new"})
    except (OSError, sqlite3.Error):
        pass
    else:
        raise AssertionError("Unwritable spool must not accept telemetry")
