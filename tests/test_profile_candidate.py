from copy import deepcopy

import pytest

from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector


class LowModels:
    def predict_session_scores(self, _chunks):
        return 0.02, 0.03

    def predict_proba(self, _features):
        return 0.02


def detector():
    return EnsembleBotDetector(lstm_model=LowModels(), tabular_model=LowModels())


def payload(moves=30):
    realm = {
        "userAgent": "Mozilla/5.0 Chrome/153.0.0.0", "webdriver": False,
        "clientHints": {"brands": [{"brand": "HeadlessChrome", "version": "153"}]},
    }
    return {
        "botd": {"profile": {"schema": "browser-profile-v1", "main": realm,
                              "worker": deepcopy(realm), "workerStatus": "ok"}},
        "mouse": {"records": [{"x": i / 100, "y": 0.2, "time": i * 16,
                               "type": "move"} for i in range(moves)]},
    }


@pytest.mark.parametrize("moves", [0, 30])
def test_candidate_runs_in_main_predict_without_mouse_dependency(moves):
    data = payload(moves)
    original = deepcopy(data)
    model = detector()
    baseline = model.predict(data)
    candidate = model.predict(data, profile_candidate=True)
    assert baseline["verdict"] == ("HUMAN" if moves else "SUSPECT")
    assert candidate["verdict"] == "BOT"
    assert candidate["decision_state"] == "FINAL"
    assert candidate["policy_version"] != DECISION_POLICY_VERSION
    assert candidate["breakdown"]["automation_rule"] == "profile_corroborated_v1"
    assert candidate["breakdown"]["risk_score_in_domain"] is False
    assert candidate["breakdown"]["behavioral_lstm_score"] is None
    assert candidate["breakdown"]["profile_candidate"]["release_approved"] is False
    assert model.predict(data) == baseline
    assert data == original


@pytest.mark.parametrize("status", ["timeout", "error", "cancelled", "unsupported", None])
def test_unavailable_worker_cannot_corroborate(status):
    data = payload()
    data["botd"]["profile"]["workerStatus"] = status
    assert detector().predict(data, profile_candidate=True)["verdict"] == "HUMAN"


def test_duplicate_ua_and_brand_observations_in_one_realm_are_not_two_sources():
    data = payload()
    data["botd"]["profile"]["worker"] = {}
    main = data["botd"]["profile"]["main"]
    main["userAgent"] = "HeadlessChrome/153"
    main["clientHints"]["fullVersionList"] = main["clientHints"]["brands"]
    assert detector().predict(data, profile_candidate=True)["verdict"] == "HUMAN"


def test_explicit_webdriver_can_corroborate_one_headless_realm():
    data = payload(0)
    data["botd"]["profile"]["worker"] = {}
    data["botd"]["profile"]["main"]["webdriver"] = True
    assert detector().predict(data, profile_candidate=True)["verdict"] == "BOT"


@pytest.mark.parametrize("bad", ["true", 1, [], {}, None])
def test_candidate_requires_boolean_automation_evidence(bad):
    data = payload(0)
    data["botd"]["profile"]["worker"] = {}
    data["botd"]["profile"]["main"]["webdriver"] = bad
    data["botd"]["detectors"] = {"webdriver": bad, "distinctiveProperties": bad}
    assert detector().predict(data, profile_candidate=True)["verdict"] == "SUSPECT"


def test_os_inconsistency_and_high_heuristic_are_not_hard_evidence():
    data = payload()
    for realm in ("main", "worker"):
        data["botd"]["profile"][realm]["clientHints"] = {"platform": "Linux"}
        data["botd"]["profile"][realm]["userAgent"] = "Windows Chrome/153"
    data["botd"]["heuristicScore"] = 0.99
    assert detector().predict(data, profile_candidate=True)["verdict"] != "BOT"


def test_unknown_schema_and_client_policy_switch_cannot_enable_candidate():
    data = payload()
    data["profile_candidate"] = True
    assert detector().predict(data)["verdict"] == "HUMAN"
    data["botd"]["profile"]["schema"] = "future"
    assert detector().predict(data, profile_candidate=True)["verdict"] == "HUMAN"


def test_profile_rule_is_independent_of_broken_models():
    class Broken:
        def predict_session_scores(self, _):
            raise AssertionError("Mouse model must not run")

        def predict_proba(self, _):
            raise AssertionError("Tabular model must not run")

    model = EnsembleBotDetector(lstm_model=Broken(), tabular_model=Broken())
    assert model.predict(payload(), profile_candidate=True)["verdict"] == "BOT"


def test_candidate_preserves_existing_rule_and_has_distinct_policy_identity():
    data = payload(0)
    data.update({"_server_user_agent": "HeadlessChrome/153",
                 "fingerprint": {"userAgent": "HeadlessChrome/153"}})
    data["botd"]["detectors"] = {"webdriver": True}
    candidate = detector().predict(data, profile_candidate=True)
    assert candidate["verdict"] == "BOT"
    assert candidate["breakdown"]["automation_rule"] == "headless_ua_and_framework_v1"
    assert candidate["policy_version"] != DECISION_POLICY_VERSION


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_candidate_mode_must_be_an_explicit_boolean(value):
    with pytest.raises(ValueError, match="boolean"):
        detector().predict(payload(), profile_candidate=value)
