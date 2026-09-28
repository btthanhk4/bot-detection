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


def test_deleted_identifier_is_never_reused_even_after_clear_and_reopen(tmp_path):
    path = tmp_path / "spool.sqlite"
    spool = TelemetrySpool(path, capacity=2)
    first = spool.enqueue({"sessionId": "first"})
    spool.delete(first)
    second = spool.enqueue({"sessionId": "second"})
    assert second > first
    spool.clear()
    reopened = TelemetrySpool(path, capacity=2)
    third = reopened.enqueue({"sessionId": "third"})
    assert third > second
    reopened.delete(first)
    assert [event["sessionId"] for event in reopened.load()] == ["third"]


def test_legacy_spool_migration_preserves_pending_events(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE telemetry_spool ("
            "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO telemetry_spool(id, session_id, payload) VALUES (17, 'old', '{\"sessionId\":\"old\"}')"
        )
    spool = TelemetrySpool(path, capacity=2)
    assert spool.load() == [{"sessionId": "old", "_spool_id": 17}]
    spool.delete(17)
    new_identifier = spool.enqueue({"sessionId": "new"})
    assert new_identifier > 17
