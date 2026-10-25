import copy
import csv
import json

import pytest
from bson.int64 import Int64

from api_service.capture import build_capture
from core_ml.dataset.export_captures import (
    capture_row, export_captures, utc_milliseconds, verify_export,
)
from core_ml.dataset.manual_labels import load_manual_training_runs, manual_training_samples


def snapshot(sequence=0, **overrides):
    payload = {"sessionId": "session", "visitorId": "visitor", "timestamp": 1000,
               "sequence": sequence, "mouse": {"records": [], "scrollEvents": [{"time": 1, "deltaY": 2}]},
               "collector": {"schemaVersion": 1, "sdkVersion": "1.1.0", "pageInstanceId": "page",
                             "studyId": "study", "siteId": "site"}}
    result = build_capture(payload, received_at=1000 + sequence, client_ip="private-ip",
                           user_agent="observed-agent", bundle_id="bundle", policy_version="10",
                           retention_days=7)
    result.update(overrides)
    return result


class Cursor:
    def __init__(self, docs):
        self.docs = docs
        self.closed = False

    def sort(self, spec):
        assert spec == [("received_at", 1), ("event_id", 1)]
        return self

    def batch_size(self, count):
        assert count == 200
        return self

    def __iter__(self):
        yield from self.docs

    def close(self):
        self.closed = True


class Collection:
    def __init__(self, docs):
        self.cursor = Cursor(docs)

    def find(self, query, projection):
        assert query == {"study_id": "study", "site_id": "site", "received_at": {"$gte": 1000, "$lt": 2000}}
        assert projection == {"_id": 0}
        return self.cursor


def export(tmp_path, docs, **kwargs):
    collection = Collection(docs)
    manifest = export_captures(collection, tmp_path / "export", study_id="study", site_id="site",
                               since_ms=1000, until_ms=2000, **kwargs)
    assert collection.cursor.closed
    return manifest


def test_export_roundtrip_preserves_raw_and_never_uses_prediction_as_label(tmp_path):
    original = snapshot(analysis_json=json.dumps({"verdict": "BOT", "model_bundle_id": "older-bundle"}))
    manifest = export(tmp_path, [original, snapshot(1)])
    assert manifest["snapshots"] == 2
    assert manifest["runs"] == 1
    assert manifest["without_analysis"] == 1
    assert verify_export(tmp_path / "export") == manifest
    rows = [json.loads(line) for line in (tmp_path / "export/snapshots.jsonl").read_text().splitlines()]
    assert rows[0]["payload_json"] == original["payload_json"]
    assert json.loads(rows[0]["payload_json"])["mouse"]["scrollEvents"][0]["deltaY"] == 2
    assert rows[0]["analysis"]["model_bundle_id"] == "older-bundle"
    assert rows[1]["analysis"] is None
    assert "client_ip" not in rows[0]
    with (tmp_path / "export/labels-template.csv").open(newline="") as stream:
        labels = list(csv.DictReader(stream))
    assert labels[0]["label"] == "UNKNOWN"
    assert labels[0]["run_id"] == rows[0]["run_id"]
    assert "session_id" not in labels[0], 'raw client IDs must not become spreadsheet formulas'


class Labels:
    def __init__(self, annotation):
        self.annotation = annotation

    def find_one(self, query):
        assert query == {"_id": "session"}
        return {"traffic_number": 7, "revision": 1, "manual_label": self.annotation}


def test_manual_label_export_and_grouped_loader_keep_prediction_out_of_features(tmp_path):
    annotation = {"label": "BOT", "source": "controlled_bot", "confirmed": True,
                  "group_id": "generator_config_01", "reviewer": "operator", "notes": "Runner evidence",
                  "revision": 1, "updated_at": 2000}
    manifest = export(tmp_path, [snapshot(analysis_json='{"verdict":"HUMAN"}'), snapshot(1)],
                      labels_collection=Labels(annotation))
    assert verify_export(tmp_path / "export") == manifest
    rows = load_manual_training_runs(tmp_path / "export")
    assert len(rows) == 1
    assert rows[0]["label"] == 1
    assert rows[0]["group_id"] == "generator_config_01"
    assert len(rows[0]["payloads"]) == 2
    assert all("label" not in payload and "analysis" not in payload for payload in rows[0]["payloads"])
    assert json.loads((tmp_path / "export/manual-labels.jsonl").read_text())["traffic_number"] == 7


@pytest.mark.parametrize("changes", [{"confirmed": False}, {"label": "UNKNOWN"},
                                    {"source": "provider_claim"}, {"source": "commercial_tool"}])
def test_unconfirmed_unknown_and_weak_labels_are_not_silently_training_data(tmp_path, changes):
    annotation = {"label": "BOT", "source": "controlled_bot", "confirmed": True,
                  "group_id": "group", "reviewer": "operator", "notes": "Evidence", "revision": 1, **changes}
    export(tmp_path, [snapshot()], labels_collection=Labels(annotation))
    with pytest.raises(ValueError, match="No confirmed"):
        load_manual_training_runs(tmp_path / "export")


def test_legacy_unlabeled_export_cannot_be_loaded_as_attested_training_data(tmp_path):
    export(tmp_path, [snapshot()])
    with pytest.raises(ValueError, match="no manual"):
        load_manual_training_runs(tmp_path / "export")


