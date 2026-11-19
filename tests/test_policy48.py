"""Policy 48: three verdicts for the product. The detector's insufficient result becomes SUSPECT with an
anomaly and HUMAN without one; results the evidence decided stay as they are."""

import copy

import mongomock
import pytest
from fastapi.testclient import TestClient

from core_ml.release_cases import THREE_VERDICT_CASES, THREE_VERDICT_GATE
from core_ml.three_verdicts import (
    DESKTOP_IDLE_MS,
    INPUT_ANOMALY_BASIS,
    NO_BOT_EVIDENCE_BASIS,
    apply_three_verdicts,
    input_anomalies,
)


def insufficient(phone=True, **breakdown):
    return {"verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE", "is_bot": False,
            "reasons": ["Decision deferred: mobile or tablet input is outside the trained mouse domain"],
            "breakdown": {"decision_basis": "insufficient_evidence", "decision_deferred": True,
                          "suspect_reason_codes": ["UNSUPPORTED_INPUT", "NO_INTERACTION_CLEAN"],
                          "mobile_human": {"device": "android" if phone else None, "missing": ["FEW_GESTURES"]},
                          "unsupported_mobile": phone,
                          "presence": {"codes": [], "research_flags": [], "visible_ms": 8000},
                          "automation_evidence": {"families": {}}, "mouse_points": 0, **breakdown}}


def test_a_phone_without_bot_evidence_is_human():
    out = apply_three_verdicts(insufficient())
    b = out["breakdown"]
    assert (out["verdict"], out["decision_state"], out["is_bot"]) == ("HUMAN", "FINAL", False)
    assert b["decision_basis"] == NO_BOT_EVIDENCE_BASIS and b["decision_deferred"] is False
    assert b["suspect_reason_codes"] == [] and b["verdict_locked"] is False
    assert b["three_verdicts"] == {"version": "three_verdicts_v1", "from_state": "INSUFFICIENT_EVIDENCE",
                                   "from_basis": "insufficient_evidence",
                                   "from_codes": ["UNSUPPORTED_INPUT", "NO_INTERACTION_CLEAN"], "anomalies": []}
    assert out["reasons"][1:] == insufficient()["reasons"]
    # A phone page never shown (in-app browsers preload ad pages) is no anomaly.
    never_shown = insufficient(presence={"codes": ["NOT_VIEWED"], "research_flags": [], "visible_ms": 0})
    assert apply_three_verdicts(never_shown)["verdict"] == "HUMAN"


def test_phone_anomalies():
    no_token = insufficient(mobile_human={"device": "android", "missing": ["FEW_GESTURES", "UNVERIFIED_PAGE_LOAD"]})
    out = apply_three_verdicts(no_token)
    assert (out["verdict"], out["decision_state"], out["breakdown"]["decision_basis"]) == (
        "SUSPECT", "FINAL", INPUT_ANOMALY_BASIS)
    assert out["breakdown"]["suspect_reason_codes"] == ["UNVERIFIED_PAGE_LOAD"]
    # A short visit often ends before the token arrives; a token that does not check out counts at once.
    short = copy.deepcopy(no_token)
    short["breakdown"]["presence"]["visible_ms"] = 3000
    assert apply_three_verdicts(short)["verdict"] == "HUMAN"
    bad = apply_three_verdicts(short, {"_server_headers": {"page_view": "reused"}})
    assert bad["breakdown"]["three_verdicts"]["anomalies"] == ["UNVERIFIED_PAGE_LOAD"]
    sensorless = insufficient(presence={"codes": [], "research_flags": ["SENSORS_UNAVAILABLE"], "visible_ms": 40000})
    assert apply_three_verdicts(sensorless)["breakdown"]["three_verdicts"]["anomalies"] == ["SENSORS_UNAVAILABLE"]
    # A family a phone browser shows on its own (policy 18 tolerates one) is no anomaly.
    family = insufficient(automation_evidence={"families": {"CLIENT_HINTS": ["clientHints.empty"]}})
    assert apply_three_verdicts(family)["verdict"] == "HUMAN"


