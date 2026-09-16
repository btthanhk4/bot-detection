"""Unit tests for MongoDB index setup."""

from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError
from api_service.database import (
    _ensure_indexes,
    delete_all_sessions,
    get_recent_results,
    is_database_ready,
    save_detection_result,
)


class FakeCollection:
    def __init__(self, indexes=None):
        self.indexes = dict(indexes or {})
        self.dropped = []
        self.created = []

    def index_information(self):
        return self.indexes

    def drop_index(self, name):
        self.dropped.append(name)
        self.indexes.pop(name, None)

    def create_index(self, keys, name, **options):
        self.created.append((name, keys, options))
        self.indexes[name] = {"key": keys, **options}


def test_ensure_indexes_rebuilds_conflicting_options():
    detections = FakeCollection(
        {
            "created_at_-1": {"key": [("created_at", -1)]},
            "sessionId_1": {"key": [("sessionId", 1)], "unique": False},
        }
    )
    deleted = FakeCollection()

    ready = _ensure_indexes({"detection_results": detections, "deleted_sessions": deleted})

    assert ready is True
    assert detections.dropped == ["created_at_-1", "sessionId_1"]
    assert detections.indexes["created_at_-1"]["expireAfterSeconds"] == 86400 * 30
    assert detections.indexes["sessionId_1"]["unique"] is True
    assert deleted.indexes["expires_at_1"]["expireAfterSeconds"] == 0


def test_ensure_indexes_keeps_matching_indexes():
    detections = FakeCollection(
        {
            "created_at_-1": {
                "key": [("created_at", -1)],
                "expireAfterSeconds": 86400 * 30,
            },
            "sessionId_1": {"key": [("sessionId", 1)], "unique": True},
        }
    )
    deleted = FakeCollection(
        {"expires_at_1": {"key": [("expires_at", 1)], "expireAfterSeconds": 0}}
    )

    ready = _ensure_indexes({"detection_results": detections, "deleted_sessions": deleted})

    assert ready is True
    assert detections.dropped == []
    assert deleted.dropped == []


def test_ensure_indexes_removes_unwanted_unique_option():
    detections = FakeCollection(
        {"verdict_1": {"key": [("verdict", 1)], "unique": True}}
    )

    ready = _ensure_indexes(
        {"detection_results": detections, "deleted_sessions": FakeCollection()}
    )

    assert ready is True
    assert "verdict_1" in detections.dropped
    assert detections.indexes["verdict_1"].get("unique", False) is False


def test_ensure_indexes_restores_previous_index_when_rebuild_fails():
    class RejectUniqueCollection(FakeCollection):
        def create_index(self, keys, name, **options):
            if name == "sessionId_1" and options.get("unique") is True:
                raise RuntimeError("duplicate session ids")
            return super().create_index(keys, name, **options)

    detections = RejectUniqueCollection(
        {"sessionId_1": {"key": [("sessionId", 1)], "unique": False}}
    )

    ready = _ensure_indexes(
        {"detection_results": detections, "deleted_sessions": FakeCollection()}
    )

    assert ready is False
    assert detections.indexes["sessionId_1"]["unique"] is False
    assert detections.dropped == ["sessionId_1"]


def test_delete_all_blocks_writes_until_delete_finishes(monkeypatch):
    class TrackingCollection:
        def __init__(self, deleted_count=0):
            self.deleted_count = deleted_count
            self.updates = []

        def update_one(self, query, update, upsert=False):
            self.updates.append(update["$set"]["blocked_until"])

        def delete_many(self, _query):
            return SimpleNamespace(deleted_count=self.deleted_count)

    control = TrackingCollection()
    database = {
        "service_control": control,
        "deleted_sessions": TrackingCollection(),
        "detection_results": TrackingCollection(deleted_count=7),
    }
    monkeypatch.setattr("api_service.database.get_db", lambda: database)

    assert delete_all_sessions() == 7
    assert len(control.updates) == 2
    assert control.updates[0] > control.updates[1]


def test_delete_all_keeps_fail_closed_block_when_delete_fails(monkeypatch):
    class TrackingControl:
        def __init__(self):
            self.updates = []

        def update_one(self, query, update, upsert=False):
            self.updates.append(update["$set"]["blocked_until"])

    class FailingCollection:
        def delete_many(self, _query):
            raise RuntimeError("delete failed")

    control = TrackingControl()
    database = {
        "service_control": control,
        "deleted_sessions": FailingCollection(),
        "detection_results": FakeCollection(),
    }
    monkeypatch.setattr("api_service.database.get_db", lambda: database)

    assert delete_all_sessions() is None
    assert len(control.updates) == 1


