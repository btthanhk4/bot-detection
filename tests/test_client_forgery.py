"""Policies 26-27: random pointer jumps and browser claims no genuine browser makes."""

import copy

import pytest

from core_ml.features.client_forgery import (
    forged_browser_fires,
    forgery_codes,
    pointer_jump_profile,
    synthetic_path_fires,
)
from core_ml.models.ensemble import EnsembleBotDetector
from core_ml.release_cases import (
    CLIENT_FORGERY_CASES,
    CLIENT_FORGERY_RULE_GATE,
    _desktop,
    _jumps,
    _path,
    _sparse_hand,
)
from core_ml.train import validate_client_forgery_rules

SAFARI9 = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/601.1.56 (KHTML, like Gecko) "
           "Version/9.0 Safari/601.1.56")
SAFARI12_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 12_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/12.1.2 Mobile/15E148 Safari/604.1")
SAFARI17 = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.6 Safari/605.1.15")
CHROME54 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/54.0.2840.99 Safari/537.36")
CHROME155 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/155.0.0.0 Safari/537.36")
# Android WebView and Chrome on iOS carry an old-looking "Version/" token beside their engine.
WEBVIEW = ("Mozilla/5.0 (Linux; Android 13; SM-A536E Build/TP1A.220624.014; wv) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.39 Mobile Safari/537.36")
CRIOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
         "CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1")
FIREFOX_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 12_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
               "FxiOS/18.1 Mobile/15E148 Version/12.1 Safari/605.1.15")
WEBDRIVER = {"families": {"NATIVE_PATCH": ["signals.webdriverPatched"]}}


class FixedLSTM:
    def predict_session_scores(self, chunks):
        return 0.05, 0.05


class FixedTabular:
    def predict_proba(self, vector):
        return 0.02


def detector():
    return EnsembleBotDetector(lstm_model=FixedLSTM(), tabular_model=FixedTabular())


def body(ua=CHROME155, pointer_moves=600, cores=None):
    fingerprint = {"userAgent": ua, **({"hardwareConcurrency": cores} if cores is not None else {})}
    return {"fingerprint": fingerprint, "mouse": {"pointerStats": {"pointermove": pointer_moves}}}


def test_random_jumps_turn_back():
    profile = pointer_jump_profile(_jumps())
    assert profile["random_jumps"]
    assert profile["jump_share"] >= 0.40 and profile["turn_share"] >= 0.50 and profile["jump_pairs"] >= 5


def test_a_fast_hand_recorded_sparsely_keeps_its_direction():
    # Balabit-like: half the steps are long, but consecutive long steps point the same way.
    profile = pointer_jump_profile(_sparse_hand())
    assert profile["jump_share"] >= 0.40 and profile["turn_share"] < 0.50
    assert not profile["random_jumps"]


def test_a_human_path_has_no_jumps():
    assert pointer_jump_profile(_path())["jump_share"] == 0.0
    assert not pointer_jump_profile(_path())["random_jumps"]


def test_jumps_are_judged_on_10_moves_or_more():
    # Policy 27: the lander's bots move a median of 20 times.
    assert not pointer_jump_profile(_jumps(n=9))["random_jumps"]
    assert pointer_jump_profile(_jumps(n=10))["steps"] == 9
    assert pointer_jump_profile(_jumps(n=15))["random_jumps"]


def test_a_fast_hand_over_few_moves_is_not_a_jump():
    for n in (10, 12, 15, 20):
        assert not pointer_jump_profile(_sparse_hand()[:n])["random_jumps"]
        assert not pointer_jump_profile(_path()[-n:])["random_jumps"]


def test_a_zigzag_without_long_steps_is_not_a_jump():
    zigzag = [{"time": i * 16, "x": 0.5 + (0.05 if i % 2 else -0.05), "y": 0.5, "type": "move"} for i in range(40)]
    assert not pointer_jump_profile(zigzag)["random_jumps"]


@pytest.mark.parametrize("ua", [SAFARI9, SAFARI12_IOS, CHROME54])
def test_a_browser_without_pointer_events_cannot_send_them(ua):
    assert forgery_codes(body(ua), {}, desktop=True) == ["UA_POINTER_MISMATCH"]
    assert forgery_codes(body(ua, pointer_moves=0), {}, desktop=True) == []


@pytest.mark.parametrize("ua", [SAFARI17, CHROME155, WEBVIEW, CRIOS, FIREFOX_IOS])
def test_current_browsers_and_embedded_engines_are_not_mismatches(ua):
    assert forgery_codes(body(ua), {}, desktop=True) == []


@pytest.mark.parametrize("value", [True, float("nan"), "600", None])
def test_malformed_pointer_counts_are_ignored(value):
    assert forgery_codes(body(SAFARI9, pointer_moves=value), {}, desktop=True) == []


def test_webdriver_tampering_comes_from_the_native_patch_family():
    assert forgery_codes(body(), WEBDRIVER, desktop=True) == ["WEBDRIVER_TAMPERED"]
    deleted = {"families": {"NATIVE_PATCH": ["signals.webdriverDeleted"]}}
    assert forgery_codes(body(), deleted, desktop=False) == ["WEBDRIVER_TAMPERED"]
    # Another navigator getter patched (a UA-switcher extension) is not webdriver tampering.
    other = {"families": {"NATIVE_PATCH": ["signals.navigatorGetterPatched"]}}
    assert forgery_codes(body(), other, desktop=True) == []