def test_desktop_anomalies():
    idle = insufficient(phone=False, presence={"codes": [], "research_flags": [], "visible_ms": DESKTOP_IDLE_MS})
    assert input_anomalies(idle["breakdown"]) == ["DESKTOP_IDLE"]
    assert input_anomalies({**idle["breakdown"], "presence": {"visible_ms": DESKTOP_IDLE_MS - 1}}) == []
    assert input_anomalies({**idle["breakdown"], "mouse_points": 10}) == []
    # Without page presence (collector before 1.16) the page age stands in.
    old = {**idle["breakdown"], "presence": {}}
    assert input_anomalies(old, {"mouse": {"pageAgeMs": 30000}}) == ["DESKTOP_IDLE"]
    # Neither page presence nor page age: nothing says a page was ever shown (a bare telemetry post); a session
    # read back from storage may just come from an older collector.
    assert input_anomalies(old) == ["NO_PAGE_PRESENCE"]
    assert input_anomalies(old, stored=True) == []
    assert input_anomalies({**idle["breakdown"], "presence": {"codes": ["NOT_VIEWED"], "visible_ms": 0}}) == ["NOT_VIEWED"]
    assert input_anomalies({**idle["breakdown"], "presence": {"visible_ms": 2000}, "automation_evidence": {
        "families": {"NATIVE_PATCH": ["signals.navigatorGetterPatched"]}}}) == ["ENVIRONMENT_FAMILY"]
    no_token = {**idle["breakdown"], "presence": {"visible_ms": 6000},
                "mobile_human": {"device": None, "missing": ["NOT_MOBILE", "UNVERIFIED_PAGE_LOAD"]}}
    assert input_anomalies(no_token) == ["UNVERIFIED_PAGE_LOAD"]
    assert input_anomalies({**no_token, "presence": {"visible_ms": 4000}}) == []
    short = insufficient(phone=False, presence={"codes": [], "research_flags": [], "visible_ms": 2000})
    assert apply_three_verdicts(short)["verdict"] == "HUMAN"


def test_what_the_detector_raised_is_an_anomaly_on_any_device():
    for phone in (True, False):
        flagged = insufficient(phone=phone, suspect_reason_codes=["INSUFFICIENT_MOUSE", "HIGH_CLIENT_HEURISTIC_SCORE",
                                                                 "CLIENT_AUTOMATION_SIGNAL"],
                               presence={"codes": [], "research_flags": [], "visible_ms": 2000})
        out = apply_three_verdicts(flagged)
        assert out["verdict"] == "SUSPECT"
        assert out["breakdown"]["three_verdicts"]["anomalies"] == ["CLIENT_AUTOMATION_SIGNAL", "HIGH_CLIENT_HEURISTIC_SCORE"]
        assert out["breakdown"]["three_verdicts"]["from_codes"][0] == "INSUFFICIENT_MOUSE"
    degenerate = insufficient(phone=False, suspect_reason_codes=["DEGENERATE_TRAJECTORY"], mouse_points=40,
                              presence={"codes": [], "research_flags": [], "visible_ms": 2000})
    assert apply_three_verdicts(degenerate)["breakdown"]["suspect_reason_codes"] == ["DEGENERATE_TRAJECTORY"]


def test_profile_automation_and_a_bare_post_are_anomalies():
    shadow = insufficient(profile_shadow={"shadow_verdict": "BOT", "signals": [{"code": "PAGE_HEADLESS_CLIENT_HINTS"}]})
    assert apply_three_verdicts(shadow)["breakdown"]["three_verdicts"]["anomalies"] == ["PROFILE_AUTOMATION"]
    mismatch = insufficient(profile_shadow={"shadow_verdict": "SUSPECT"})
    assert apply_three_verdicts(mismatch)["verdict"] == "HUMAN", "an OS mismatch a privacy tool can cause"
    bare = insufficient(phone=False, presence={},
                        mobile_human={"device": None, "missing": ["NOT_MOBILE", "UNVERIFIED_PAGE_LOAD"]})
    assert apply_three_verdicts(bare, {"mouse": {"records": []}})["breakdown"]["three_verdicts"]["anomalies"] == [
        "NO_PAGE_PRESENCE", "UNVERIFIED_PAGE_LOAD"]
    assert input_anomalies(bare["breakdown"], stored=True) == []


