"""
Integration tests for FastAPI inference & telemetry service.
"""

import asyncio
import hashlib
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from api_service.main import app
from core_ml.models.ensemble import DECISION_POLICY_VERSION


@pytest.fixture(autouse=True)
def isolated_telemetry_spool(tmp_path, monkeypatch):
    from api_service import main
    from api_service.spool import TelemetrySpool

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", False)
    monkeypatch.setattr(main, "delete_research_data", lambda session_id=None: None)
    monkeypatch.setattr(
        main, "_spool",
        TelemetrySpool(tmp_path / "telemetry-spool.sqlite", main.settings.MAX_BUFFER_SIZE),
    )
    yield
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()


@pytest.fixture
def client():
    from api_service.main import _health_cache, _rate_limit_records
    from api_service.config import settings
    _rate_limit_records.clear()
    _health_cache["checked_at"] = 0.0
    original_read_token = settings.READ_TOKEN
    settings.READ_TOKEN = "test-read-token"
    try:
        yield TestClient(app)
    finally:
        settings.READ_TOKEN = original_read_token


READ_HEADERS = {"X-Read-Token": "test-read-token"}


def test_research_capture_survives_unavailable_models(client, monkeypatch):
    from api_service import database, main

    saved = []
    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True, raising=False)
    monkeypatch.setattr(main, "lstm_loaded", False)
    monkeypatch.setattr(
        database, "save_telemetry_capture",
        lambda snapshot, analysis=None: saved.append(snapshot) or snapshot["event_id"],
        raising=False,
    )
    response = client.post("/api/v1/telemetry", json={
        "sessionId": "capture-no-model", "visitorId": "visitor", "timestamp": 1000, "sequence": 0,
    })

    assert response.status_code == 202
    assert response.json()["recorded"] is True
    assert response.json()["analysis_available"] is False
    assert response.json()["capture_id"] == saved[0]["event_id"]
    assert "verdict" not in response.json()


def test_research_capture_precedes_inference_failure(client, monkeypatch):
    from api_service import database, main

    steps = []
    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True, raising=False)
    monkeypatch.setattr(main, "_require_inference_models", lambda: None)

    def save(snapshot, analysis=None):
        steps.append("capture")
        return snapshot["event_id"]

    def fail(_data):
        steps.append("inference")
        raise RuntimeError("broken runtime")

    monkeypatch.setattr(database, "save_telemetry_capture", save, raising=False)
    monkeypatch.setattr(main.ensemble_detector, "predict", fail)
    response = client.post("/api/v1/telemetry", json={"sessionId": "s", "visitorId": "v"})

    assert steps == ["capture", "inference"]
    assert response.status_code == 202
    assert response.json()["analysis_available"] is False


def test_research_capture_recovers_after_restart_without_running_model(client, monkeypatch):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(main, "lstm_loaded", False)

    def outage(*args):
        raise database.DatabasePersistenceError("offline")

    monkeypatch.setattr(database, "save_telemetry_capture", outage)
    payload = {"sessionId": "offline", "visitorId": "visitor", "timestamp": 1000, "sequence": 0,
               "mouse": {"scrollEvents": [{"time": 123, "deltaY": 50}]}}
    response = client.post("/api/v1/telemetry", json=payload)
    assert response.status_code == 202
    assert response.json()["buffered"] is True
    assert main._spool.count() == 1
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()

    saved = []
    monkeypatch.setattr(database, "save_telemetry_capture",
                        lambda event, analysis: saved.append((event, analysis)) or event["event_id"])
    monkeypatch.setattr(main.ensemble_detector, "predict",
                        lambda *args: pytest.fail("Raw recovery must not run inference"))
    main._flush_telemetry_buffer()

    assert main._spool.count() == 0
    assert len(saved) == 1
    assert saved[0][1] is None
    assert json.loads(saved[0][0]["payload_json"])["mouse"] == payload["mouse"]
    assert saved[0][0]["event_id"] == response.json()["capture_id"]


def test_research_capture_replay_preserves_original_decision_version(client, monkeypatch):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(main, "_require_inference_models", lambda: None)
    monkeypatch.setattr(main, "model_bundle_id", "bundle-original")
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: {"verdict": "BOT"})

    def outage(*args):
        raise database.DatabasePersistenceError("offline")

    monkeypatch.setattr(database, "save_telemetry_capture", outage)
    monkeypatch.setattr(database, "save_detection_result", outage)
    response = client.post("/api/v1/telemetry", json={"sessionId": "s", "visitorId": "v"})
    assert response.status_code == 200
    assert response.json()["capture_buffered"] is True
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()

    saved = []
    monkeypatch.setattr(main, "model_bundle_id", "bundle-new")
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: pytest.fail("Must reuse old analysis"))
    monkeypatch.setattr(database, "save_telemetry_capture",
                        lambda event, analysis: saved.append((event, analysis)) or event["event_id"])
    monkeypatch.setattr(database, "save_detection_result", lambda *args: "s")
    main._flush_telemetry_buffer()
    assert main._spool.count() == 0
    decisions = [analysis for _, analysis in saved if analysis is not None]
    assert decisions == [{"verdict": "BOT", "model_bundle_id": "bundle-original"}]
    assert all(event["capture_bundle_id"] == "bundle-original" for event, _ in saved)


@pytest.mark.parametrize("failure", ["full", "disk"])
def test_research_capture_never_acknowledges_failed_storage(client, monkeypatch, failure):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)

    def outage(*args):
        raise database.DatabasePersistenceError("offline")

    def enqueue(event):
        if failure == "disk":
            raise OSError("disk full")
        return None

    monkeypatch.setattr(database, "save_telemetry_capture", outage)
    monkeypatch.setattr(main._spool, "enqueue", enqueue)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: pytest.fail("No capture, no inference"))
    response = client.post("/api/v1/telemetry", json={"sessionId": "s", "visitorId": "v"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "10"
    assert not main.telemetry_buffer


def test_research_capture_retry_uses_same_id_and_attaches_actual_analysis(client, monkeypatch):
    from api_service import database, main

    saved = []
    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(main, "_require_inference_models", lambda: None)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: {"verdict": "SUSPECT"})
    monkeypatch.setattr(database, "save_telemetry_capture",
                        lambda event, analysis=None: saved.append((event, analysis)) or event["event_id"])
    monkeypatch.setattr(database, "save_detection_result", lambda *args: "s")
    payload = {"sessionId": "s", "visitorId": "v", "timestamp": 1234, "sequence": 0}
    first = client.post("/api/v1/telemetry", json=payload)
    retry = client.post("/api/v1/telemetry", json=payload)
    assert first.json()["capture_id"] == retry.json()["capture_id"]
    assert first.json()["analysis_available"] is True
    assert [analysis is None for _, analysis in saved] == [True, False, True, False]
    assert saved[1][1]["model_bundle_id"] == main.model_bundle_id


def test_research_capture_replay_requeues_outage_without_inference(client, monkeypatch):
    from api_service import database, main
    from api_service.capture import build_capture

    capture = build_capture({"sessionId": "s", "visitorId": "v"}, received_at=int(time.time() * 1000),
                            client_ip="ip", user_agent="ua", bundle_id="old", policy_version="10",
                            retention_days=7)
    assert main._buffer_telemetry({"sessionId": "s", "_capture_snapshot": capture})

    def outage(*args):
        raise database.DatabasePersistenceError("offline")

    monkeypatch.setattr(database, "save_telemetry_capture", outage)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: pytest.fail("Must not infer"))
    for _ in range(main.settings.MAX_TELEMETRY_RETRIES + 2):
        main._flush_telemetry_buffer()
    assert main._spool.count() == 1
    assert len(main.telemetry_buffer) == 1
    main._purge_session_from_memory("s")
    assert main._spool.count() == 0