def test_server_cpu_only_above_64_cores_on_a_desktop():
    assert forgery_codes(body(cores=640), {}, desktop=True) == ["SERVER_CPU"]
    assert forgery_codes(body(cores=65), {}, desktop=True) == ["SERVER_CPU"]
    assert forgery_codes(body(cores=64), {}, desktop=True) == []
    assert forgery_codes(body(cores=640), {}, desktop=False) == []
    assert forgery_codes(body(cores=True), {}, desktop=True) == []


def test_forgery_codes_survive_malformed_payloads():
    assert forgery_codes(None, None, desktop=True) == []
    assert forgery_codes({"fingerprint": "x", "mouse": []}, {"families": None}, desktop=True) == []


def test_the_path_rule_needs_jumps_and_an_independent_contradiction():
    jumps = pointer_jump_profile(_jumps())
    assert synthetic_path_fires(jumps, ["WEBDRIVER_TAMPERED"], {})
    assert synthetic_path_fires(jumps, [], {"families": {"CLIENT_HINTS": ["signals.uaHintsMismatch"]}})
    # A cloud address alone is not a contradiction of the browser.
    assert not synthetic_path_fires(jumps, [], {"families": {"NETWORK": ["server.datacenter"]}})
    assert not synthetic_path_fires(jumps, [], {})
    assert not synthetic_path_fires(pointer_jump_profile(_path()), ["WEBDRIVER_TAMPERED"], WEBDRIVER)


def test_random_jumps_with_webdriver_tampering_are_a_bot():
    result = detector().predict(_desktop(path=_jumps(), signals={"webdriverPatched": True}))
    assert result["verdict"] == "BOT"
    assert result["breakdown"]["automation_rule"] == "synthetic_pointer_path_v1"
    assert result["breakdown"]["decision_basis"] == "synthetic_input"
    assert "Synthetic pointer path" in " ".join(result["reasons"])


def test_random_jumps_alone_withhold_a_human_verdict():
    result = detector().predict(_desktop(path=_jumps()))
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["desktop_risk"]["codes"] == ["RANDOM_POINTER_JUMPS"]


def test_deferred_session_with_forgery_is_a_final_suspect():
    payload = _desktop(signals={"webdriverPatched": True})
    payload["mouse"]["records"] = []
    result = detector().predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["decision_basis"] == "client_forgery"
    assert result["breakdown"]["client_forgery"]["codes"] == ["WEBDRIVER_TAMPERED"]
    assert result["breakdown"]["decision_deferred"] is False
    assert "CLIENT_FORGERY" in result["breakdown"]["suspect_reason_codes"]
    assert "DESKTOP_RISK" not in result["breakdown"]["suspect_reason_codes"]


@pytest.mark.parametrize("index", range(len(CLIENT_FORGERY_CASES)))
def test_release_fixtures(index):
    verdict, state, basis, payload = CLIENT_FORGERY_CASES[index]
    result = detector().predict(copy.deepcopy(payload))
    assert (result["verdict"], result["decision_state"]) == (verdict, state)
    if basis:
        assert result["breakdown"]["decision_basis"] == basis


def test_release_gate_counts():
    gate = validate_client_forgery_rules(detector())
    assert gate == CLIENT_FORGERY_RULE_GATE
    assert (gate["final_cases"], gate["insufficient_cases"]) == (10, 5)


def test_two_contradictions_convict():
    assert forged_browser_fires(["UA_POINTER_MISMATCH", "WEBDRIVER_TAMPERED"])
    assert forged_browser_fires(["WEBDRIVER_TAMPERED", "SERVER_CPU"])
    assert not forged_browser_fires(["WEBDRIVER_TAMPERED"])
    assert not forged_browser_fires(["WEBDRIVER_TAMPERED", "WEBDRIVER_TAMPERED"])
    assert not forged_browser_fires([])
    assert not forged_browser_fires(None)


def test_forged_browser_is_a_bot_even_without_mouse_input():
    payload = _desktop(coalesced=0.0, multi=0.0, ua=SAFARI9, signals={"webdriverPatched": True})
    payload["mouse"]["records"] = []
    result = detector().predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("BOT", "FINAL")
    assert result["breakdown"]["automation_rule"] == "forged_browser_v1"
    assert result["breakdown"]["decision_basis"] == "forged_browser"
    assert result["breakdown"]["risk_score_in_domain"] is False
    assert "Forged browser" in " ".join(result["reasons"])


def test_random_jumps_on_a_short_session_are_evidence():
    result = detector().predict(_desktop(path=_jumps(n=15)))
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["decision_basis"] == "client_forgery"
    assert result["breakdown"]["client_forgery"]["evidence"] == ["RANDOM_POINTER_JUMPS"]
    assert result["breakdown"]["client_forgery"]["codes"] == []
    bot = detector().predict(_desktop(path=_jumps(n=15), signals={"webdriverPatched": True}))
    assert bot["breakdown"]["automation_rule"] == "synthetic_pointer_path_v1"
