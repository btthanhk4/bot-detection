"""Synthetic-click evidence and the policy 11 decision rule."""

import numpy as np
import pytest

from core_ml.features.input_provenance import (
    SYNTHETIC_CLICK_RULE,
    analyze_input_provenance,
    sanitize_click_events,
)
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.release_cases import SYNTHETIC_INPUT_CASES

REGULAR_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0"


def click(ox=0.0, oy=0.0, w=80, h=24, hold=0.2):
    return {"ox": ox, "oy": oy, "w": w, "h": h, "hold": hold}


class FixedLSTM:
    def predict_session_scores(self, chunks):
        return 0.05, 0.05


class FixedTabular:
    def predict_proba(self, vector):
        return 0.02


def detector():
    return EnsembleBotDetector(lstm_model=FixedLSTM(), tabular_model=FixedTabular())


def human_moves(n=60):
    rng = np.random.default_rng(1)
    t, x, y, records = 0.0, 300.0, 200.0, []
    for _ in range(n):
        t += float(rng.uniform(12, 22))
        x += float(rng.normal(6, 3))
        y += float(rng.normal(2, 3))
        records.append({"time": t, "x": x, "y": y, "type": "move", "source": "mouse"})
    return records


def predict(clicks, records=None, ua=REGULAR_UA, server_ua=REGULAR_UA, botd=None):
    return detector().predict({
        "_server_user_agent": server_ua,
        "fingerprint": {"userAgent": ua},
        "botd": botd or {"detectors": {}},
        "mouse": {"records": records or [], "clickEvents": clicks},
    })


@pytest.mark.parametrize("expected, clicks", SYNTHETIC_INPUT_CASES)
def test_release_fixtures(expected, clicks):
    result = predict(clicks)
    assert result["verdict"] == expected
    fired = result["breakdown"]["input_provenance"]["synthetic_click_rule"]
    assert (fired == SYNTHETIC_CLICK_RULE) == (expected == "BOT")


def test_rule_decides_even_when_mouse_models_say_human():
    clicks = [click(), click(0.5, -0.3), click(-0.2, 0.0, 120, 40, 0.1)]
    baseline = predict([], records=human_moves())
    assert baseline["verdict"] == "HUMAN"
    result = predict(clicks, records=human_moves())
    assert result["verdict"] == "BOT" and result["decision_state"] == "FINAL"
    assert result["policy_version"] == DECISION_POLICY_VERSION
    breakdown = result["breakdown"]
    assert breakdown["decision_basis"] == "synthetic_input"
    assert breakdown["automation_rule"] == SYNTHETIC_CLICK_RULE
    assert breakdown["risk_score_in_domain"] is False
    assert breakdown["behavioral_lstm_score"] is None
    assert any("Synthetic clicks" in reason for reason in result["reasons"])


def test_headless_rule_keeps_precedence():
    headless = "Mozilla/5.0 Chrome/154.0.0.0 HeadlessChrome/154.0.0.0"
    result = predict([click(), click(), click()], ua=headless, server_ua=headless,
                     botd={"detectors": {"webdriver": True}})
    assert result["breakdown"]["decision_basis"] == "explicit_automation"
    assert result["breakdown"]["automation_rule"] == "headless_ua_and_framework_v1"


def test_three_centred_clicks_with_two_instant_releases_fire():
    clicks = [click(), click(), click(hold=60.0)]
    assert analyze_input_provenance({"clickEvents": clicks})["synthetic_click_rule"] == SYNTHETIC_CLICK_RULE


@pytest.mark.parametrize("clicks", [
    [click(1.01, 0), click(), click()],                       # one click just outside tolerance
    [click(), click(), click(w=15)],                          # small target is ignored -> only two
    [click(hold=5.0), click(hold=5.0), click(hold=0.1)],      # only one release under 5 ms
    [click(hold=None), click(hold=None), click(hold=None)],   # no press timing
    [click(), click(), click(), click(3.0, 1.0, hold=110.0)],  # a single human click breaks the lock
])
def test_near_misses_do_not_fire(clicks):
    result = predict(clicks, records=human_moves())
    assert result["breakdown"]["input_provenance"]["synthetic_click_rule"] is None
    assert result["verdict"] == "HUMAN"


def test_boundaries_are_inclusive_for_centre_and_exclusive_for_hold():
    edge = [click(1.0, -1.0, hold=4.99), click(-1.0, 1.0, hold=4.99), click(hold=4.99)]
    assert analyze_input_provenance({"clickEvents": edge})["synthetic_click_rule"]
    slow = [dict(c, hold=5.0) for c in edge]
    assert analyze_input_provenance({"clickEvents": slow})["synthetic_click_rule"] is None


