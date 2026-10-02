from copy import deepcopy

import pytest

from core_ml.dataset.field_captures import BotCapture
from core_ml.evaluate_profile_shadow import evaluate_profile_captures
from core_ml.features.profile_consistency import analyze_profile_consistency
from core_ml.models.ensemble import EnsembleBotDetector


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/153.0.0.0"


def profile_payload():
    realm = {
        "userAgent": UA, "platform": "Win32", "hardwareConcurrency": 8,
        "webdriver": None,
        "clientHints": {"platform": "Windows", "brands": [{"brand": "Chromium", "version": "153"}]},
    }
    return {"botd": {"profile": {
        "schema": "browser-profile-v1", "main": realm,
        "worker": deepcopy(realm), "workerStatus": "ok",
    }}}


@pytest.mark.parametrize("payload", [None, [], {}, {"botd": None}, {"botd": {"profile": []}},
                                    {"botd": {"profile": {"schema": "future"}}}])
def test_missing_or_unrecognized_profile_is_unknown(payload):
    report = analyze_profile_consistency(payload)
    assert report["shadow_verdict"] is None
    assert report["available_checks"] == 0
    assert report["release_approved"] is False


def test_regular_profile_has_no_bot_suggestion():
    assert analyze_profile_consistency(profile_payload())["signals"] == []


@pytest.mark.parametrize("field", ["brands", "fullVersionList"])
def test_headless_client_hint_is_reported_independently_of_ua(field):
    payload = profile_payload()
    payload["botd"]["profile"]["main"]["clientHints"][field] = [
        {"brand": "HeadlessChrome", "version": "153"},
    ]
    report = analyze_profile_consistency(payload)
    assert report["shadow_verdict"] == "BOT"
    assert {signal["code"] for signal in report["signals"]} == {"PAGE_HEADLESS_CLIENT_HINTS"}


def test_privacy_cpu_language_and_version_differences_are_not_bot_evidence():
    payload = profile_payload()
    payload["botd"]["profile"]["main"].update({
        "hardwareConcurrency": 2, "language": "en-US", "userAgent": UA.replace("153", "128"),
    })
    payload["botd"]["profile"]["worker"].update({"hardwareConcurrency": 10, "language": "vi-VN"})
    assert analyze_profile_consistency(payload)["signals"] == []


@pytest.mark.parametrize("status", ["timeout", "unsupported", "error", "cancelled"])
def test_worker_failure_cannot_be_used_as_bot_evidence(status):
    payload = profile_payload()
    payload["botd"]["profile"].update({"workerStatus": status, "worker": {"webdriver": True}})
    report = analyze_profile_consistency(payload)
    assert report["signals"] == []
    assert not next(check["available"] for check in report["checks"] if check["code"] == "WORKER_WEBDRIVER")


def test_os_mismatch_is_only_a_soft_suggestion():
    payload = profile_payload()
    payload["botd"]["profile"]["main"]["clientHints"]["platform"] = "Linux"
    report = analyze_profile_consistency(payload)
    assert report["shadow_verdict"] == "SUSPECT"
    assert report["signals"] == [{"code": "PAGE_UA_HINTS_OS_MISMATCH", "strength": "inconsistency"}]


def test_android_linux_ua_and_android_hints_are_consistent():
    payload = profile_payload()
    for realm in ("main", "worker"):
        payload["botd"]["profile"][realm].update({
            "userAgent": "Mozilla/5.0 (Linux; Android 15) Chrome/153 Mobile",
            "clientHints": {"platform": "Android"},
        })
    assert analyze_profile_consistency(payload)["signals"] == []


def test_invalid_brands_and_non_boolean_webdriver_are_ignored():
    payload = profile_payload()
    payload["botd"]["profile"]["main"]["clientHints"] = {"brands": "HeadlessChrome"}
    payload["botd"]["profile"]["worker"].update({"webdriver": "true", "clientHints": {"brands": [None, 1]}})
    assert analyze_profile_consistency(payload)["signals"] == []


@pytest.mark.parametrize("move_count", [0, 25])
def test_shadow_evidence_does_not_change_production_decision_or_weights(move_count):
    class LowLstm:
        def predict_session_scores(self, _chunks):
            return 0.02, 0.03

    class LowTabular:
        def predict_proba(self, _features):
            return 0.02

    detector = EnsembleBotDetector(lstm_model=LowLstm(), tabular_model=LowTabular())
    mouse = {"records": [{"time": i * 16, "x": i / 100, "y": 0.2, "type": "move"}
                         for i in range(move_count)]}
    baseline = detector.predict({"mouse": mouse})
    payload = profile_payload()
    payload["mouse"] = mouse
    payload["botd"]["profile"]["main"]["clientHints"]["brands"][0]["brand"] = "HeadlessChrome"
    result = detector.predict(payload)
    assert result["verdict"] == baseline["verdict"]
    assert result["bot_probability"] == baseline["bot_probability"]
    assert result["breakdown"]["weights_used"] == baseline["breakdown"]["weights_used"]
    assert result["breakdown"]["profile_shadow"]["shadow_verdict"] == "BOT"
    assert result["verdict"] == ("HUMAN" if move_count else "SUSPECT")


def test_evaluator_counts_runs_not_snapshots_and_excludes_final_probe():
    payload = profile_payload()
    payload["sessionId"] = "s1"
    payload["botd"]["profile"]["main"]["clientHints"]["brands"][0]["brand"] = "HeadlessChrome"

    class HumanModel:
        def predict(self, _payload):
            return {"verdict": "HUMAN"}

    capture = BotCapture("capture1", "stealth", (payload, payload, {"sessionId": "s1"}))
    report = evaluate_profile_captures(HumanModel(), [capture])
    group = report["groups"][0]
    assert report["runs"] == 1
    assert group["shadow_final"] == {"BOT": 1}
    assert group["final_signals"] == {"PAGE_HEADLESS_CLIENT_HINTS": 1}
    assert report["human_participants"] == 0
    assert report["release_approved"] is False


def test_evaluator_never_downgrades_existing_bot_and_reports_human_false_positive():
    payload = profile_payload()
    payload["sessionId"] = "s2"
    payload["botd"]["profile"]["main"]["clientHints"]["platform"] = "Linux"

    class BotModel:
        def predict(self, _payload):
            return {"verdict": "BOT"}

    capture = BotCapture("capture2", "privacy", (payload, {}), label="HUMAN", participant_id="participant1")
    report = evaluate_profile_captures(BotModel(), [capture])
    assert report["groups"][0]["shadow_final"] == {"BOT": 1}
    assert report["human_runs"] == report["human_participants"] == 1
