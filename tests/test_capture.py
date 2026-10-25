"""Research snapshots must survive retries, model errors and database outages."""

import copy
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from api_service.capture import build_capture
from api_service import database


def snapshot(payload=None, **overrides):
    kwargs = {
        "received_at": int(time.time() * 1000), "client_ip": "127.0.0.1",
        "user_agent": "browser", "bundle_id": "bundle-a", "policy_version": "10",
        "retention_days": 7,
    }
    kwargs.update(overrides)
    return build_capture(payload or {
        "sessionId": "session", "visitorId": "visitor", "timestamp": 1000, "sequence": 1,
    }, **kwargs)


class CaptureCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        key = query["_id"]
        doc = self.docs.get(key)
        if doc is None and upsert:
            self.docs[key] = doc = copy.deepcopy(update["$setOnInsert"])
        if doc is not None and not ("analysis_json" in query and "analysis_json" in doc):
            doc.update(copy.deepcopy(update.get("$set", {})))
            return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    def find_one(self, query, projection=None):
        return self.docs.get(query.get("_id"))

    def delete_many(self, query):
        keys = [key for key, doc in self.docs.items()
                if not query or doc["sessionId"] == query["sessionId"]]
        for key in keys:
            del self.docs[key]
        return SimpleNamespace(deleted_count=len(keys))


@pytest.fixture
def collection(monkeypatch):
    captures = CaptureCollection()
    monkeypatch.setattr(database, "get_db", lambda: {"telemetry_captures": captures})
    monkeypatch.setattr(database, "_writes_are_blocked", lambda _db, _session: False)
    return captures


def test_identity_ignores_arrival_ip_bundle_and_json_key_order():
    payload = {"sessionId": "s", "visitorId": "v", "timestamp": 1000, "sequence": 0}
    first = snapshot(payload, received_at=1000)
    retry = snapshot(dict(reversed(list(payload.items()))), received_at=2000,
                     client_ip="other", bundle_id="new")
    assert first["event_id"] == retry["event_id"]
    assert first["identity_kind"] == "payload_sha256"
    assert snapshot({**payload, "sequence": 1})["event_id"] != first["event_id"]
    assert snapshot({**payload, "mouse": {"records": []}})["event_id"] != first["event_id"]
    assert snapshot({**payload, "visitorId": "other"})["event_id"] != first["event_id"]


@pytest.mark.parametrize("missing", ["timestamp", "sequence"])
def test_legacy_payloads_without_stable_identity_are_not_collapsed(missing):
    payload = {"sessionId": "s", "visitorId": "v", "timestamp": 1000, "sequence": 0}
    del payload[missing]
    assert snapshot(payload)["event_id"] != snapshot(payload)["event_id"]
    assert snapshot(payload)["identity_kind"] == "server_uuid"


def test_capture_preserves_full_validated_payload():
    payload = {
        "sessionId": "s", "visitorId": "v",
        "mouse": {"records": [{"time": i, "source": "touch"} for i in range(140)],
                  "scrollEvents": [{"time": 1, "deltaY": -4}]},
        "fingerprint": {"profile": {"worker": {"result": {"platform": "x"}}}},
    }
    capture = snapshot(payload)
    payload["mouse"]["records"].clear()
    saved = json.loads(capture["payload_json"])
    assert len(saved["mouse"]["records"]) == 140
    assert saved["mouse"]["scrollEvents"][0]["deltaY"] == -4
    assert saved["fingerprint"]["profile"]["worker"]["result"]["platform"] == "x"
    assert "analysis_json" not in capture


def test_capture_rejects_non_finite_values():
    with pytest.raises(ValueError):
        snapshot({"sessionId": "s", "visitorId": "v", "fingerprint": {"value": float("inf")}})