def test_training_import_requires_explicit_groups_and_enough_mouse_data(tmp_path):
    annotation = {"label": "BOT", "source": "controlled_bot", "confirmed": True,
                  "group_id": "group", "reviewer": "operator", "notes": "Evidence", "revision": 1}
    export(tmp_path, [snapshot()], labels_collection=Labels(annotation))
    with pytest.raises(ValueError, match="Declare existing"):
        manual_training_samples(tmp_path / "export", [])
    with pytest.raises(ValueError, match="no usable desktop"):
        manual_training_samples(tmp_path / "export", ["group"])


def test_training_import_deduplicates_heartbeats_and_strips_browser_profile(tmp_path):
    payload = json.loads(snapshot()["payload_json"])
    payload["mouse"]["records"] = [
        {"type": "move", "time": index * 20, "x": index / 100, "y": ((index * 7) % 20) / 100}
        for index in range(40)
    ]
    payload["fingerprint"] = {"userAgent": "must not learn label from runner profile"}
    docs = []
    for sequence in range(2):
        payload["sequence"] = sequence
        docs.append(build_capture(payload, received_at=1000 + sequence, client_ip="ip", user_agent="ua",
                                  bundle_id="bundle", policy_version="10", retention_days=7))
    annotation = {"label": "BOT", "source": "controlled_bot", "confirmed": True,
                  "group_id": "group", "reviewer": "operator", "notes": "Evidence", "revision": 1}
    export(tmp_path, docs, labels_collection=Labels(annotation))
    samples = manual_training_samples(tmp_path / "export", ["group"])
    assert len(samples) == 1
    assert len(samples[0]["windows"]) == 1
    assert len(samples[0]["windows"][0]) == 40


def test_manual_training_cannot_publish_over_live_bundle():
    from core_ml.train import main
    with pytest.raises(ValueError, match="Manual labels require"):
        main(manual_export_dir="not-read")


def test_explicit_ip_option_and_capture_metadata():
    doc = snapshot()
    assert (doc["study_id"], doc["site_id"], doc["page_instance_id"]) == ("study", "site", "page")
    assert capture_row(doc, include_client_ip=True)["client_ip"] == "private-ip"


def test_real_bson_int64_timestamps_are_valid_and_roundtrip(tmp_path):
    manifest = export(tmp_path, [snapshot(received_at=Int64(1000))])
    assert manifest["snapshots"] == 1
    assert verify_export(tmp_path / "export") == manifest


@pytest.mark.parametrize("change", [
    {"payload_json": "{}"}, {"sessionId": "wrong"}, {"visitorId": "wrong"},
    {"study_id": "wrong"}, {"site_id": "wrong"}, {"page_instance_id": "wrong"},
    {"event_id": "wrong"}, {"analysis_json": "NaN"}, {"analysis_json": "[]"},
])
def test_corrupt_capture_fails_closed_without_success_manifest(tmp_path, change):
    collection = Collection([snapshot(**change)])
    with pytest.raises(ValueError):
        export_captures(collection, tmp_path / "export", study_id="study", site_id="site", since_ms=1000, until_ms=2000)
    assert collection.cursor.closed
    assert not (tmp_path / "export/manifest.json").exists()


@pytest.mark.parametrize("docs", [[], [snapshot(), snapshot()], [snapshot(received_at=999)], [snapshot(received_at=2000)]])
def test_empty_duplicate_or_out_of_scope_cursor_cannot_produce_success(tmp_path, docs):
    collection = Collection(docs)
    with pytest.raises(ValueError):
        export_captures(collection, tmp_path / "export", study_id="study", site_id="site", since_ms=1000, until_ms=2000)
    assert collection.cursor.closed
    assert not (tmp_path / "export/manifest.json").exists()


def test_export_will_not_overwrite_existing_directory(tmp_path):
    export(tmp_path, [snapshot()])
    previous = (tmp_path / "export/manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        export(tmp_path, [snapshot(1)])
    assert (tmp_path / "export/manifest.json").read_bytes() == previous


@pytest.mark.parametrize("filename", ["snapshots.jsonl", "labels-template.csv"])
def test_verify_rejects_modified_files(tmp_path, filename):
    export(tmp_path, [snapshot()])
    with (tmp_path / "export" / filename).open("a") as stream:
        stream.write("changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_export(tmp_path / "export")


def test_pages_of_same_session_remain_distinct_runs(tmp_path):
    second = snapshot(1)
    payload = json.loads(second["payload_json"])
    payload["collector"]["pageInstanceId"] = "another-page"
    import hashlib
    second["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    second["event_id"] = second["payload_sha256"] = hashlib.sha256(second["payload_json"].encode()).hexdigest()
    second["page_instance_id"] = "another-page"
    assert export(tmp_path, [snapshot(), second])["runs"] == 2


def test_time_range_requires_timezone_and_normalizes_offsets():
    assert utc_milliseconds("2026-10-19T07:00:00+07:00") == utc_milliseconds("2026-10-19T00:00:00Z")
    with pytest.raises(ValueError, match="timezone"):
        utc_milliseconds("2026-10-19T00:00:00")


def test_invalid_study_ids_and_time_range_do_not_create_output(tmp_path):
    for study, since, until in [("=formula", 1000, 2000), ("study", 2000, 1000), ("study", 1000, 1000)]:
        with pytest.raises(ValueError):
            export_captures(Collection([]), tmp_path / "bad", study_id=study, site_id="site", since_ms=since, until_ms=until)
        assert not (tmp_path / "bad").exists()


def test_row_does_not_mutate_source():
    doc = snapshot()
    original = copy.deepcopy(doc)
    capture_row(doc)
    assert doc == original