@pytest.mark.parametrize("raw", [None, "x", 5, [None, "x", 3], [{"ox": 1e9, "oy": 0, "w": 80, "h": 20}],
                                 [{"ox": 0, "oy": 0, "w": -5, "h": 20}], [{"ox": 0, "oy": 0, "w": 80, "h": 20, "hold": -1}]])
def test_malformed_click_events_are_ignored(raw):
    clean = sanitize_click_events(raw)
    assert all(c["hold"] is None or c["hold"] >= 0 for c in clean)
    report = analyze_input_provenance({"clickEvents": raw})
    assert report["synthetic_click_rule"] is None


def test_click_history_is_bounded():
    many = [click() for _ in range(500)]
    assert len(sanitize_click_events(many)) == 30


def test_pointer_stats_are_reported():
    mouse = {"records": human_moves(), "clickEvents": [],
             "pointerStats": {"pointermove": 50, "coalescedTotal": 95, "coalescedMax": 3,
                              "coalescedMulti": 40, "secureContext": True, "frameMs": 16.7, "frames": 60}}
    result = detector().predict({"_server_user_agent": REGULAR_UA, "fingerprint": {"userAgent": REGULAR_UA},
                                 "botd": {"detectors": {}}, "mouse": mouse})
    stats = result["breakdown"]["input_provenance"]["pointer_stats"]
    assert stats == {"pointer_moves": 50, "coalesced_mean": 1.9, "coalesced_max": 3,
                     "coalesced_multi_share": 0.8, "secure_context": True, "frame_ms": 16.7, "frames": 60,
                     "raw_updates": 0, "coalesced_self": 0, "coalesced_stale": 0}
    assert result["verdict"] == "HUMAN"


def simulate_humans(rng, sessions, centre_sd_fraction, tap_share):
    """Human clicks: Gaussian scatter around the centre; some touchpad taps release instantly."""
    fired = 0
    for _ in range(sessions):
        clicks = []
        for _ in range(int(rng.integers(3, 13))):
            w = float(rng.choice([24, 32, 44, 80, 120, 200]))
            h = float(rng.choice([20, 24, 32, 40, 48]))
            hold = float(rng.uniform(0.0, 4.0)) if rng.random() < tap_share else float(rng.lognormal(np.log(95), 0.35))
            clicks.append(click(round(float(rng.normal(0, centre_sd_fraction * w)), 2),
                                round(float(rng.normal(0, centre_sd_fraction * h)), 2), w, h, round(hold, 2)))
        fired += analyze_input_provenance({"clickEvents": clicks})["synthetic_click_rule"] is not None
    return fired


def test_simulated_humans_almost_never_trigger_the_rule():
    """Monte Carlo false-positive estimate under explicit, pessimistic assumptions.

    Even with unusually precise users (scatter SD = 8% of the target) who all use
    tap-to-click, the rule stays below 1 in 5,000 sessions. This is a model of
    human behaviour, not a measurement; it must be confirmed on real sessions.
    """
    rng = np.random.default_rng(2026)
    assert simulate_humans(rng, 20_000, 0.15, 0.2) == 0
    assert simulate_humans(rng, 20_000, 0.08, 1.0) <= 4


def test_playwright_style_sessions_always_trigger():
    rng = np.random.default_rng(7)
    for _ in range(2_000):
        n = int(rng.integers(3, 10))
        clicks = [click(round(float(rng.uniform(-0.7, 0.7)), 2), 0.0, float(rng.choice([29, 80, 140])),
                        float(rng.choice([20, 36, 40])), round(float(rng.uniform(0.0, 0.4)), 2)) for _ in range(n)]
        assert analyze_input_provenance({"clickEvents": clicks})["synthetic_click_rule"] == SYNTHETIC_CLICK_RULE


# ---- Policy 15: typing rhythm and press pressure ----
from core_ml.features.input_provenance import (  # noqa: E402
    SYNTHETIC_POINTER_RULE, SYNTHETIC_TYPING_RULE, analyze_typing,
)
from core_ml.release_cases import SYNTHETIC_DEVICE_CASES, _strokes  # noqa: E402


@pytest.mark.parametrize("expected, rule, payload", SYNTHETIC_DEVICE_CASES)
def test_device_release_fixtures(expected, rule, payload):
    result = detector().predict(payload)
    assert result["verdict"] == expected
    assert result["breakdown"]["automation_rule"] == rule


