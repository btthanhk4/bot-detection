"""
Integration tests for FastAPI inference & telemetry service.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from api_service.main import app


@pytest.fixture
def client():
    from api_service.main import _rate_limit_records
    from api_service.config import settings
    _rate_limit_records.clear()
    original_read_token = settings.READ_TOKEN
    settings.READ_TOKEN = "test-read-token"
    try:
        yield TestClient(app)
    finally:
        settings.READ_TOKEN = original_read_token


READ_HEADERS = {"X-Read-Token": "test-read-token"}


def test_index_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "models" in data
    assert "graph_node_counts" in data


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code in (200, 503)
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert "models_loaded" in data
    assert "database" in data
    assert "inference_ready" in data


def test_health_detects_runtime_inference_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)

    def fail_probe(_payload):
        raise RuntimeError("broken model runtime")

    monkeypatch.setattr("api_service.main.ensemble_detector.predict", fail_probe)
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["inference_ready"] is False


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
    assert 0 <= data["latency_ms"] < 2000
    assert data["sessionId"] == "sess_test_human"


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


def test_graph_stats(client):
    res = client.get("/api/v1/graph/stats", headers=READ_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "device_count" in data
    assert "ip_count" in data
    assert "session_count" in data


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
    assert "Không đủ dữ liệu quỹ đạo chuột thô" in res.text
    assert "sessionSelectionVersion" in res.text
    assert "models.tabular && models.lstm" in res.text
    assert "Fallback: generate representative trajectory" not in res.text
    assert "const controller = new AbortController()" in res.text
    assert "let activePoll = null" in res.text
    assert "sessionStorage.removeItem('bot_read_token');" in res.text
    assert "http://159.223.91.163/san-pham" not in res.text


def test_recent_telemetry_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_recent_results", lambda limit: None)
    monkeypatch.setattr("api_service.database.get_total_count", lambda: 1)

    response = client.get("/api/v1/telemetry/recent", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_summary_reports_database_query_failure(client, monkeypatch):
    monkeypatch.setattr("api_service.database.get_db", lambda: object())
    monkeypatch.setattr("api_service.database.get_summary_stats", lambda: None)

    response = client.get("/api/v1/stats/summary", headers=READ_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database query failed"


def test_invalid_telemetry_is_rejected(client):
    res = client.post("/api/v1/telemetry", content=b"not-json", headers={"Content-Type": "text/plain"})
    assert res.status_code == 400


def test_telemetry_requires_visitor_id(client):
    res = client.post("/api/v1/telemetry", json={"sessionId": "session-without-visitor"})
    assert res.status_code == 422


def test_monitoring_endpoints_require_read_token(client):
    assert client.get("/api/v1/graph/stats").status_code == 401
    assert client.get("/api/v1/telemetry/recent").status_code == 401


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
    graphed = []
    monkeypatch.setattr("api_service.main.ensemble_detector.predict", lambda _data: {"verdict": "HUMAN"})
    monkeypatch.setattr(
        "api_service.database.save_detection_result",
        lambda data, _analysis: persisted.append(data["sessionId"]) or data["sessionId"],
    )
    monkeypatch.setattr("api_service.database.is_database_ready", lambda: True)
    monkeypatch.setattr(
        "api_service.main.graph_builder.add_telemetry_event",
        lambda data, ip_address: graphed.append((data["sessionId"], ip_address)),
    )

    _flush_telemetry_buffer()

    assert persisted == ["replay-session"]
    assert graphed == [("replay-session", "192.0.2.1")]
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


def test_delete_requires_admin_token(client, monkeypatch):
    from api_service.main import graph_builder, telemetry_buffer, _telemetry_buffer_lock
    from api_service.config import settings
    original_token = settings.ADMIN_TOKEN
    settings.ADMIN_TOKEN = "test-secret"
    monkeypatch.setattr("api_service.database.delete_all_sessions", lambda: 3)
    graph_builder.add_telemetry_event({"sessionId": "delete-all-memory", "visitorId": "device"})
    with _telemetry_buffer_lock:
        telemetry_buffer.append({"sessionId": "delete-all-memory"})
    try:
        assert client.delete("/api/v1/sessions").status_code == 401
        res = client.delete("/api/v1/sessions", headers={"X-Admin-Token": "test-secret"})
        assert res.status_code == 200
        assert res.json()["count"] == 3
        assert graph_builder.get_stats()["session_count"] == 0
        with _telemetry_buffer_lock:
            assert len(telemetry_buffer) == 0
    finally:
        settings.ADMIN_TOKEN = original_token


def test_delete_session_purges_in_memory_data(client, monkeypatch):
    from api_service.config import settings
    from api_service.main import graph_builder, telemetry_buffer, _telemetry_buffer_lock

    original_token = settings.ADMIN_TOKEN
    settings.ADMIN_TOKEN = "test-secret"
    monkeypatch.setattr("api_service.database.delete_session", lambda _session_id: False)
    graph_builder.add_telemetry_event({"sessionId": "memory-only", "visitorId": "device"})
    with _telemetry_buffer_lock:
        telemetry_buffer.append({"sessionId": "memory-only"})
    try:
        response = client.delete(
            "/api/v1/sessions/memory-only",
            headers={"X-Admin-Token": "test-secret"},
        )
        assert response.status_code == 200
        assert "memory-only" not in graph_builder.session_map
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


def test_graph_topology_has_no_dangling_edges(client):
    res = client.get("/api/v1/graph/topology?max_nodes=1", headers=READ_HEADERS)
    assert res.status_code == 200
    data = res.json()
    node_ids = {node["id"] for node in data["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in data["edges"])
