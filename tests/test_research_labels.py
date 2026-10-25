import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api_service import main, research_labels as research
from api_service.capture import build_capture


class Cursor(list):
    def sort(self, key, direction):
        return Cursor(sorted(self, key=lambda doc: doc.get(key, 0), reverse=direction == -1))

    def limit(self, limit):
        return Cursor(self[:limit])


class Collection:
    def __init__(self):
        self.docs = {}
        self.lock = threading.RLock()

    def matches(self, doc, query):
        return all((doc.get(key, 0) > value["$gt"] if isinstance(value, dict) and "$gt" in value
                    else doc.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value
                    else doc.get(key) != value["$ne"] if isinstance(value, dict) and "$ne" in value
                    else doc.get(key, 0) < value["$lt"] if isinstance(value, dict) and "$lt" in value
                    else doc.get(key) == value) for key, value in query.items())

    def find(self, query, projection=None):
        return Cursor(copy.deepcopy(doc) for doc in self.docs.values() if self.matches(doc, query))

    def count_documents(self, query):
        return len(self.find(query))

    def find_one(self, query, projection=None):
        return next(iter(self.find(query)), None)

    def create_index(self, *args, **kwargs):
        pass

    def aggregate(self, pipeline):
        first = {}
        for doc in self.docs.values():
            first[doc["sessionId"]] = min(first.get(doc["sessionId"], float("inf")), doc["received_at"])
        return [{"_id": sid, "received_at": received} for sid, received in first.items()]

    def find_one_and_update(self, query, update, upsert=False, **kwargs):
        with self.lock:
            doc = next((doc for doc in self.docs.values() if self.matches(doc, query)), None)
            inserted = doc is None
            if inserted:
                if not upsert:
                    return None
                doc = copy.deepcopy(query)
                doc.update(copy.deepcopy(update.get("$setOnInsert", {})))
                self.docs[doc["_id"]] = doc
            doc.update(copy.deepcopy(update.get("$set", {})))
            for key, value in update.get("$inc", {}).items():
                doc[key] = doc.get(key, 0) + value
            for key, value in update.get("$push", {}).items():
                doc.setdefault(key, []).append(copy.deepcopy(value))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
            return copy.deepcopy(doc)

    def update_one(self, query, update, **kwargs):
        return self.find_one_and_update(query, update, **kwargs)

    def update_many(self, query, update):
        for doc in self.find(query):
            self.update_one({"_id": doc["_id"]}, update)

    def delete_many(self, query):
        for doc in self.find(query):
            self.docs.pop(doc["_id"])


@pytest.fixture
def db(monkeypatch):
    collections = {key: Collection() for key in (
        "research_sessions", "research_counters", "detection_results", "telemetry_captures", "labeled_captures",
        "deleted_sessions", "service_control",
    )}
    monkeypatch.setattr(research, "get_db", lambda: collections)
    return collections


def annotation(**changes):
    return {"label": "BOT", "source": "controlled_bot", "group_id": "run_a",
            "reviewer": "operator", "notes": "Controlled browser runner", "confirmed": True, **changes}


def retainable_snapshot(db, session_id="a"):
    payload = {"sessionId": session_id, "visitorId": "visitor", "collector": {
        "studyId": "study", "siteId": "site", "pageInstanceId": "page"}, "mouse": {"records": []}}
    snapshot = build_capture(payload, received_at=int(time.time() * 1000), client_ip="ip",
                             user_agent="ua", bundle_id="frozen", policy_version="10", retention_days=7)
    db["telemetry_captures"].docs[snapshot["event_id"]] = {"_id": snapshot["event_id"], **snapshot}
    return snapshot


def test_numbers_are_stable_for_heartbeats_restart_and_counter_not_reused(db):
    assert research.register_traffic({"sessionId": "a", "received_at": 1000}) == 1
    assert research.register_traffic({"sessionId": "b", "received_at": 2000}) == 2
    assert research.register_traffic({"sessionId": "a", "received_at": 9000}) == 1
    research.delete_research_data("a")
    assert research.register_traffic({"sessionId": "c", "received_at": 10000}) == 3


def test_concurrent_first_heartbeats_allocate_once(db):
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda _: research.register_traffic({"sessionId": "a"}), range(40)))
    assert numbers == [1] * 40
    assert research.register_traffic({"sessionId": "b"}) == 2


def test_cursor_pagination_includes_unanalyzed_sessions_and_ignores_heartbeats(db):
    for number in range(1, 62):
        research.register_traffic({"sessionId": f"s{number}", "received_at": number * 1000})
    first = research.traffic_page(50)
    assert first["total"] == 61
    assert first["next_before"] == 12
    assert [row["traffic_number"] for row in first["sessions"]] == list(range(61, 11, -1))
    research.register_traffic({"sessionId": "s60", "received_at": 999999})
    research.register_traffic({"sessionId": "s62", "received_at": 1000000})
    second = research.traffic_page(50, first["next_before"])
    assert [row["traffic_number"] for row in second["sessions"]] == list(range(11, 0, -1))
    assert second["next_before"] is None
    assert second["sessions"][0]["decision_state"] == "INSUFFICIENT_EVIDENCE"
    research.delete_research_data("s10")
    assert research.traffic_page(50, 12)["total"] == 61


