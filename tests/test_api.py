"""
Integration tests for FastAPI inference & telemetry service.
"""

import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from api_service.main import app


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
    observed = {}

    def inspect_probe(payload):
        observed["move_count"] = len(payload["mouse"]["records"])
        return {"bot_probability": 0.5}

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", inspect_probe)
    response = client.get("/health")

    assert response.status_code == 200
    assert observed["move_count"] >= 25


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
    assert calls == {"database": 1, "inference": 1}


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


def test_detect_bot_flagged(client):
    payload = {
        "sessionId": "sess_test_bot",
        "visitorId": "dev_test_bot",
        "botd": {
            "heuristicScore": 0.95,
            "detectors": {"webdriver": True, "distinctiveProperties": True},
            "reasons": ["navigator.webdriver is true"],
        },
    }
    res = client.post("/api/v1/detect", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_bot"] is True
    assert data["bot_probability"] >= 0.75
    assert data["verdict"] == "BOT"


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


def test_dashboard_uses_only_real_mouse_trajectory(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "<title>DATACAT</title>" in res.text
    assert "/api/v1/traffic/timeline" in res.text
    assert 'id="timelineRange"' in res.text
    assert '<option value="1440">24 giờ</option>' in res.text
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
    assert "sessionStorage.removeItem('bot_read_token');" in res.text
    assert "http://159.223.91.163/san-pham" not in res.text
    assert "data.sessions.map(sessionRevision)" in res.text
    assert "refreshSelectedTrajectory(selectedSession)" in res.text
    assert "Models Online / Database Degraded" in res.text
    assert "const POLL_INTERVAL = 5000" in res.text
    assert "function parseScreenResolution(value)" in res.text
    assert "for (let i = 0; i < 40; i++)" in res.text
    assert "await Promise.all([fetchClassificationSummary(), fetchTrafficTimeline()])" in res.text


def test_recent_telemetry_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_recent_results", lambda limit: None)
    monkeypatch.setattr("api_service.database.get_total_count", lambda: 1)

    response = client.get("/api/v1/telemetry/recent", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_recent_telemetry_reports_database_total_with_compatibility_alias(
    client, monkeypatch
):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr(
        "api_service.database.get_recent_results",
        lambda limit: [{"sessionId": "session-1"}],
    )
    monkeypatch.setattr("api_service.database.get_total_count", lambda: 7)

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

    def fake_timeline(window_minutes, bucket_minutes):
        query_args.update(window_minutes=window_minutes, bucket_minutes=bucket_minutes)
        return timeline

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)

    response = client.get("/api/v1/traffic/timeline", headers=READ_HEADERS)

    assert response.status_code == 200
    assert response.json() == timeline
    assert query_args == {"window_minutes": 60, "bucket_minutes": 1}


@pytest.mark.parametrize(
    ("window_minutes", "expected_bucket_minutes"),
    [(30, 1), (120, 2), (240, 5), (360, 5), (720, 10), (1440, 15)],
)
def test_traffic_timeline_uses_adaptive_buckets(
    client,
    monkeypatch,
    window_minutes,
    expected_bucket_minutes,
):
    query_args = {}

    def fake_timeline(window_minutes, bucket_minutes):
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
        "/api/v1/traffic/timeline?window_minutes=1441", headers=READ_HEADERS
    ).status_code == 422


def test_traffic_timeline_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr(
        "api_service.database.get_traffic_timeline",
        lambda window_minutes, bucket_minutes: None,
    )

    response = client.get("/api/v1/traffic/timeline", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Traffic timeline query failed"


def test_summary_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_summary_stats", lambda: None)

    response = client.get("/api/v1/stats/summary", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_invalid_telemetry_is_rejected(client):
    res = client.post("/api/v1/telemetry", content=b"not-json", headers={"Content-Type": "text/plain"})
    assert res.status_code == 400


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


def test_full_telemetry_buffer_reports_oldest_event_drop():
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

    assert _buffer_telemetry({"sessionId": "newest"}) is True

    with _telemetry_buffer_lock:
        assert len(telemetry_buffer) == telemetry_buffer.maxlen
        assert telemetry_buffer[0]["sessionId"] == "old-1"
        assert telemetry_buffer[-1]["sessionId"] == "newest"
        assert _telemetry_buffer_stats["dropped_total"] == dropped_before + 1
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
