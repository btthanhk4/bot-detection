"""Touch gestures: sanitising, research flags, weak labels, storage and API."""

import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api_service.touch_samples import build_touch_samples, device_family, label_hint
from core_ml.features.touch import MODEL_FEATURES, analyze_touch, feature_vector, gesture_features, sanitize_gestures
from core_ml.train_touch import GENERATORS, brainrun_points, synthesize

PIXEL = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/153.0.0.0 Mobile Safari/537.36")


def _finger_swipe(x=120.0, y=640.0, n=9):
    # A thumb flick: accelerates then slows, drifts sideways, contact ellipse changes.
    steps = [6, 14, 26, 38, 40, 30, 18, 8, 3][:n - 1]
    points, t = [[0.0, x, y, 11.5, 10.0, 0.42]], 0.0
    for i, step in enumerate(steps):
        t += 16.7
        x += 0.4 * i - 0.6
        y -= step
        points.append([round(t, 1), round(x, 1), round(y, 1), 11.5 + i * 0.3, 10.0 + i * 0.2, 0.42 - i * 0.01])
    return points


def _cdp_swipe(n=11):
    return [[i * 2.0, 200.0 + i, 700.0 - i * 50.0, 1, 1, 1] for i in range(n)]


def _cdp_tap(x=180.0, y=324.0):
    return [[0.0, x, y, 1, 1, 1], [0.0, x, y, 1, 1, 1]]


def test_sanitize_drops_bad_points_and_bounds_sizes():
    touch = {"gestures": [
        {"t0": 5, "points": [[0, 1, 2], ["x", 1, 2], [3, float("inf"), 2], [2, 3, 4, 9, 9, 0.5], [1, 5, 5]]},
        {"t0": 1, "points": "nope"},
        "junk",
    ] + [{"t0": i, "points": [[0, i, i]] * 100} for i in range(30)]}
    gestures = sanitize_gestures(touch)
    assert len(gestures) == 20
    assert all(len(g["points"]) <= 48 for g in gestures)
    first = sanitize_gestures({"gestures": touch["gestures"][:1]})[0]["points"]
    # Non-numeric, non-finite and time-reversed points are dropped; missing extras become None.
    assert first == [[0.0, 1.0, 2.0, None, None, None], [2.0, 3.0, 4.0, 9.0, 9.0, 0.5]]
    assert sanitize_gestures(None) == [] and sanitize_gestures({"gestures": "x"}) == []


def test_features_tell_taps_from_swipes():
    swipe = gesture_features(_finger_swipe())
    tap = gesture_features([[0, 50, 50, 10, 10, 0.3], [85, 51, 50, 10, 10, 0.3]])
    assert swipe["kind"] == "swipe" and tap["kind"] == "tap"
    assert 0.9 < swipe["straightness"] <= 1
    assert 0.3 <= swipe["peak_step_position"] <= 0.7, "a flick peaks mid-stroke"
    assert len(feature_vector(swipe)) == len(MODEL_FEATURES)
    assert all(isinstance(v, float) for v in feature_vector(tap))


def test_finger_input_raises_no_research_flags():
    report = analyze_touch({"gestures": [{"t0": i * 900, "points": _finger_swipe(x=100 + i)} for i in range(6)]
                                       + [{"t0": 9000, "points": [[0, 50, 50, 10, 10, 0.3], [92, 50, 51, 10, 10, 0.3]]}],
                            "total": 7})
    assert report["research_flags"] == []
    assert (report["swipes"], report["taps"], report["gestures_total"]) == (6, 1, 7)