def test_expired_research_capture_is_removed_during_database_outage(client, monkeypatch):
    from api_service import database, main
    from api_service.capture import build_capture

    capture = build_capture({"sessionId": "s", "visitorId": "v"}, received_at=0,
                            client_ip="ip", user_agent="ua", bundle_id="old", policy_version="10",
                            retention_days=7)
    # A non-capture event at the head must not prevent expired research cleanup.
    assert main._buffer_telemetry({"sessionId": "ahead"}, {"verdict": "SUSPECT"})
    assert main._buffer_telemetry({"sessionId": "s", "_capture_snapshot": capture})
    monkeypatch.setattr(database, "save_telemetry_capture", lambda *args: pytest.fail("Already expired"))
    monkeypatch.setattr(database, "save_detection_result", lambda *args: None)
    monkeypatch.setattr(database, "is_database_ready", lambda: False)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: pytest.fail("Must not infer"))
    main._flush_telemetry_buffer()
    assert main._spool.count() == 1
    assert [event["sessionId"] for event in main.telemetry_buffer] == ["ahead"]


def test_capture_is_recorded_even_when_latest_session_rejects_stale_event(client, monkeypatch):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(main, "_require_inference_models", lambda: None)
    monkeypatch.setattr(main.ensemble_detector, "predict", lambda data: {"verdict": "SUSPECT"})
    monkeypatch.setattr(database, "save_telemetry_capture", lambda event, analysis=None: event["event_id"])
    monkeypatch.setattr(database, "save_detection_result", lambda *args: None)
    monkeypatch.setattr(database, "is_database_ready", lambda: True)
    response = client.post("/api/v1/telemetry", json={"sessionId": "s", "visitorId": "v"})
    assert response.json()["recorded"] is True
    assert response.json()["persisted"] is False
    assert response.json()["capture_persisted"] is True


@pytest.mark.parametrize("paused", [True, False])
def test_research_capture_rejection_is_not_buffered(client, monkeypatch, paused):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)

    def reject(*args):
        if paused:
            raise database.DatabaseIngestionPaused(5)
        return None

    monkeypatch.setattr(database, "save_telemetry_capture", reject)
    response = client.post("/api/v1/telemetry", json={"sessionId": "s", "visitorId": "v"})
    assert response.status_code == (503 if paused else 409)
    assert main._spool.count() == 0


def test_invalid_capture_payload_never_reaches_storage(client, monkeypatch):
    from api_service import database, main

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(database, "save_telemetry_capture", lambda *args: pytest.fail("Invalid payload"))
    response = client.post("/api/v1/telemetry",
                           content='{"sessionId":"s","visitorId":"v","fingerprint":{"x":1e999}}')
    assert response.status_code == 422


def test_model_bundle_verification_detects_tampering(tmp_path):
    from core_ml.model_bundle import ModelBundleError, verify_model_bundle

    artifacts = {}
    for filename, content in (
        ("tabular_model.joblib", b"tabular"),
        ("behavioral_lstm.pt", b"lstm"),
    ):
        (tmp_path / filename).write_bytes(content)
        artifacts[filename] = hashlib.sha256(content).hexdigest()
    (tmp_path / "model_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "bundle_id": "0123456789abcdef0123456789abcdef",
            "feature_names": ["feature-a"],
            "artifacts": artifacts,
        }),
        encoding="utf-8",
    )

    assert verify_model_bundle(str(tmp_path), ["feature-a"])["schema_version"] == 1
    (tmp_path / "behavioral_lstm.pt").write_bytes(b"tampered")
    with pytest.raises(ModelBundleError, match="hash mismatch"):
        verify_model_bundle(str(tmp_path), ["feature-a"])


def test_model_bundle_requires_traceable_bundle_id(tmp_path):
    from core_ml.model_bundle import ModelBundleError, verify_model_bundle

    artifacts = {}
    for filename in ("tabular_model.joblib", "behavioral_lstm.pt"):
        content = filename.encode("utf-8")
        (tmp_path / filename).write_bytes(content)
        artifacts[filename] = hashlib.sha256(content).hexdigest()
    (tmp_path / "model_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "feature_names": [],
            "artifacts": artifacts,
        }),
        encoding="utf-8",
    )

    with pytest.raises(ModelBundleError, match="bundle_id"):
        verify_model_bundle(str(tmp_path), [])


def test_model_bundle_requires_manifest_by_default(tmp_path):
    from core_ml.model_bundle import ModelBundleError, verify_model_bundle

    with pytest.raises(ModelBundleError, match="manifest is missing"):
        verify_model_bundle(str(tmp_path), [])


def test_index_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "models" in data


def test_index_does_not_claim_fallback_inference_when_models_are_missing(client, monkeypatch):
    monkeypatch.setattr("api_service.main.lstm_loaded", False)
    monkeypatch.setattr("api_service.main.tabular_loaded", False)

    models = client.get("/").json()["models"]

    assert models["behavioral_lstm"] == "unavailable"
    assert models["tabular_xgboost"] == "unavailable"


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code in (200, 503)
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert "models_loaded" in data
    assert "database" in data
    assert "inference_ready" in data
    assert data["telemetry_buffer"]["capacity"] > 0
    assert data["telemetry_buffer"]["dropped_total"] >= 0


def test_health_detects_runtime_inference_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)

    def fail_probe(_payload):
        raise RuntimeError("broken model runtime")

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", fail_probe)
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["inference_ready"] is False


def test_health_probe_contains_enough_mouse_data_to_execute_lstm(client, monkeypatch):
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    observed = []

    def inspect_probe(payload):
        observed.append(len(payload["mouse"]["records"]))
        return {"bot_probability": 0.5}

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", inspect_probe)
    response = client.get("/health")

    assert response.status_code == 200
    assert observed == [25, 37]


def test_health_probe_is_cached(client, monkeypatch):
    calls = {"database": 0, "inference": 0}

    def database_ready():
        calls["database"] += 1
        return True

    def predict(_payload):
        calls["inference"] += 1
        return {"bot_probability": 0.5}

    monkeypatch.setattr("api_service.database.is_database_ready", database_ready)
    monkeypatch.setattr("api_service.main.ensemble_detector.predict", predict)

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert calls == {"database": 1, "inference": 2}


def test_application_lifespan_starts_and_stops_maintenance(monkeypatch):
    import api_service.main as main_module

    calls = []

    async def maintenance():
        calls.append("maintenance")
        await asyncio.Future()

    monkeypatch.setattr(main_module, "_maintenance_loop", maintenance)

    with TestClient(main_module.app):
        assert calls == ["maintenance"]