def test_decided_and_unavailable_results_stay():
    for result in ({"verdict": "BOT", "decision_state": "FINAL", "breakdown": {}},
                   {"verdict": "SUSPECT", "decision_state": "FINAL", "breakdown": {"decision_basis": "mobile_risk"}},
                   {"verdict": "HUMAN", "decision_state": "FINAL", "breakdown": {}}):
        assert apply_three_verdicts(result) is result
    unavailable = insufficient()
    unavailable["reasons"] = ["Decision deferred: required model unavailable"]
    assert apply_three_verdicts(unavailable) is unavailable
    assert apply_three_verdicts(None) is None


def test_release_gate():
    from api_service.main import ensemble_detector
    from core_ml.train import validate_three_verdicts

    assert validate_three_verdicts(ensemble_detector) == THREE_VERDICT_GATE
    assert (THREE_VERDICT_GATE["human_cases"], THREE_VERDICT_GATE["suspect_cases"],
            THREE_VERDICT_GATE["bot_cases"]) == (6, 6, 1)
    # The detector itself still says when it has too little evidence.
    for _, _, _, anomalies, payload in THREE_VERDICT_CASES:
        core = ensemble_detector.predict(copy.deepcopy(payload))
        assert core["decision_state"] == ("INSUFFICIENT_EVIDENCE" if anomalies is not None else "FINAL")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from api_service import main
    from api_service.spool import TelemetrySpool

    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", False)
    monkeypatch.setattr(main, "delete_research_data", lambda session_id=None: None)
    monkeypatch.setattr(main, "_spool", TelemetrySpool(tmp_path / "spool.sqlite", main.settings.MAX_BUFFER_SIZE))
    yield main
    with main._telemetry_buffer_lock:
        main.telemetry_buffer.clear()


def test_the_api_stores_three_verdicts(api, monkeypatch):
    from api_service import database

    saved = []
    monkeypatch.setattr(api, "_require_inference_models", lambda: None)
    monkeypatch.setattr(api.ensemble_detector, "predict", lambda data: insufficient())
    monkeypatch.setattr(database, "save_detection_result", lambda data, analysis: saved.append(analysis) or "s")
    response = TestClient(api.app).post("/api/v1/telemetry", json={"sessionId": "three", "visitorId": "v"})
    assert response.status_code == 200
    assert (saved[0]["verdict"], saved[0]["decision_state"]) == ("HUMAN", "FINAL")
    assert saved[0]["breakdown"]["decision_basis"] == NO_BOT_EVIDENCE_BASIS


def test_stored_insufficient_sessions_map_on_request():
    from api_service.rejudge import map_three_verdicts

    db = mongomock.MongoClient()["three"]
    desktop = insufficient(phone=False, presence={"codes": [], "research_flags": [], "visible_ms": 20000})
    db["detection_results"].insert_many([
        {"_id": "p", "sessionId": "p", "verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE",
         "policy_version": "46", "reasons": ["old"], "breakdown": insufficient()["breakdown"]},
        {"_id": "d", "sessionId": "d", "verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE",
         "policy_version": "46", "reasons": ["old"], "breakdown": desktop["breakdown"]},
        {"_id": "h", "sessionId": "h", "verdict": "HUMAN", "decision_state": "FINAL", "policy_version": "46",
         "breakdown": {}},
    ])
    counted = map_three_verdicts(db)
    assert counted["mapped"] == 2 and counted["written"] == 0
    assert counted["counts"] == {"phone HUMAN": 1, "desktop SUSPECT": 1, "anomaly DESKTOP_IDLE": 1}
    done = map_three_verdicts(db, apply=True)
    assert done["written"] == 2
    docs = {d["_id"]: d for d in db["detection_results"].find()}
    assert (docs["p"]["verdict"], docs["p"]["decision_state"], docs["p"]["breakdown"]["decision_basis"]) == (
        "HUMAN", "FINAL", NO_BOT_EVIDENCE_BASIS)
    assert docs["p"]["verdict_mapped"] is True and docs["p"]["rejudged"]["from_state"] == "INSUFFICIENT_EVIDENCE"
    assert docs["d"]["verdict"] == "SUSPECT" and docs["d"]["breakdown"]["suspect_reason_codes"] == ["DESKTOP_IDLE"]
    assert docs["h"]["verdict"] == "HUMAN" and "rejudged" not in docs["h"]
    assert map_three_verdicts(db)["mapped"] == 0


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION

    assert DECISION_POLICY_VERSION in ("48", "49", "50", "51")