def test_recent_results_falls_back_to_created_time_for_legacy_null_update(monkeypatch):
    from datetime import datetime, timezone

    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Cursor(list):
        def sort(self, *_args):
            return self

        def limit(self, _limit):
            return self

    class LegacyCollection:
        def find(self, *_args, **_kwargs):
            return Cursor(
                [{"sessionId": "legacy", "created_at": created_at, "updated_at": None}]
            )

    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {"detection_results": LegacyCollection()},
    )

    results = get_recent_results()

    assert results[0]["received_at"] == int(created_at.timestamp() * 1000)


def test_readiness_clears_stale_connection_for_reconnect(monkeypatch):
    import api_service.database as database_module

    class FailingAdmin:
        def command(self, _name):
            raise ConnectionError("connection dropped")

    class StaleClient:
        admin = FailingAdmin()

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    client = StaleClient()
    monkeypatch.setattr(database_module, "_client", client)
    monkeypatch.setattr(database_module, "_db", {"cached": "stale"})
    monkeypatch.setattr(database_module, "_retry_after", 0.0)

    assert is_database_ready() is False
    assert client.closed is True
    assert database_module._client is None
    assert database_module._db is None
    assert database_module._retry_after > 0.0


def test_readiness_retries_failed_index_setup(monkeypatch):
    import api_service.database as database_module

    class Admin:
        def command(self, _name):
            return {"ok": 1}

    database = {
        "detection_results": FakeCollection(),
        "deleted_sessions": FakeCollection(),
    }
    monkeypatch.setattr(database_module, "_client", SimpleNamespace(admin=Admin()))
    monkeypatch.setattr(database_module, "_db", database)
    monkeypatch.setattr(database_module, "_indexes_ready", False)

    assert is_database_ready() is True
    assert database_module._indexes_ready is True
    assert database["detection_results"].indexes["sessionId_1"]["unique"] is True


def test_save_waits_for_required_indexes_on_real_cached_database(monkeypatch):
    import api_service.database as database_module

    detections = MemoryCollection()
    empty = MemoryCollection()
    database = {
        "detection_results": detections,
        "deleted_sessions": empty,
        "service_control": empty,
    }
    monkeypatch.setattr(database_module, "_db", database)
    monkeypatch.setattr(database_module, "_indexes_ready", False)
    monkeypatch.setattr(database_module, "get_db", lambda: database)

    with pytest.raises(database_module.DatabasePersistenceError, match="indexes"):
        save_detection_result(
            {"sessionId": "wait-for-index", "visitorId": "visitor"},
            {"verdict": "HUMAN"},
        )

    assert detections.docs == {}


def test_save_reports_unavailable_database_as_retryable(monkeypatch):
    import api_service.database as database_module

    monkeypatch.setattr(database_module, "get_db", lambda: None)

    with pytest.raises(database_module.DatabasePersistenceError, match="unavailable"):
        save_detection_result(
            {"sessionId": "retry-later", "visitorId": "visitor"},
            {"verdict": "HUMAN"},
        )


class MemoryCollection:
    def __init__(self):
        self.docs = {}

    def find_one(self, query, projection=None):
        session_id = query.get("sessionId")
        return self.docs.get(session_id) if session_id else None

    def update_one(self, query, update, upsert=False):
        doc = self.docs.get(query.get("sessionId"))
        incoming = update["$set"]
        matches = bool(
            doc
            and doc.get("event_order", -1) <= incoming["event_order"]
            and doc.get("visitorId", incoming.get("visitorId")) == incoming.get("visitorId")
        )
        if matches:
            doc.update(incoming)
        return SimpleNamespace(matched_count=1 if matches else 0)

    def insert_one(self, doc):
        if doc["sessionId"] in self.docs:
            raise DuplicateKeyError("duplicate sessionId")
        self.docs[doc["sessionId"]] = dict(doc)
        return SimpleNamespace(inserted_id=doc["sessionId"])

    def delete_one(self, query):
        removed = self.docs.pop(query.get("sessionId"), None)
        return SimpleNamespace(deleted_count=1 if removed else 0)