def test_maintenance_loop_survives_failed_iteration(monkeypatch):
    import api_service.main as main_module

    calls = []

    async def no_wait(_seconds):
        return None

    async def run_iteration(_function):
        calls.append("flush")
        if len(calls) == 1:
            raise RuntimeError("temporary maintenance failure")
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module.asyncio, "sleep", no_wait)
    monkeypatch.setattr(main_module, "run_in_threadpool", run_iteration)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module._maintenance_loop())

    assert calls == ["flush", "flush"]


def test_detect_bot_human(client):
    payload = {
        "sessionId": "sess_test_human",
        "visitorId": "dev_test_human",
        "pageUrl": "https://example.com/shop",
        "fingerprint": {
            "hardwareConcurrency": 8,
            "deviceMemory": 16,
            "screenResolution": "1920x1080",
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        "botd": {
            "heuristicScore": 0.0,
            "detectors": {"webdriver": False, "virtualGpu": False},
        },
        "mouse": {
            "records": [
                {"time": i * 16, "x": 0.2 + i * 0.005, "y": 0.3 + (i % 3) * 0.002, "type": "move"}
                for i in range(25)
            ]
        },
    }
    res = client.post("/api/v1/detect", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "is_bot" in data
    assert "bot_probability" in data
    assert "latency_ms" in data
    assert data["model_bundle_id"]
    assert 0 <= data["latency_ms"] < 2000
    assert data["sessionId"] == "sess_test_human"


def test_detect_reports_inference_failure_as_unavailable(client, monkeypatch):
    def fail_inference(_payload):
        raise RuntimeError("runtime failure")

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", fail_inference)

    response = client.post("/api/v1/detect", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "Inference temporarily unavailable"


def test_telemetry_does_not_buffer_inference_failures(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    def fail_inference(_payload):
        raise RuntimeError("runtime failure")

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", fail_inference)
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()

    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": "inference-failure", "visitorId": "visitor"},
    )

    assert response.status_code == 503
    with _telemetry_buffer_lock:
        assert not telemetry_buffer


def test_detect_client_flag_without_mouse_defers_decision(client):
    payload = {
        "sessionId": "sess_test_bot",
        "visitorId": "dev_test_bot",
        "botd": {
            "heuristicScore": 0.95,
            "detectors": {"headlessUa": True, "pluginsInconsistency": True},
            "reasons": ["User-Agent explicitly declares HeadlessChrome"],
        },
    }
    res = client.post("/api/v1/detect", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_bot"] is False
    assert data["verdict"] == "SUSPECT"
    assert data["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert data["score_calibrated"] is False
    assert data["policy_version"] == DECISION_POLICY_VERSION

    # Policy 12: a framework artefact decides on its own, even without mouse input.
    payload["botd"]["detectors"] = {"webdriver": True}
    marker = client.post("/api/v1/detect", json=payload).json()
    assert marker["verdict"] == "BOT" and marker["decision_state"] == "FINAL"
    assert marker["breakdown"]["decision_basis"] == "automation_marker"


def test_explicit_automation_rule_uses_http_user_agent_not_json_override(client):
    headless = "Mozilla/5.0 HeadlessChrome/154.0.0.0"
    payload = {
        "sessionId": "sess_rule_detect",
        "fingerprint": {"userAgent": headless},
        "botd": {"detectors": {"webdriver": True}},
        "mouse": {"records": []},
        "_server_user_agent": headless,
    }
    uncorroborated = client.post("/api/v1/detect", json=payload)
    assert uncorroborated.status_code == 200
    # The JSON UA override cannot trigger the headless rule; webdriver is still a
    # framework marker under policy 12, so the basis shows which rule decided.
    assert uncorroborated.json()["breakdown"]["decision_basis"] == "automation_marker"

    corroborated = client.post(
        "/api/v1/detect", json=payload, headers={"User-Agent": headless},
    )
    assert corroborated.status_code == 200
    decision = corroborated.json()
    assert decision["verdict"] == "BOT"
    assert decision["decision_state"] == "FINAL"
    assert decision["breakdown"]["decision_basis"] == "explicit_automation"
    assert decision["breakdown"]["risk_score_in_domain"] is False


def test_telemetry_persists_explicit_automation_verdict(client, monkeypatch):
    headless = "Mozilla/5.0 HeadlessChrome/154.0.0.0"
    captured = {}

    def save(_telemetry, analysis):
        captured.update(analysis)
        return True

    monkeypatch.setattr("api_service.database.save_detection_result", save)
    response = client.post(
        "/api/v1/telemetry",
        json={
            "sessionId": "sess_rule_telemetry",
            "visitorId": "visitor_rule",
            "fingerprint": {"userAgent": headless},
            "botd": {"detectors": {"chromeDriverGlobal": True}},
            "mouse": {"records": []},
        },
        headers={"User-Agent": headless},
    )
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert captured["verdict"] == "BOT"
    assert captured["breakdown"]["decision_basis"] == "explicit_automation"
    assert captured["breakdown"]["suspect_reason_codes"] == []


def test_telemetry_persists_suspect_diagnostic_codes(client, monkeypatch):
    captured = {}

    def save(_telemetry, analysis):
        captured.update(analysis)
        return True

    monkeypatch.setattr("api_service.database.save_detection_result", save)
    response = client.post(
        "/api/v1/telemetry",
        json={
            "sessionId": "sess_suspect_diagnostic",
            "visitorId": "visitor_suspect_diagnostic",
            "botd": {"heuristicScore": 0.95},
            "mouse": {"records": []},
        },
    )

    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert captured["verdict"] == "SUSPECT"
    assert captured["breakdown"]["suspect_reason_codes"] == [
        "INSUFFICIENT_MOUSE", "HIGH_CLIENT_HEURISTIC_SCORE",
    ]


def test_health_distinguishes_model_load_from_release_evidence(client):
    response = client.get("/health")

    assert response.status_code in (200, 503)
    health = response.json()
    assert health["model_bundle_valid"] is True
    assert health["decision_policy_version"] == DECISION_POLICY_VERSION
    assert health["release_gate_evidence_present"] is True


def test_profile_shadow_survives_detect_and_telemetry_without_promoting_verdict(client, monkeypatch):
    captured = {}

    def save(_telemetry, analysis):
        captured.update(analysis)
        return True

    monkeypatch.setattr("api_service.database.save_detection_result", save)
    payload = {
        "sessionId": "profile-shadow", "visitorId": "profile-visitor",
        "botd": {"profile": {
            "schema": "browser-profile-v1", "workerStatus": "unsupported",
            "main": {"clientHints": {"brands": [{"brand": "HeadlessChrome", "version": "153"}]}},
        }},
        "mouse": {"records": []},
    }
    response = client.post("/api/v1/detect", json=payload)
    assert response.status_code == 200
    decision = response.json()
    assert decision["verdict"] == "SUSPECT"
    assert decision["policy_version"] == DECISION_POLICY_VERSION
    assert decision["breakdown"]["profile_shadow"]["shadow_verdict"] == "BOT"
    response = client.post("/api/v1/telemetry", json=payload)
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert captured["verdict"] == "SUSPECT"
    assert captured["breakdown"]["profile_shadow"] == decision["breakdown"]["profile_shadow"]


def test_interaction_measurements_round_trip_without_promoting_verdict(client, monkeypatch):
    captured = {}

    def save(_telemetry, analysis):
        captured.update(analysis)
        return True

    monkeypatch.setattr("api_service.database.save_detection_result", save)
    payload = {
        "sessionId": "interaction-shadow", "visitorId": "interaction-visitor",
        "mouse": {"records": [], "scrollEvents": [
            {"time": i * 20, "deltaX": 0, "deltaY": 120} for i in range(4)
        ]},
    }
    response = client.post("/api/v1/detect", json=payload)
    assert response.status_code == 200
    decision = response.json()
    measurement = decision["breakdown"]["interaction_shadow"]
    assert measurement["features"]["scroll_interval_cv"] == 0
    assert measurement["features"]["move_interval_cv"] is None
    assert measurement["mode"] == "measurement_only"
    assert decision["verdict"] == "SUSPECT"
    response = client.post("/api/v1/telemetry", json=payload)
    assert response.status_code == 200
    assert response.json()["persisted"] is True
    assert captured["breakdown"]["interaction_shadow"] == measurement
    assert captured["verdict"] == decision["verdict"]


def test_detect_empty_payload(client):
    res = client.post("/api/v1/detect", json={})
    assert res.status_code == 200
    data = res.json()
    assert "is_bot" in data
    assert "bot_probability" in data


def test_telemetry_async_ingestion(client, monkeypatch):
    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: "saved")
    payload = {
        "sessionId": "sess_beacon_1",
        "visitorId": "visitor_beacon_1",
        "action": "scroll",
        "mouse": {"records": []},
    }
    res = client.post("/api/v1/telemetry", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["recorded"] is True


def test_telemetry_beacon_text_plain_ingestion(client, monkeypatch):
    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: "saved")
    # Tests navigator.sendBeacon fallback where Content-Type is text/plain
    raw_json = '{"sessionId": "sess_beacon_text_plain", "visitorId": "visitor_beacon_text", "action": "leave", "mouse": {"records": []}}'
    res = client.post(
        "/api/v1/telemetry",
        content=raw_json.encode("utf-8"),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["recorded"] is True


def test_reverse_proxy_ip_forwarding(client, monkeypatch):
    monkeypatch.setattr(
        "api_service.main._is_trusted_proxy",
        lambda host: host == "testclient" or host.startswith("10."),
    )
    # Test Cloudflare header
    res = client.post(
        "/api/v1/detect",
        json={"sessionId": "sess_cf"},
        headers={"CF-Connecting-IP": "203.0.113.195"},
    )
    assert res.status_code == 200
    assert res.json()["client_ip"] == "203.0.113.195"

    # Test X-Forwarded-For
    res2 = client.post(
        "/api/v1/detect",
        json={"sessionId": "sess_xff"},
        headers={"X-Forwarded-For": "198.51.100.42, 10.0.0.1"},
    )
    assert res2.status_code == 200
    assert res2.json()["client_ip"] == "198.51.100.42"


def test_forwarded_chain_skips_only_trusted_proxy_hops(client, monkeypatch):
    monkeypatch.setattr(
        "api_service.main._is_trusted_proxy",
        lambda host: host == "testclient" or host.startswith("10."),
    )
    response = client.post(
        "/api/v1/detect",
        json={"sessionId": "proxy-chain"},
        headers={"X-Forwarded-For": "192.0.2.10, 198.51.100.20, 10.0.0.2"},
    )

    assert response.json()["client_ip"] == "198.51.100.20"


def test_untrusted_client_cannot_spoof_forwarded_ip(client):
    res = client.post(
        "/api/v1/detect",
        json={"sessionId": "sess_untrusted_proxy"},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert res.status_code == 200
    assert res.json()["client_ip"] != "198.51.100.99"


def test_invalid_proxy_entry_does_not_disable_valid_network(monkeypatch):
    from api_service.config import settings
    from api_service.main import _is_trusted_proxy

    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["invalid-cidr", "172.16.0.0/12"])

    assert _is_trusted_proxy("172.18.0.5") is True
    assert _is_trusted_proxy("203.0.113.5") is False


def test_rate_limiter_blocks_excessive_traffic(client, monkeypatch):
    from api_service.config import settings
    monkeypatch.setattr("api_service.main._is_trusted_proxy", lambda _host: True)
    orig_limit = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 3  # temporarily set low limit for test

    test_ip = "192.0.2.99"
    try:
        # First 3 requests succeed
        for i in range(3):
            r = client.post(
                "/api/v1/detect",
                json={"sessionId": f"sess_rl_{i}"},
                headers={"CF-Connecting-IP": test_ip},
            )
            assert r.status_code == 200

        # 4th request must be blocked with HTTP 429 Too Many Requests
        r4 = client.post(
            "/api/v1/detect",
            json={"sessionId": "sess_rl_blocked"},
            headers={"CF-Connecting-IP": test_ip},
        )
        assert r4.status_code == 429
        assert "Rate limit exceeded" in r4.json()["detail"]
        assert "retry-after" in r4.headers
    finally:
        settings.RATE_LIMIT_PER_MINUTE = orig_limit


def test_rate_limiter_does_not_clear_active_clients_at_capacity():
    import time
    from api_service.main import _rate_limit_records, check_rate_limit

    now = time.monotonic()
    _rate_limit_records.clear()
    for index in range(10000):
        _rate_limit_records[f"192.0.2.{index}"] = [now]

    assert check_rate_limit("new-client") is False
    assert len(_rate_limit_records) == 10000
    assert check_rate_limit("192.0.2.1") is True
    _rate_limit_records.clear()


def test_get_bot_collector_sdk(client):
    res = client.get("/bot-collector.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    assert res.headers["cache-control"] == "public, no-cache"
    assert "BotCollector" in res.text


def test_dashboard_uses_only_real_mouse_trajectory(client, monkeypatch):
    from api_service import auth

    monkeypatch.setattr(auth, "session_user", lambda token: {"username": "admin", "role": "admin"})
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "<title>DATACAT</title>" in res.text
    assert "CHỜ DỮ LIỆU" not in res.text
    assert "/api/v1/traffic/timeline" in res.text
    assert 'id="timelineRange"' in res.text
    assert '<option value="1440" selected>24 giờ</option>' in res.text
    assert '<option value="43200">30 ngày</option>' in res.text
    assert "?window_minutes=${requestedRange}" in res.text
    assert "/api/v1/stats/summary" in res.text
    assert "table-layout: fixed" in res.text
    assert "/api/v1/graph/" not in res.text
    assert "let previousBotSessions = null" in res.text
    assert "!previousBotSessions.has(sessionId)" in res.text
    assert "MAX_TIMELINE_INTERVALS" not in res.text
    assert "suggestedMax: 1" in res.text
    assert "Không đủ dữ liệu quỹ đạo chuột thô" in res.text
    assert "sessionSelectionVersion" in res.text
    assert "models.tabular && models.lstm" in res.text
    assert "Fallback: generate representative trajectory" not in res.text
    assert "const controller = new AbortController()" in res.text
    assert "let activePoll = null" in res.text
    assert "handleUnauthorized(res)" in res.text
    assert "bot_read_token" not in res.text
    assert "http://159.223.91.163/san-pham" not in res.text
    assert "data.sessions.map(sessionRevision)" in res.text
    assert "refreshSelectedTrajectory(selectedSession)" in res.text
    assert "Mô hình tốt, cơ sở dữ liệu suy giảm" in res.text
    assert "const POLL_INTERVAL = 5000" in res.text
    assert "function parseScreenResolution(value)" in res.text
    assert "for (let i = 0; i < 40; i++)" in res.text
    assert "await Promise.all([fetchClassificationSummary(), fetchTrafficTimeline()])" in res.text


def test_recent_telemetry_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_recent_results", lambda limit, site_filter=None: None)
    monkeypatch.setattr("api_service.database.get_total_count", lambda site_filter=None: 1)

    response = client.get("/api/v1/telemetry/recent", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_recent_telemetry_reports_database_total_with_compatibility_alias(
    client, monkeypatch
):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr(
        "api_service.database.get_recent_results",
        lambda limit, site_filter=None: [{"sessionId": "session-1"}],
    )
    monkeypatch.setattr("api_service.database.get_total_count", lambda site_filter=None: 7)

    response = client.get("/api/v1/telemetry/recent", headers=READ_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "total": 7,
        "total_buffered": 7,
        "returned": 1,
        "sessions": [{"sessionId": "session-1"}],
    }


def test_traffic_timeline_defaults_to_one_hour_window(client, monkeypatch):
    timeline = {
        "window_start": 1_000,
        "window_end": 3_601_000,
        "window_minutes": 60,
        "bucket_minutes": 1,
        "buckets": [
            {"start": 1_000, "human": 700, "suspect": 200, "bot": 100, "total": 1000}
        ],
    }
    query_args = {}

    def fake_timeline(window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None):
        query_args.update(window_minutes=window_minutes, bucket_minutes=bucket_minutes)
        return timeline

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)

    response = client.get("/api/v1/traffic/timeline", headers=READ_HEADERS)

    assert response.status_code == 200
    assert response.json() == timeline
    assert query_args == {"window_minutes": 60, "bucket_minutes": 1}


@pytest.mark.parametrize(
    ("window_minutes", "expected_bucket_minutes"),
    [(30, 1), (120, 2), (240, 5), (360, 5), (720, 10), (1440, 15), (10080, 60), (43200, 1440)],
)
def test_traffic_timeline_uses_adaptive_buckets(
    client,
    monkeypatch,
    window_minutes,
    expected_bucket_minutes,
):
    query_args = {}

    def fake_timeline(window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None):
        query_args.update(window_minutes=window_minutes, bucket_minutes=bucket_minutes)
        return {
            "window_minutes": window_minutes,
            "bucket_minutes": bucket_minutes,
            "buckets": [],
        }

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)

    response = client.get(
        f"/api/v1/traffic/timeline?window_minutes={window_minutes}",
        headers=READ_HEADERS,
    )

    assert response.status_code == 200
    assert query_args == {
        "window_minutes": window_minutes,
        "bucket_minutes": expected_bucket_minutes,
    }


def test_traffic_timeline_rejects_out_of_range_windows(client):
    assert client.get(
        "/api/v1/traffic/timeline?window_minutes=29", headers=READ_HEADERS
    ).status_code == 422
    assert client.get(
        "/api/v1/traffic/timeline?window_minutes=43201", headers=READ_HEADERS
    ).status_code == 422
    assert client.get(
        "/api/v1/traffic/timeline?utc_offset_minutes=900", headers=READ_HEADERS
    ).status_code == 422


def test_traffic_timeline_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr(
        "api_service.database.get_traffic_timeline",
        lambda window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None: None,
    )

    response = client.get("/api/v1/traffic/timeline", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Traffic timeline query failed"


def test_summary_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_summary_stats", lambda site_filter=None: None)

    response = client.get("/api/v1/stats/summary", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_summary_reports_recent_inference_latency(client, monkeypatch):
    from api_service import main

    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_summary_stats",
                        lambda site_filter=None: {"total": 3, "humans": 2, "bots": 1, "suspects": 0})
    monkeypatch.setattr(main, "_inference_latency_ms", main.collections.deque(maxlen=500))

    empty = client.get("/api/v1/stats/summary", headers=READ_HEADERS).json()
    assert empty["inference_latency"] is None and empty["bots"] == 1

    main._inference_latency_ms.extend([10.0, 20.0, 30.0, 40.0])
    latency = client.get("/api/v1/stats/summary", headers=READ_HEADERS).json()["inference_latency"]
    assert latency == {"avg_ms": 25.0, "p95_ms": 40.0, "samples": 4}


def test_invalid_telemetry_is_rejected(client):
    res = client.post("/api/v1/telemetry", content=b"not-json", headers={"Content-Type": "text/plain"})
    assert res.status_code == 400


@pytest.mark.parametrize("field", ["records", "trajectory"])
def test_non_array_mouse_records_are_rejected(client, field):
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": "bad-mouse", "visitorId": "visitor", "mouse": {field: 7}},
    )
    assert response.status_code == 422


def test_retry_after_is_exposed_to_cross_origin_collector(client, monkeypatch):
    from api_service.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    origin = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS[0] != "*" else "https://example.com"
    headers = {"Origin": origin}
    payload = {"sessionId": "rate-limited", "visitorId": "visitor"}
    client.post("/api/v1/telemetry", content=b"not-json", headers=headers)
    response = client.post("/api/v1/telemetry", json=payload, headers=headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "retry-after" in response.headers["Access-Control-Expose-Headers"].lower()


def test_excessively_nested_telemetry_is_rejected(client):
    nested = "[" * 2000 + "0" + "]" * 2000
    body = (
        '{"sessionId":"deep-json","visitorId":"visitor","fingerprint":{"nested":'
        + nested
        + "}}"
    )

    response = client.post(
        "/api/v1/telemetry",
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_non_finite_json_numbers_are_rejected(client):
    response = client.post(
        "/api/v1/telemetry",
        content=b'{"sessionId":"s","visitorId":"v","fingerprint":{"value":NaN}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_telemetry_requires_visitor_id(client):
    res = client.post("/api/v1/telemetry", json={"sessionId": "session-without-visitor"})
    assert res.status_code == 422


def test_monitoring_endpoints_require_read_token(client):
    assert client.get("/api/v1/telemetry/recent").status_code == 401
    assert client.get("/api/v1/traffic/timeline").status_code == 401


def test_oversized_payload_is_rejected(client):
    from api_service.config import settings
    body = b"x" * (settings.MAX_PAYLOAD_BYTES + 1)
    res = client.post("/api/v1/telemetry", content=body, headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_chunked_payload_is_limited_before_buffering():
    from api_service.main import RequestBodyLimitMiddleware

    async def consume_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break

    messages = [
        {"type": "http.request", "body": b"a" * 6, "more_body": True},
        {"type": "http.request", "body": b"b" * 6, "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "headers": [(b"transfer-encoding", b"chunked")]}
    asyncio.run(RequestBodyLimitMiddleware(consume_body, max_bytes=10)(scope, receive, send))
    assert any(message.get("status") == 413 for message in sent)


def test_rejected_telemetry_is_not_added_to_fallback_buffer(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: None)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    session_id = "rejected-tombstoned-event"
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": session_id, "visitorId": "visitor"},
    )

    assert response.status_code == 200
    assert response.json()["recorded"] is False
    assert response.json()["buffered"] is False
    with _telemetry_buffer_lock:
        assert all(event.get("sessionId") != session_id for event in telemetry_buffer)


def test_deleted_live_session_tells_the_collector_to_rotate(client, monkeypatch):
    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: None)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    monkeypatch.setattr("api_service.database.is_session_closed", lambda session_id: session_id == "deleted-tab")

    closed = client.post("/api/v1/telemetry", json={"sessionId": "deleted-tab", "visitorId": "visitor"}).json()
    assert closed["recorded"] is False and closed["session_closed"] is True
    stale = client.post("/api/v1/telemetry", json={"sessionId": "stale-tab", "visitorId": "visitor"}).json()
    assert "session_closed" not in stale


def test_database_outage_uses_fallback_buffer(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: None)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: False)
    session_id = "database-outage-event"
    try:
        response = client.post(
            "/api/v1/telemetry",
            json={"sessionId": session_id, "visitorId": "visitor"},
        )

        assert response.status_code == 200
        assert response.json()["recorded"] is True
        assert response.json()["buffered"] is True
        with _telemetry_buffer_lock:
            assert any(event.get("sessionId") == session_id for event in telemetry_buffer)
    finally:
        with _telemetry_buffer_lock:
            retained = [event for event in telemetry_buffer if event.get("sessionId") != session_id]
            telemetry_buffer.clear()
            telemetry_buffer.extend(retained)


def test_admin_ingestion_pause_returns_retry_without_buffering(client, monkeypatch):
    from api_service.database import DatabaseIngestionPaused
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    def paused_write(_data, _analysis):
        raise DatabaseIngestionPaused(5)

    monkeypatch.setattr("api_service.database.save_detection_result", paused_write)
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": "new-during-delete", "visitorId": "visitor"},
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    with _telemetry_buffer_lock:
        assert all(event.get("sessionId") != "new-during-delete" for event in telemetry_buffer)


def test_database_write_exception_is_buffered_even_when_ping_is_healthy(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    def fail_write(_data, _analysis):
        raise RuntimeError("primary stepped down")

    monkeypatch.setattr("api_service.database.save_detection_result", fail_write)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    session_id = "write-exception-event"
    try:
        response = client.post(
            "/api/v1/telemetry",
            json={"sessionId": session_id, "visitorId": "visitor"},
        )

        assert response.status_code == 200
        assert response.json()["recorded"] is True
        assert response.json()["buffered"] is True
        with _telemetry_buffer_lock:
            assert any(event.get("sessionId") == session_id for event in telemetry_buffer)
    finally:
        with _telemetry_buffer_lock:
            retained = [event for event in telemetry_buffer if event.get("sessionId") != session_id]
            telemetry_buffer.clear()
            telemetry_buffer.extend(retained)


def test_buffered_telemetry_reuses_original_inference(client, monkeypatch):
    from api_service.main import (
        _flush_telemetry_buffer,
        _telemetry_buffer_lock,
        telemetry_buffer,
    )

    decisions = {"count": 0}

    def predict(_data):
        decisions["count"] += 1
        return {"verdict": "HUMAN", "bot_probability": 0.1}

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", predict)
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda _data, _analysis: (_ for _ in ()).throw(RuntimeError("temporary outage")),
    )
    session_id = "reuse-original-analysis"
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": session_id, "visitorId": "visitor"},
    )
    assert response.status_code == 200
    assert response.json()["buffered"] is True
    assert decisions["count"] == 1

    persisted = []
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, analysis: persisted.append((data["sessionId"], analysis["verdict"]))
        or data["sessionId"],
    )
    monkeypatch.setattr(
        "api_service.main.ensemble_detector.predict",
        lambda _data: (_ for _ in ()).throw(AssertionError("inference must not run again")),
    )

    _flush_telemetry_buffer()

    assert persisted == [(session_id, "HUMAN")]
    with _telemetry_buffer_lock:
        assert all(event.get("sessionId") != session_id for event in telemetry_buffer)


def test_buffered_telemetry_survives_process_restart(client, monkeypatch):
    from api_service import main
    from api_service.spool import TelemetrySpool

    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda _data, _analysis: (_ for _ in ()).throw(RuntimeError("database offline")),
    )
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": "restart-session", "visitorId": "visitor"},
    )
    assert response.status_code == 200
    assert response.json()["recorded"] is True
    assert main._spool.count() == 1

    spool_path = main._spool.path
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()
    monkeypatch.setattr(
        main, "_spool", TelemetrySpool(spool_path, main.settings.MAX_BUFFER_SIZE),
    )
    main._restore_telemetry_spool()
    persisted = []
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, _analysis: persisted.append(data["sessionId"]) or data["sessionId"],
    )
    main._flush_telemetry_buffer()
    assert persisted == ["restart-session"]
    assert main._spool.count() == 0


def test_inflight_purge_cannot_delete_newly_acknowledged_event(monkeypatch):
    from api_service import main
    from api_service.spool import TelemetrySpool

    assert main._buffer_telemetry({"sessionId": "old"}, {"verdict": "HUMAN"})
    old_identifier = main.telemetry_buffer[0]["_spool_id"]

    def save_during_purge(data, _analysis):
        main._purge_session_from_memory("old")
        assert main._buffer_telemetry({"sessionId": "new"}, {"verdict": "SUSPECT"})
        assert main.telemetry_buffer[0]["_spool_id"] != old_identifier
        return data["sessionId"]

    monkeypatch.setattr("api_service.database.save_detection_result", save_during_purge)
    main._flush_telemetry_buffer(max_events=1)
    assert main._spool.count() == 1

    spool_path = main._spool.path
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()
    monkeypatch.setattr(main, "_spool", TelemetrySpool(spool_path, main.settings.MAX_BUFFER_SIZE))
    main._restore_telemetry_spool()
    assert [event["sessionId"] for event in main.telemetry_buffer] == ["new"]


def test_replay_keeps_original_model_bundle_after_restart(monkeypatch):
    from api_service import main
    from api_service.spool import TelemetrySpool

    assert main._buffer_telemetry(
        {"sessionId": "old-model"},
        {"verdict": "HUMAN", "policy_version": "7", "model_bundle_id": "bundle-before"},
    )
    spool_path = main._spool.path
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()
    monkeypatch.setattr(main, "_spool", TelemetrySpool(spool_path, main.settings.MAX_BUFFER_SIZE))
    monkeypatch.setattr(main, "model_bundle_id", "bundle-after")
    captured = []
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, analysis: captured.append(dict(analysis)) or data["sessionId"],
    )
    main._flush_telemetry_buffer()

    assert captured == [{
        "verdict": "HUMAN", "policy_version": "7", "model_bundle_id": "bundle-before",
    }]
    assert main._spool.count() == 0


def test_spool_restore_cannot_resurrect_deleted_session(monkeypatch):
    from api_service import main

    assert main._buffer_telemetry({"sessionId": "delete-race"})
    loaded = threading.Event()
    resume = threading.Event()
    purge_done = threading.Event()
    original_load = main._spool.load

    def paused_load():
        events = original_load()
        loaded.set()
        assert resume.wait(timeout=2)
        return events

    monkeypatch.setattr(main._spool, "load", paused_load)
    restore_thread = threading.Thread(target=main._restore_telemetry_spool)
    purge_thread = threading.Thread(
        target=lambda: (main._purge_session_from_memory("delete-race"), purge_done.set())
    )
    restore_thread.start()
    try:
        assert loaded.wait(timeout=2)
        purge_thread.start()
        assert not purge_done.wait(timeout=0.1)
    finally:
        resume.set()
        restore_thread.join(timeout=2)
        if purge_thread.ident is not None:
            purge_thread.join(timeout=2)

    assert purge_done.is_set()
    assert main._spool.count() == 0
    assert all(event.get("sessionId") != "delete-race" for event in main.telemetry_buffer)


def test_spool_failure_returns_retryable_error_without_ack(client, monkeypatch):
    from api_service import main

    monkeypatch.setattr(main, "_require_inference_models", lambda: None)
    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: None)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: False)

    def fail_disk(_event):
        raise OSError("disk unavailable")

    monkeypatch.setattr(main._spool, "enqueue", fail_disk)
    response = client.post(
        "/api/v1/telemetry",
        json={"sessionId": "spool-failure", "visitorId": "visitor"},
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
    assert main._spool.count() == 0
    assert all(event.get("sessionId") != "spool-failure" for event in main.telemetry_buffer)


def test_buffered_telemetry_is_flushed_after_database_recovery(monkeypatch):
    from api_service.main import (
        _flush_telemetry_buffer,
        _telemetry_buffer_lock,
        telemetry_buffer,
    )

    event = {"sessionId": "replay-session", "visitorId": "visitor", "client_ip": "192.0.2.1"}
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.append(event)
    persisted = []
    monkeypatch.setattr("api_service.main.ensemble_detector.predict", lambda _data: {"verdict": "HUMAN"})
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, _analysis: persisted.append(data["sessionId"]) or data["sessionId"],
    )
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    _flush_telemetry_buffer()

    assert persisted == ["replay-session"]
    with _telemetry_buffer_lock:
        assert not telemetry_buffer