def test_cdp_touches_raise_research_flags():
    report = analyze_touch({"gestures": [{"t0": 0, "points": _cdp_tap()}, {"t0": 1, "points": _cdp_tap(90, 90)},
                                         {"t0": 2, "points": _cdp_swipe()}, {"t0": 3, "points": _cdp_swipe()}]})
    assert set(report["research_flags"]) == {"SYNTHETIC_CONTACT", "ZERO_TIME_TAPS", "RULER_SWIPES"}
    # Radius 1 / force 1 on one gesture among real ones is not the CDP default for the session.
    mixed = analyze_touch({"gestures": [{"t0": 0, "points": _cdp_tap()}, {"t0": 1, "points": _finger_swipe()}]})
    assert "SYNTHETIC_CONTACT" not in mixed["research_flags"]


def test_device_family_and_label_hints():
    assert device_family("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "ios"
    assert device_family(PIXEL) == "android"
    assert device_family("Mozilla/5.0 (Windows NT 10.0)") == "other"
    clean = {"research_flags": []}
    human = {"verdict": "SUSPECT", "breakdown": {"automation_rule": None,
                                                 "automation_evidence": {"family_count": 1, "families": {"HTTP": ["x"]}}}}
    assert label_hint(human, clean, mobile=True) == "human_candidate"
    assert label_hint(human, clean, mobile=False) == "unlabeled"
    cloud = {"verdict": "SUSPECT", "breakdown": {"automation_evidence": {"family_count": 1, "families": {"NETWORK": ["x"]}}}}
    assert label_hint(cloud, clean, mobile=True) == "unlabeled"
    convicted = {"verdict": "BOT", "breakdown": {"automation_rule": "mobile_emulation_v1"}}
    assert label_hint(convicted, clean, mobile=True) == "automation"
    assert label_hint(human, {"research_flags": ["SYNTHETIC_CONTACT"]}, mobile=True) == "automation"
    assert label_hint(human, {"research_flags": ["RULER_SWIPES"]}, mobile=True) == "unlabeled"


def _telemetry(gestures, session="s1", page="p1"):
    return {
        "sessionId": session, "visitorId": "v1", "collector": {"schemaVersion": 1, "pageInstanceId": page, "sdkVersion": "1.7.0"},
        "fingerprint": {"userAgent": PIXEL, "platform": "Linux aarch64"},
        "mouse": {"touch": {"gestures": gestures, "total": len(gestures), "viewport": [412, 915, 0], "dpr": 2.625}},
        "client_ip": "203.0.113.9",
    }


def test_samples_have_stable_ids_and_no_ip():
    gestures = [{"t0": 100, "points": _finger_swipe()}, {"t0": 900, "points": _finger_swipe(x=90)}]
    analysis = {"verdict": "SUSPECT", "policy_version": "17", "breakdown": {"automation_evidence": {}}}
    first = build_touch_samples(_telemetry(gestures), analysis)
    again = build_touch_samples(_telemetry(gestures[:1]), analysis)
    assert len(first) == 2 and first[0]["_id"] == again[0]["_id"] != first[1]["_id"]
    assert first[0]["_id"] != build_touch_samples(_telemetry(gestures, page="p2"), analysis)[0]["_id"]
    sample = first[0]
    assert sample["device"] == "android" and sample["label_hint"] == "human_candidate"
    assert sample["viewport"] == [412, 915] and sample["dpr"] == 2.625
    assert "client_ip" not in sample and all("203.0.113.9" not in str(v) for v in sample.values())
    assert build_touch_samples({"sessionId": "s", "mouse": {}}, analysis) == []


class TouchCollection:
    def __init__(self):
        self.docs, self.writes, self.indexes = {}, 0, []

    def create_index(self, keys, name, **options):
        self.indexes.append((name, options))

    def update_one(self, query, update, upsert=False):
        self.writes += 1
        doc = self.docs.get(query["_id"])
        if doc is None:
            doc = self.docs[query["_id"]] = dict(update["$setOnInsert"])
        doc.update(update["$set"])
        return SimpleNamespace(matched_count=1)


class Empty:
    def find_one(self, *args, **kwargs):
        return None


def test_save_touch_samples_upserts_once_and_relabels(monkeypatch):
    from api_service import database

    touches = TouchCollection()
    monkeypatch.setattr(database, "_touch_indexes_ready", False)
    monkeypatch.setattr(database, "get_db", lambda: {"touch_samples": touches, "deleted_sessions": Empty(),
                                                     "service_control": Empty()})
    database._touch_written.clear()
    gestures = [{"t0": 100, "points": _finger_swipe()}]
    analysis = {"verdict": "SUSPECT", "breakdown": {}}
    samples = build_touch_samples(_telemetry(gestures), analysis)
    assert database.save_touch_samples(samples) == 1
    assert database.save_touch_samples(samples) == 0, "an unchanged heartbeat costs no write"
    relabelled = build_touch_samples(_telemetry(gestures), {"verdict": "BOT", "breakdown": {"automation_rule": "x"}})
    assert database.save_touch_samples(relabelled) == 1
    doc = next(iter(touches.docs.values()))
    assert doc["label_hint"] == "automation" and doc["points"] == samples[0]["points"]
    assert doc["expires_at"] > doc["created_at"]
    assert ("expires_at_1", {"expireAfterSeconds": 0}) in touches.indexes
    database._touch_written.clear()


def test_no_touch_samples_without_a_ttl_index(monkeypatch):
    from api_service import database

    class NoIndexes(TouchCollection):
        def create_index(self, *args, **kwargs):
            raise RuntimeError("not authorised")

    touches = NoIndexes()
    monkeypatch.setattr(database, "_touch_indexes_ready", False)
    monkeypatch.setattr(database, "get_db", lambda: {"touch_samples": touches, "deleted_sessions": Empty(),
                                                     "service_control": Empty()})
    samples = build_touch_samples(_telemetry([{"t0": 1, "points": _finger_swipe()}]), {"verdict": "SUSPECT"})
    assert database.save_touch_samples(samples) == 0 and touches.docs == {}


def test_tombstoned_session_stores_no_touch_samples(monkeypatch):
    from api_service import database

    touches = TouchCollection()
    monkeypatch.setattr(database, "_touch_indexes_ready", False)

    class Tombstones:
        def find_one(self, query, projection=None):
            return {"_id": 1} if "sessionId" in query else None

    monkeypatch.setattr(database, "get_db", lambda: {"touch_samples": touches, "deleted_sessions": Tombstones(),
                                                     "service_control": Empty()})
    samples = build_touch_samples(_telemetry([{"t0": 1, "points": _finger_swipe()}]), {"verdict": "SUSPECT"})
    assert database.save_touch_samples(samples) == 0 and touches.docs == {}


def test_generators_copy_the_template_and_differ_in_shape():
    rng = random.Random(4)
    template = _finger_swipe()
    for kind in GENERATORS:
        bot = synthesize(kind, template, rng)
        assert len(bot) == len(template)
        assert bot[0][0] == 0 and bot[-1][0] == pytest.approx(template[-1][0], abs=0.2)
        assert gesture_features(bot)["kind"] == "swipe"
    linear = gesture_features(synthesize("linear", template, rng))
    assert linear["max_deviation_px"] < 0.2 and linear["step_length_cv"] < 0.01
    with pytest.raises(ValueError):
        synthesize("teleport", template, rng)


def test_brainrun_points_from_pan_responder_samples():
    doc = {"t_start": 1000.0, "t_stop": 1100.0, "data": [
        {"x0": 10, "y0": 500, "moveX": 11, "moveY": 470}, {"x0": 10, "y0": 500, "moveX": 13, "moveY": 420}]}
    points = brainrun_points(doc)
    assert [p[:3] for p in points] == [[0.0, 10.0, 500.0], [50.0, 11.0, 470.0], [100.0, 13.0, 420.0]]
    assert brainrun_points({"data": []}) is None
    assert brainrun_points({**doc, "t_stop": 900.0}) is None


def test_ensemble_reports_touch_without_changing_the_verdict():
    from api_service.main import ensemble_detector

    payload = {"sessionId": "t", "visitorId": "v", "fingerprint": {"userAgent": PIXEL},
               "mouse": {"records": [], "touch": {"gestures": [{"t0": i, "points": _cdp_swipe()} for i in range(3)]}}}
    with_touch = ensemble_detector.predict(payload)
    without = ensemble_detector.predict({**payload, "mouse": {"records": []}})
    touch = with_touch["breakdown"]["touch"]
    assert "RULER_SWIPES" in touch["research_flags"] and "SYNTHETIC_CONTACT" in touch["research_flags"]
    assert touch["shadow"] is None or touch["shadow"]["swipes"] == 3
    assert with_touch["verdict"] == without["verdict"]
    assert with_touch["breakdown"]["automation_rule"] == without["breakdown"]["automation_rule"]


@pytest.fixture
def client():
    from api_service.config import settings
    from api_service.main import _rate_limit_records, app

    _rate_limit_records.clear()
    original = (settings.ADMIN_TOKEN, settings.READ_TOKEN)
    settings.ADMIN_TOKEN, settings.READ_TOKEN = "admin-secret", "read-secret"
    try:
        yield TestClient(app)
    finally:
        settings.ADMIN_TOKEN, settings.READ_TOKEN = original


def test_touch_endpoints_require_credentials(client, monkeypatch):
    from api_service import database

    monkeypatch.setattr(database, "get_touch_sample_stats", lambda: {"groups": [{"label": "human_candidate", "count": 3}]})
    monkeypatch.setattr(database, "export_touch_samples", lambda **kw: {"samples": [{"_id": "a" * 32}], "next": None, **kw})
    monkeypatch.setattr(database, "delete_touch_samples", lambda: 4)
    assert client.get("/api/v1/touch-samples/stats").status_code == 401
    stats = client.get("/api/v1/touch-samples/stats", headers={"X-Read-Token": "read-secret"})
    assert stats.status_code == 200 and stats.json()["groups"][0]["count"] == 3
    assert client.get("/api/v1/touch-samples/export", headers={"X-Read-Token": "read-secret"}).status_code == 401
    exported = client.get("/api/v1/touch-samples/export?label=human_candidate&limit=10",
                          headers={"X-Admin-Token": "admin-secret"})
    assert exported.status_code == 200 and exported.json()["label"] == "human_candidate"
    assert client.get("/api/v1/touch-samples/export?after=../x", headers={"X-Admin-Token": "admin-secret"}).status_code == 422
    assert client.delete("/api/v1/touch-samples").status_code == 401
    assert client.delete("/api/v1/touch-samples", headers={"X-Admin-Token": "admin-secret"}).json()["count"] == 4


def test_telemetry_stores_touch_samples_only_when_enabled(client, monkeypatch):
    from api_service import database, main

    stored = []
    monkeypatch.setattr(main, "_require_inference_models", lambda: None)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: {"verdict": "SUSPECT", "breakdown": {}})
    monkeypatch.setattr(database, "save_detection_result", lambda *args: "s")
    monkeypatch.setattr(database, "save_touch_samples", lambda samples: stored.extend(samples) or len(samples))
    body = {k: v for k, v in _telemetry([{"t0": 1, "points": _finger_swipe()}]).items() if k != "client_ip"}
    monkeypatch.setattr(main.settings, "TOUCH_CAPTURE_ENABLED", False)
    assert client.post("/api/v1/telemetry", json=body).status_code == 200
    assert stored == []
    monkeypatch.setattr(main.settings, "TOUCH_CAPTURE_ENABLED", True)
    assert client.post("/api/v1/telemetry", json=body).status_code == 200
    assert len(stored) == 1 and stored[0]["label_hint"] == "human_candidate"
    monkeypatch.setattr(database, "save_touch_samples", lambda samples: 1 / 0)
    assert client.post("/api/v1/telemetry", json=body).status_code == 200, "touch storage is best effort"