def test_save_rejects_stale_or_foreign_heartbeat(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    database = {
        "detection_results": detections,
        "deleted_sessions": empty,
        "service_control": empty,
    }
    monkeypatch.setattr("api_service.database.get_db", lambda: database)
    analysis = {"verdict": "HUMAN", "bot_probability": 0.1}

    assert save_detection_result({"sessionId": "s1", "visitorId": "v1", "sequence": 2}, analysis)
    assert save_detection_result({"sessionId": "s1", "visitorId": "v1", "sequence": 1}, {"verdict": "BOT"}) is None
    assert save_detection_result({"sessionId": "s1", "visitorId": "attacker", "sequence": 3}, {"verdict": "BOT"}) is None
    assert detections.docs["s1"]["verdict"] == "HUMAN"


def test_newer_timestamp_allows_sequence_restart(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )

    first = {"sessionId": "reused", "visitorId": "v1", "timestamp": 1000, "sequence": 50}
    reloaded = {"sessionId": "reused", "visitorId": "v1", "timestamp": 2000, "sequence": 0}
    delayed = {"sessionId": "reused", "visitorId": "v1", "timestamp": 1500, "sequence": 99}

    assert save_detection_result(first, {"verdict": "SUSPECT"})
    assert save_detection_result(reloaded, {"verdict": "HUMAN"})
    assert save_detection_result(delayed, {"verdict": "BOT"}) is None
    assert detections.docs["reused"]["verdict"] == "HUMAN"


def test_event_timestamp_is_bounded_by_server_receive_time(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )

    future = {
        "sessionId": "clock-skew",
        "visitorId": "v1",
        "timestamp": 9_000_000_000_000,
        "received_at": 2_000_000,
        "sequence": 1,
    }
    later = {
        "sessionId": "clock-skew",
        "visitorId": "v1",
        "timestamp": 9_000_000_000_000,
        "received_at": 2_001_000,
        "sequence": 0,
    }

    assert save_detection_result(future, {"verdict": "SUSPECT"})
    assert save_detection_result(later, {"verdict": "HUMAN"})
    assert detections.docs["clock-skew"]["verdict"] == "HUMAN"
    assert detections.docs["clock-skew"]["event_timestamp"] == 2_001_000 + 300_000


def test_save_sanitizes_nested_values_that_bson_cannot_encode(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )
    telemetry = {
        "sessionId": "bson-safe",
        "visitorId": "visitor",
        "timestamp": 10**400,
        "received_at": 2_000_000,
        "fingerprint": {
            "huge": 10**400,
            "notFinite": float("inf"),
            "$unsafe.key": {"nested": [float("nan")]},
        },
    }

    assert save_detection_result(
        telemetry,
        {"verdict": "human", "bot_probability": float("nan"), "confidence": float("inf")},
    )
    stored = detections.docs["bson-safe"]
    assert stored["verdict"] == "HUMAN"
    assert stored["bot_probability"] == 0.0
    assert stored["confidence"] == 0.0
    assert stored["event_timestamp"] == 2_000_000 + 300_000
    assert stored["fingerprint"]["huge"] == 2**63 - 1
    assert stored["fingerprint"]["notFinite"] == 0.0
    assert "_unsafe_key" in stored["fingerprint"]


def test_zero_timestamp_is_not_replaced_by_receive_time(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )

    telemetry = {"sessionId": "epoch", "visitorId": "v1", "timestamp": 0, "sequence": 1}
    assert save_detection_result(telemetry, {"verdict": "HUMAN"})
    assert detections.docs["epoch"]["event_order"] == 1


def test_save_uses_server_computed_mouse_stats(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )
    records = [
        {"time": i * 20, "x": 0.1 + i * 0.01, "y": 0.2, "type": "move"}
        for i in range(30)
    ]
    telemetry = {
        "sessionId": "trusted-stats",
        "visitorId": "visitor",
        "sequence": 1,
        "mouse": {
            "records": records,
            "stats": {"pointCount": 999999, "avgSpeed": 999999},
        },
    }

    assert save_detection_result(telemetry, {"verdict": "HUMAN"})
    stored = detections.docs["trusted-stats"]
    assert stored["mouse_points_captured"] == 30
    assert stored["mouse_stats"]["move_point_count"] == 30
    assert stored["mouse_stats"]["chunks_count"] == 1
    assert "avgSpeed" not in stored["mouse_stats"]


def test_save_uses_same_rolling_window_as_collector(monkeypatch):
    detections = MemoryCollection()
    empty = MemoryCollection()
    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {
            "detection_results": detections,
            "deleted_sessions": empty,
            "service_control": empty,
        },
    )
    records = [
        {"time": i * 20, "x": (i % 100) / 100, "y": 0.2, "type": "move"}
        for i in range(250)
    ]

    assert save_detection_result(
        {"sessionId": "rolling", "visitorId": "visitor", "mouse": {"records": records}},
        {"verdict": "HUMAN"},
    )
    stored = detections.docs["rolling"]
    assert stored["mouse_points_captured"] == 100
    assert len(stored["mouse_trajectory"]) == 100