def test_buffered_telemetry_is_requeued_when_inference_fails(monkeypatch):
    from api_service.main import (
        _flush_telemetry_buffer,
        _telemetry_buffer_lock,
        telemetry_buffer,
    )

    event = {"sessionId": "retry-session", "visitorId": "visitor"}
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.append(event)
    monkeypatch.setattr(
        "api_service.main.ensemble_detector.predict",
        lambda _data: (_ for _ in ()).throw(RuntimeError("temporary inference failure")),
    )

    _flush_telemetry_buffer()

    with _telemetry_buffer_lock:
        assert list(telemetry_buffer) == [event]
        telemetry_buffer.clear()


def test_poisoned_replay_does_not_block_later_events(monkeypatch):
    from api_service.main import (
        _flush_telemetry_buffer,
        _telemetry_buffer_lock,
        telemetry_buffer,
    )

    poisoned = {"sessionId": "poisoned"}
    healthy = {"sessionId": "healthy"}
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.extend([poisoned, healthy])

    def predict(data):
        if data["sessionId"] == "poisoned":
            raise RuntimeError("bad event")
        return {"verdict": "HUMAN"}

    persisted = []
    monkeypatch.setattr("api_service.main.ensemble_detector.predict", predict)
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, _analysis: persisted.append(data["sessionId"]) or data["sessionId"],
    )
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)

    _flush_telemetry_buffer()

    assert persisted == ["healthy"]
    with _telemetry_buffer_lock:
        assert [event["sessionId"] for event in telemetry_buffer] == ["poisoned"]
        telemetry_buffer.clear()