def test_legacy_backfill_uses_earliest_server_time_not_latest_heartbeat(db):
    db["detection_results"].docs = {
        "b": {"_id": "b", "sessionId": "b", "created_at": 2000, "updated_at": 2100},
        "a": {"_id": "a", "sessionId": "a", "created_at": 1000, "updated_at": 9000},
    }
    assert research.register_traffic({"sessionId": "c", "received_at": 3000}) == 3
    assert db["research_sessions"].docs["a"]["traffic_number"] == 1


def test_label_archive_history_and_optimistic_conflict_never_change_prediction(db):
    research.register_traffic({"sessionId": "a"})
    snapshot = retainable_snapshot(db)
    db["detection_results"].docs["a"] = {"_id": "a", "sessionId": "a", "verdict": "HUMAN"}
    result = research.set_manual_label("a", annotation(), 0)
    assert result["revision"] == 1
    assert db["labeled_captures"].docs[snapshot["event_id"]]["payload_json"] == snapshot["payload_json"]
    assert "expires_at" not in db["labeled_captures"].docs[snapshot["event_id"]]
    assert db["detection_results"].docs["a"]["verdict"] == "HUMAN"
    with pytest.raises(FileExistsError):
        research.set_manual_label("a", annotation(label="UNKNOWN"), 0)
    research.set_manual_label("a", annotation(label="UNKNOWN"), 1)
    assert len(db["research_sessions"].docs["a"]["label_history"]) == 2
    assert db["research_sessions"].docs["a"]["manual_label"]["label"] == "UNKNOWN"


def test_no_raw_means_no_label_ack_and_unknown_session_is_rejected(db):
    research.register_traffic({"sessionId": "a"})
    with pytest.raises(ValueError):
        research.set_manual_label("a", annotation(), 0)
    with pytest.raises(LookupError):
        research.set_manual_label("missing", annotation(), 0)


def test_unknown_can_clear_an_attestation_without_creating_dataset_raw(db):
    research.register_traffic({"sessionId": "a"})
    result = research.set_manual_label("a", annotation(label="UNKNOWN"), 0)
    assert result["manual_label"]["label"] == "UNKNOWN"
    assert not db["labeled_captures"].docs


def test_mixed_visitor_snapshots_cannot_share_one_confirmed_label(db):
    research.register_traffic({"sessionId": "a"})
    first = retainable_snapshot(db)
    db["telemetry_captures"].docs["foreign"] = {
        **first, "_id": "foreign", "visitorId": "another-visitor",
    }
    with pytest.raises(ValueError, match="conflicting visitor"):
        research.set_manual_label("a", annotation(), 0)
    assert db["research_sessions"].docs["a"]["manual_label"] is None
    assert "foreign" not in db["labeled_captures"].docs


def test_archived_data_survives_operational_ttl_but_explicit_delete_removes_it(db):
    research.register_traffic({"sessionId": "a"})
    retainable_snapshot(db)
    research.set_manual_label("a", annotation(), 0)
    db["telemetry_captures"].docs.clear()
    research.set_manual_label("a", annotation(label="UNKNOWN"), 1)
    research.delete_research_data("a")
    assert not db["labeled_captures"].docs
    assert db["research_sessions"].docs["a"]["manual_label"] is None
    assert "label_history" not in db["research_sessions"].docs["a"]


def test_api_requires_admin_and_rejects_unsupported_annotations(db, monkeypatch):
    monkeypatch.setattr(main.settings, "ADMIN_TOKEN", "local-test-admin")
    client = TestClient(main.app)
    body = {**annotation(), "expected_revision": 0}
    assert client.put("/api/v1/sessions/a/label", json=body).status_code == 401
    headers = {"X-Admin-Token": "local-test-admin"}
    for change in ({"label": "SUSPECT"}, {"confirmed": "true"}, {"expected_revision": -1},
                   {"source": "model_prediction"}, {"group_id": ""}, {"notes": "  "},
                   {"label": "HUMAN", "source": "controlled_bot"}):
        assert client.put("/api/v1/sessions/a/label", json={**body, **change}, headers=headers).status_code == 422
    research.register_traffic({"sessionId": "a"})
    retainable_snapshot(db)
    assert client.put("/api/v1/sessions/a/label", json=body, headers=headers).status_code == 200
    assert client.put("/api/v1/sessions/a/label", json=body, headers=headers).status_code == 409


def test_label_write_failure_does_not_acknowledge(db, monkeypatch):
    monkeypatch.setattr(main.settings, "ADMIN_TOKEN", "local-test-admin")
    research.register_traffic({"sessionId": "a"})
    retainable_snapshot(db)

    def failed(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(db["labeled_captures"], "update_one", failed)
    response = TestClient(main.app).put("/api/v1/sessions/a/label", json={**annotation(), "expected_revision": 0},
                                       headers={"X-Admin-Token": "local-test-admin"})
    assert response.status_code == 503
    assert db["research_sessions"].docs["a"]["revision"] == 0