def test_sliding_windows_find_a_scripted_field_inside_human_typing():
    human = _strokes([92, 71, 104, 66, 118, 83, 97, 59, 88, 131], [212, 148, 305, 176, 260, 131, 228, 190, 342, 158])
    scripted = [dict(s, t=s["t"] + 3000) for s in _strokes([2.0] * 9, [1.0] * 9)]
    report = analyze_typing({"keystrokes": human + scripted})
    assert "TYPING_INSTANT_HOLD" in report["codes"]
    assert analyze_typing({"keystrokes": human})["codes"] == []


def test_thresholds_are_strict_at_the_boundary():
    at_limit = _strokes([12.0] * 8, [5, 7, 6, 8, 5, 9, 6, 7])
    assert "TYPING_INSTANT_HOLD" not in analyze_typing({"keystrokes": at_limit})["codes"]
    below = _strokes([11.9] * 8, [5, 7, 6, 8, 5, 9, 6, 7])
    assert "TYPING_INSTANT_HOLD" in analyze_typing({"keystrokes": below})["codes"]
    spaced = _strokes([2.0] * 8, [12, 13, 12, 14, 12, 13, 12, 12])
    assert "TYPING_INSTANT_HOLD" not in analyze_typing({"keystrokes": spaced})["codes"]


def test_policy_22_needs_combined_evidence():
    # Instant holds at a human pace: a keyboard that reports key-up with key-down.
    report = analyze_typing({"keystrokes": _strokes([0.5] * 12, [212, 148, 305, 176, 260, 131, 228, 190, 342, 158, 207, 263])})
    assert report["codes"] == [] and report["fastest_median_hold_ms"] == 0.5
    # A skilled typist with an even rhythm (interval CV 0.05) but human holds.
    steady = _strokes([92, 71, 104, 66, 118, 83, 97, 59, 88, 131, 74, 95],
                      [150, 160, 145, 155, 165, 150, 140, 158, 152, 147, 162, 149])
    report = analyze_typing({"keystrokes": steady})
    assert report["codes"] == [] and report["lowest_interval_cv"] < 0.10 and report["lowest_rhythm_cv"] > 0.1
    # Scripts measured 2026-10-28.
    delay = _strokes([104.5, 105.1, 104.8, 105.3, 104.6, 105.0, 104.9, 105.2, 104.7, 105.1, 104.8, 105.0],
                     [105.9, 106.2, 105.8, 106.1, 106.0, 105.7, 106.3, 105.9, 106.0, 106.1, 105.8, 106.0])
    assert analyze_typing({"keystrokes": delay})["codes"] == ["TYPING_METRONOME"]
    selenium = _strokes([0.3, 0.4, 0.3, 0.35, 0.3, 0.4, 0.3, 0.3, 0.35, 0.4, 0.3, 0.3],
                        [110.4, 111.2, 109.8, 110.6, 110.9, 110.1, 111.4, 110.2, 110.7, 110.3, 111.0, 110.5])
    assert analyze_typing({"keystrokes": selenium})["codes"] == ["TYPING_INSTANT_METRONOME"]


def test_pauses_split_bursts_and_ten_keys_are_not_enough_for_rhythm():
    even = _strokes([100.0] * 10, [100.0] * 10)
    assert analyze_typing({"keystrokes": even})["lowest_interval_cv"] is None
    split = even + [dict(s, t=s["t"] + 5000) for s in _strokes([100.0] * 10, [100.0] * 10)]
    assert analyze_typing({"keystrokes": split})["lowest_interval_cv"] is None


def test_pressure_rule_needs_chromium_and_repetition():
    chrome = "Mozilla/5.0 Chrome/155.0.0.0"
    assert analyze_input_provenance({"pointerStats": {"zeroPressureDowns": 2}}, chrome)["synthetic_input_rule"] == SYNTHETIC_POINTER_RULE
    assert analyze_input_provenance({"pointerStats": {"zeroPressureDowns": 1}}, chrome)["synthetic_input_rule"] is None
    assert analyze_input_provenance({"pointerStats": {"zeroPressureDowns": 5}}, "Firefox/158.0")["synthetic_input_rule"] is None
    assert analyze_input_provenance({"pointerStats": {"zeroPressureDowns": "x"}}, chrome)["synthetic_input_rule"] is None


def test_typing_rule_reports_the_measured_evidence():
    payload = SYNTHETIC_DEVICE_CASES[1][2]
    result = detector().predict(payload)
    assert result["breakdown"]["automation_rule"] == SYNTHETIC_TYPING_RULE
    assert any("Synthetic typing" in reason and "holds and intervals equal" in reason for reason in result["reasons"])