def test_failed_replay_does_not_evict_newer_event_when_buffer_refills():
    from api_service.main import (
        _requeue_buffered_event,
        _telemetry_buffer_stats,
        telemetry_buffer,
        _telemetry_buffer_lock,
    )

    newer_events = [{"sessionId": f"new-{index}"} for index in range(telemetry_buffer.maxlen)]
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.extend(newer_events)

    dropped_before = _telemetry_buffer_stats["dropped_total"]
    assert _requeue_buffered_event({"sessionId": "old-failed"}) is False
    assert _telemetry_buffer_stats["dropped_total"] == dropped_before + 1

    with _telemetry_buffer_lock:
        assert list(telemetry_buffer) == newer_events
        telemetry_buffer.clear()


def test_replay_reserves_capacity_for_failed_event(monkeypatch):
    from api_service.main import (
        _buffer_telemetry,
        _flush_telemetry_buffer,
        _telemetry_buffer_lock,
        _telemetry_buffer_stats,
        telemetry_buffer,
    )

    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.extend(
            {"sessionId": str(index), "_buffered_analysis": {"verdict": "HUMAN"}}
            for index in range(telemetry_buffer.maxlen)
        )
        dropped_before = _telemetry_buffer_stats["dropped_total"]

    def fail_after_concurrent_ingest(_data, _analysis):
        assert _buffer_telemetry({"sessionId": "concurrent"}) is False
        raise RuntimeError("database went away")

    monkeypatch.setattr("api_service.database.save_detection_result", fail_after_concurrent_ingest)
    try:
        _flush_telemetry_buffer(max_events=1)
        with _telemetry_buffer_lock:
            assert len(telemetry_buffer) == telemetry_buffer.maxlen
            assert telemetry_buffer[0]["sessionId"] == "0"
            assert _telemetry_buffer_stats["dropped_total"] == dropped_before
    finally:
        with _telemetry_buffer_lock:
            telemetry_buffer.clear()


