"""
Integration tests for FastAPI inference & telemetry service.
"""

import pytest
from fastapi.testclient import TestClient
from api_service.main import app


@pytest.fixture
def client():
    from api_service.main import _rate_limit_records
    _rate_limit_records.clear()
    return TestClient(app)


def test_index_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "models" in data
    assert "graph_node_counts" in data


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert "models_loaded" in data
    assert "database" in data


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
    assert data["latency_ms"] < 200  # Latency well within real-time SLO
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
    raw_json = '{"sessionId": "sess_beacon_text_plain", "action": "leave", "mouse": {"records": []}}'
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
    res = client.get("/api/v1/graph/stats")
    assert res.status_code == 200
    data = res.json()
    assert "device_count" in data
    assert "ip_count" in data
    assert "session_count" in data


def test_reverse_proxy_ip_forwarding(client, monkeypatch):
    monkeypatch.setattr("api_service.main._is_trusted_proxy", lambda _host: True)
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


def test_untrusted_client_cannot_spoof_forwarded_ip(client):
    res = client.post(
        "/api/v1/detect",
        json={"sessionId": "sess_untrusted_proxy"},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert res.status_code == 200
    assert res.json()["client_ip"] != "198.51.100.99"


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


def test_get_bot_collector_sdk(client):
    res = client.get("/bot-collector.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    assert "BotCollector" in res.text


def test_invalid_telemetry_is_rejected(client):
    res = client.post("/api/v1/telemetry", content=b"not-json", headers={"Content-Type": "text/plain"})
    assert res.status_code == 400


def test_oversized_payload_is_rejected(client):
    from api_service.config import settings
    body = b"x" * (settings.MAX_PAYLOAD_BYTES + 1)
    res = client.post("/api/v1/telemetry", content=body, headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_delete_requires_admin_token(client, monkeypatch):
    from api_service.config import settings
    original_token = settings.ADMIN_TOKEN
    settings.ADMIN_TOKEN = "test-secret"
    monkeypatch.setattr("api_service.database.delete_all_sessions", lambda: 3)
    try:
        assert client.delete("/api/v1/sessions").status_code == 401
        res = client.delete("/api/v1/sessions", headers={"X-Admin-Token": "test-secret"})
        assert res.status_code == 200
        assert res.json()["count"] == 3
    finally:
        settings.ADMIN_TOKEN = original_token


def test_graph_topology_has_no_dangling_edges(client):
    res = client.get("/api/v1/graph/topology?max_nodes=1")
    assert res.status_code == 200
    data = res.json()
    node_ids = {node["id"] for node in data["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in data["edges"])