def test_retries_preserve_raw_provenance_retention_and_first_decision(collection):
    first = snapshot()
    assert database.save_telemetry_capture(first) == first["event_id"]
    retry = snapshot(received_at=first["received_at"] + 1000, bundle_id="new-bundle")
    analysis = {"verdict": "BOT", "model_bundle_id": "original-inference"}
    database.save_telemetry_capture(retry, analysis)
    database.save_telemetry_capture(retry, {"verdict": "HUMAN", "model_bundle_id": "later"})
    assert len(collection.docs) == 1
    doc = collection.docs[first["event_id"]]
    assert doc["received_at"] == first["received_at"]
    assert doc["expires_at_ms"] == first["expires_at_ms"]
    assert doc["capture_bundle_id"] == "bundle-a"
    assert json.loads(doc["analysis_json"]) == analysis


def test_distinct_snapshots_of_same_session_are_retained(collection):
    first = snapshot()
    payload = json.loads(first["payload_json"])
    second = snapshot({**payload, "sequence": 2})
    database.save_telemetry_capture(second)
    database.save_telemetry_capture(first)
    assert len(collection.docs) == 2


def test_concurrent_identical_insert_is_idempotent(collection, monkeypatch):
    event = snapshot()
    database.save_telemetry_capture(event)
    update = collection.update_one

    def race(query, changes, upsert=False):
        if upsert:
            raise DuplicateKeyError("concurrent insert")
        return update(query, changes, upsert)

    monkeypatch.setattr(collection, "update_one", race)
    assert database.save_telemetry_capture(event, {"verdict": "HUMAN"}) == event["event_id"]
    assert len(collection.docs) == 1


def test_expired_spool_capture_is_not_recreated(collection):
    assert database.save_telemetry_capture(snapshot(received_at=0)) is None
    assert collection.docs == {}


@pytest.mark.parametrize("paused", [False, True])
def test_delete_wins_race_with_capture_write(collection, monkeypatch, paused):
    calls = []

    def block(_db, _session):
        calls.append(1)
        if len(calls) == 1:
            return False
        if paused:
            raise database.DatabaseIngestionPaused(5)
        return True

    monkeypatch.setattr(database, "_writes_are_blocked", block)
    if paused:
        with pytest.raises(database.DatabaseIngestionPaused):
            database.save_telemetry_capture(snapshot())
    else:
        assert database.save_telemetry_capture(snapshot()) is None
    assert not collection.docs


def test_outage_and_missing_indexes_are_not_acknowledged(collection, monkeypatch):
    monkeypatch.setattr(database, "get_db", lambda: None)
    with pytest.raises(database.DatabasePersistenceError):
        database.save_telemetry_capture(snapshot())
    db = {"telemetry_captures": collection}
    monkeypatch.setattr(database, "get_db", lambda: db)
    monkeypatch.setattr(database, "_db", db)
    monkeypatch.setattr(database, "_indexes_ready", False)
    with pytest.raises(database.DatabasePersistenceError):
        database.save_telemetry_capture(snapshot())


def test_admin_delete_removes_raw_data_even_when_capture_is_disabled(collection, monkeypatch):
    event = snapshot()
    database.save_telemetry_capture(event)

    class Empty:
        def update_one(self, *args, **kwargs):
            pass

        def delete_one(self, *args):
            return SimpleNamespace(deleted_count=0)

    db = {"telemetry_captures": collection, "deleted_sessions": Empty(), "detection_results": Empty()}
    monkeypatch.setattr(database, "get_db", lambda: db)
    monkeypatch.setattr(database.settings, "CAPTURE_ENABLED", False)
    assert database.delete_session(event["sessionId"]) is True
    assert not collection.docs


def test_capture_writes_are_blocked_by_real_admin_tombstone(collection, monkeypatch):
    class Tombstones:
        def find_one(self, query, projection):
            return {"_id": "deleted"}

    class Control:
        def find_one(self, query, projection):
            return None

    # Use the actual check, rather than the capture fixture's stub.
    monkeypatch.undo()
    db = {"telemetry_captures": collection, "deleted_sessions": Tombstones(), "service_control": Control()}
    monkeypatch.setattr(database, "get_db", lambda: db)
    assert database.save_telemetry_capture(snapshot()) is None
    assert not collection.docs
    monkeypatch.setattr(Control, "find_one", lambda *args: {
        "blocked_until": datetime.now(timezone.utc) + timedelta(seconds=10),
    })
    with pytest.raises(database.DatabaseIngestionPaused):
        database.save_telemetry_capture(snapshot())