def test_admin_delete_does_not_requeue_old_replay(monkeypatch):
    from api_service.database import DatabaseIngestionPaused
    from api_service.main import _flush_telemetry_buffer, _telemetry_buffer_lock, telemetry_buffer

    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.append({
            "sessionId": "deleted-event",
            "_buffered_analysis": {"verdict": "HUMAN"},
        })

    def paused_write(_data, _analysis):
        raise DatabaseIngestionPaused(5)

    monkeypatch.setattr("api_service.database.save_detection_result", paused_write)

    _flush_telemetry_buffer(max_events=1)
    with _telemetry_buffer_lock:
        assert not telemetry_buffer


def test_full_telemetry_buffer_rejects_new_event_without_eviction():
    from api_service.main import (
        _buffer_telemetry,
        _telemetry_buffer_stats,
        telemetry_buffer,
        _telemetry_buffer_lock,
    )

    existing = [{"sessionId": f"old-{index}"} for index in range(telemetry_buffer.maxlen)]
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.extend(existing)
        dropped_before = _telemetry_buffer_stats["dropped_total"]

    assert _buffer_telemetry({"sessionId": "newest"}) is False

    with _telemetry_buffer_lock:
        assert len(telemetry_buffer) == telemetry_buffer.maxlen
        assert list(telemetry_buffer) == existing
        assert _telemetry_buffer_stats["dropped_total"] == dropped_before
        telemetry_buffer.clear()


