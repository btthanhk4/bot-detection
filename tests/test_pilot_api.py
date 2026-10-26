import json

import pytest
from fastapi.testclient import TestClient

from api_service import main, database
from api_service.spool import TelemetrySpool


@pytest.fixture
def pilot_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", True)
    monkeypatch.setattr(main, "lstm_loaded", False)
    monkeypatch.setattr(main, "_spool", TelemetrySpool(tmp_path / "pilot.sqlite", 100))
    main._rate_limit_records.clear()
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()
    yield TestClient(main.app)
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()


def metadata():
    return {"schemaVersion": 1, "sdkVersion": "1.1.0", "pageInstanceId": "page_01",
            "studyId": "study_01", "siteId": "site_01"}


def test_pilot_metadata_and_coordinate_frame_survive_validation_and_raw_capture(pilot_client, monkeypatch):
    saved = []
    monkeypatch.setattr(database, "save_telemetry_capture",
                        lambda capture, analysis=None: saved.append(capture) or capture["event_id"])
    payload = {"sessionId": "session", "visitorId": "visitor", "timestamp": 1, "sequence": 0,
               "collector": metadata(), "mouse": {"records": [], "scrollEvents": [],
                   "coordinateFrame": {"id": 1, "width": 1440, "height": 900}}}
    result = pilot_client.post("/api/v1/telemetry", json=payload)
    assert result.status_code == 202
    assert result.json()["capture_id"] == saved[0]["event_id"]
    assert saved[0]["study_id"] == "study_01"
    assert saved[0]["site_id"] == "site_01"
    assert saved[0]["page_instance_id"] == "page_01"
    assert json.loads(saved[0]["payload_json"])["collector"] == metadata()
    assert json.loads(saved[0]["payload_json"])["mouse"] == payload["mouse"]
    assert "verdict" not in result.json(), 'inference failure must not manufacture a label'


@pytest.mark.parametrize("overrides", [{"schemaVersion": 2}, {"studyId": "../wrong"},
                                      {"siteId": ""}, {"pageInstanceId": ""}, {"sdkVersion": "x" * 33}])
def test_malformed_pilot_metadata_is_rejected_before_storage(pilot_client, monkeypatch, overrides):
    monkeypatch.setattr(database, "save_telemetry_capture", lambda *args: pytest.fail("Must not save invalid metadata"))
    result = pilot_client.post("/api/v1/telemetry", json={
        "sessionId": "s", "visitorId": "v", "collector": {**metadata(), **overrides},
    })
    assert result.status_code == 422


def test_served_sdk_contains_opt_in_bootstrap_and_version(pilot_client):
    response = pilot_client.get("/bot-collector.js")
    assert response.status_code == 200
    assert "bootstrapPilot" in response.text
    assert "COLLECTOR_VERSION = '1.6.0'" in response.text
    assert response.headers["cache-control"] == "public, no-cache"


def test_health_reports_whether_research_capture_is_enabled(pilot_client, monkeypatch):
    monkeypatch.setattr(main, "_health_cache", {"checked_at": 0.0, "database": False, "inference_ready": False})
    monkeypatch.setattr(database, "is_database_ready", lambda: False)
    response = pilot_client.get("/health")
    assert response.json()["research_capture"] == {
        "enabled": True, "retention_days": main.settings.CAPTURE_RETENTION_DAYS,
    }


def test_cors_allows_cross_origin_json_preflight_and_exposes_retry_header(pilot_client):
    response = pilot_client.options("/api/v1/telemetry", headers={
        "Origin": "https://instrumented.example.org",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in ("*", "https://instrumented.example.org")
