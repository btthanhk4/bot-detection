"""Unit tests for MongoDB index setup."""

from api_service.database import _ensure_indexes


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

    _ensure_indexes({"detection_results": detections, "deleted_sessions": deleted})

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

    _ensure_indexes({"detection_results": detections, "deleted_sessions": deleted})

    assert detections.dropped == []
    assert deleted.dropped == []