def test_full_telemetry_buffer_returns_retryable_error(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    monkeypatch.setattr("api_service.database.save_detection_result", lambda _data, _analysis: None)
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: False)
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()
        telemetry_buffer.extend({"sessionId": str(index)} for index in range(telemetry_buffer.maxlen))

    try:
        response = client.post(
            "/api/v1/telemetry",
            json={"sessionId": "retry-me", "visitorId": "visitor"},
        )
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "10"
        with _telemetry_buffer_lock:
            assert len(telemetry_buffer) == telemetry_buffer.maxlen
            assert all(event["sessionId"] != "retry-me" for event in telemetry_buffer)
    finally:
        with _telemetry_buffer_lock:
            telemetry_buffer.clear()


def test_delete_requires_admin_token(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock
    from api_service.config import settings
    original_token = settings.ADMIN_TOKEN
    settings.ADMIN_TOKEN = "test-secret"
    monkeypatch.setattr("api_service.database.delete_all_sessions", lambda: 3)
    with _telemetry_buffer_lock:
        telemetry_buffer.append({"sessionId": "delete-all-memory"})
    try:
        assert client.delete("/api/v1/sessions").status_code == 401
        res = client.delete("/api/v1/sessions", headers={"X-Admin-Token": "test-secret"})
        assert res.status_code == 200
        assert res.json()["count"] == 3
        with _telemetry_buffer_lock:
            assert len(telemetry_buffer) == 0
    finally:
        settings.ADMIN_TOKEN = original_token


def test_delete_session_purges_in_memory_data(client, monkeypatch):
    from api_service.config import settings
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    original_token = settings.ADMIN_TOKEN
    settings.ADMIN_TOKEN = "test-secret"
    monkeypatch.setattr("api_service.database.delete_session", lambda _session_id: False)
    with _telemetry_buffer_lock:
        telemetry_buffer.append({"sessionId": "memory-only"})
    try:
        response = client.delete(
            "/api/v1/sessions/memory-only",
            headers={"X-Admin-Token": "test-secret"},
        )
        assert response.status_code == 200
        with _telemetry_buffer_lock:
            assert all(event.get("sessionId") != "memory-only" for event in telemetry_buffer)
    finally:
        settings.ADMIN_TOKEN = original_token


def test_raw_endpoint_does_not_resurrect_missing_db_session(client, monkeypatch):
    from api_service.main import telemetry_buffer, _telemetry_buffer_lock

    class EmptyDetections:
        def find_one(self, _query, _projection):
            return None

    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {"detection_results": EmptyDetections()},
    )
    with _telemetry_buffer_lock:
        telemetry_buffer.append({"sessionId": "deleted-raw", "mouse": {"records": []}})
    try:
        response = client.get(
            "/api/v1/telemetry/raw/deleted-raw",
            headers=READ_HEADERS,
        )
        assert response.status_code == 404
    finally:
        with _telemetry_buffer_lock:
            retained = [event for event in telemetry_buffer if event.get("sessionId") != "deleted-raw"]
            telemetry_buffer.clear()
            telemetry_buffer.extend(retained)


def test_raw_and_detail_endpoints_report_database_query_failure(client, monkeypatch):
    class FailingDetections:
        def find_one(self, *_args, **_kwargs):
            raise RuntimeError("query interrupted")

    monkeypatch.setattr(
        "api_service.database.get_db",
        lambda: {"detection_results": FailingDetections()},
    )

    raw = client.get("/api/v1/telemetry/raw/session", headers=READ_HEADERS)
    detail = client.get("/api/v1/sessions/session/detail", headers=READ_HEADERS)

    assert raw.status_code == 503
    assert detail.status_code == 503


def test_telemetry_and_detect_respect_origin_allowlist(client, monkeypatch):
    from api_service import main
    monkeypatch.setattr(main.settings, "TELEMETRY_ALLOWED_ORIGINS", ["https://shop.example"])
    body = {"sessionId": "origin-check", "visitorId": "v", "mouse": {"records": []}}
    foreign = client.post("/api/v1/telemetry", json=body, headers={"Origin": "http://chat.other.dev"})
    assert foreign.status_code == 403
    assert client.post("/api/v1/detect", json=body, headers={"Origin": "http://chat.other.dev"}).status_code == 403
    assert client.post("/api/v1/detect", json=body, headers={"Origin": "https://shop.example"}).status_code == 200
    # Requests without an Origin header (server-side callers) are not blocked by this check.
    assert client.post("/api/v1/detect", json=body).status_code == 200


def test_minimal_detect_response_hides_evidence_from_anonymous_callers(client, monkeypatch):
    from api_service import main
    monkeypatch.setattr(main.settings, "DETECT_RESPONSE", "minimal")
    body = {"sessionId": "oracle", "visitorId": "v", "botd": {"detectors": {"webdriver": True}}, "mouse": {"records": []}}
    anonymous = client.post("/api/v1/detect", json=body).json()
    # Policy 24: not even the verdict, so a bot cannot tune itself against the endpoint.
    assert set(anonymous) == {"decision_state", "policy_version", "model_bundle_id", "sessionId", "visitorId"}
    authorised = client.post("/api/v1/detect", json=body, headers=READ_HEADERS).json()
    assert authorised["verdict"] == "BOT"
    assert "breakdown" in authorised and "bot_probability" in authorised


def test_traffic_timeline_passes_the_viewer_utc_offset(client, monkeypatch):
    seen = {}

    def fake_timeline(window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None):
        seen.update(window=window_minutes, bucket=bucket_minutes, offset=utc_offset_minutes)
        return {"window_minutes": window_minutes, "bucket_minutes": bucket_minutes, "buckets": []}

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)
    response = client.get("/api/v1/traffic/timeline?window_minutes=43200&utc_offset_minutes=420", headers=READ_HEADERS)
    assert response.status_code == 200
    assert seen == {"window": 43200, "bucket": 1440, "offset": 420}


def test_detect_nulls_risk_score_for_rule_verdicts(client):
    # Policy 25: a rule verdict carries no meaningful fused score (a real iPhone was HUMAN
    # with 0.9989); risk_score is null then, bot_probability stays for old clients.
    headless = "Mozilla/5.0 HeadlessChrome/154.0.0.0"
    response = client.post(
        "/api/v1/detect",
        json={"sessionId": "sess_rule_detect", "visitorId": "visitor_rule",
              "fingerprint": {"userAgent": headless}, "botd": {"detectors": {"chromeDriverGlobal": True}},
              "mouse": {"records": []}},
        headers={"User-Agent": headless, **READ_HEADERS},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "BOT" and body["risk_score"] is None
    assert isinstance(body["bot_probability"], float)
