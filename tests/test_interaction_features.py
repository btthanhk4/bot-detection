import json
from copy import deepcopy

import pytest

from core_ml.dataset.field_captures import BotCapture
from core_ml.evaluate_interactions import evaluate_interaction_captures
from core_ml.features.interaction_features import (
    INTERACTION_FEATURE_NAMES,
    extract_interaction_features,
    sanitize_scroll_events,
)
from core_ml.models.ensemble import EnsembleBotDetector


def event(time, type="move", source="mouse"):
    return {"time": time, "type": type, "x": 0.3, "y": 0.4, "source": source}


@pytest.mark.parametrize("mouse", [None, [], {}, {"records": None}, {"records": []}])
def test_absent_interaction_features_are_null_not_human_evidence(mouse):
    report = extract_interaction_features(mouse)
    assert set(report["features"]) == set(INTERACTION_FEATURE_NAMES)
    assert all(value is None for value in report["features"].values())
    assert report["release_approved"] is False
    assert report["mode"] == "measurement_only"
    assert "shadow_verdict" not in report


def test_movement_intervals_sort_stably_and_measure_zero_quantization():
    records = [event(time) for time in (30, 0, 10, 10)]
    original = deepcopy(records)
    report = extract_interaction_features({"records": records})
    assert report["features"]["move_interval_median_ms"] == 10
    assert report["features"]["move_zero_interval_ratio"] == pytest.approx(1 / 3, abs=1e-6)
    assert report["features"]["move_interval_cv"] == pytest.approx(0.816497, abs=1e-6)
    assert records == original


def test_zero_and_single_intervals_do_not_invent_cadence():
    report = extract_interaction_features({"records": [event(1), event(1), event(1)]})
    assert report["features"]["move_interval_cv"] is None
    assert report["features"]["move_zero_interval_ratio"] == 1
    report = extract_interaction_features({"records": [event(1), event(2)]})
    assert report["features"]["move_interval_cv"] is None
    assert report["features"]["move_interval_median_ms"] == 1


def test_complete_presses_and_pre_click_pause_do_not_use_future_moves():
    records = [event(0, "up"), event(10), event(30, "down"), event(70, "up"),
               event(80, "click"), event(90), event(180, "click"), event(200, "down")]
    report = extract_interaction_features({"records": records})
    assert report["features"]["press_duration_median_ms"] == 40
    assert report["features"]["pre_click_pause_median_ms"] == 80
    assert report["features"]["click_interval_median_ms"] == 100
    assert report["features"]["click_interval_cv"] is None
    assert report["counts"]["paired_presses"] == 1


def test_click_without_preceding_move_remains_unknown():
    report = extract_interaction_features({"records": [event(20, "click"), event(30)]})
    assert report["features"]["pre_click_pause_median_ms"] is None
    assert report["counts"]["clicks_with_preceding_move"] == 0


def test_ambiguous_overlapping_presses_do_not_invent_dwell():
    report = extract_interaction_features({"records": [
        event(1, "down"), event(2, "down"), event(3, "up"), event(4, "up"),
    ]})
    assert report["features"]["press_duration_median_ms"] is None


def test_touch_unknown_source_and_invalid_events_are_excluded():
    report = extract_interaction_features({"records": [
        event(10), event(20, source="touch"), event(30, source="pen"),
        event(40, type="unknown"), event(True), event(float("nan")), event(-1),
    ]})
    assert report["counts"]["moves"] == 1
    assert report["counts"]["touch_events_excluded"] == 1
    assert report["features"]["move_interval_median_ms"] is None


def test_legacy_records_and_trajectory_fallback_remain_supported():
    records = [event(10), event(20), event(30)]
    for row in records:
        row.pop("source")
    report = extract_interaction_features({"trajectory": records})
    assert report["features"]["move_interval_cv"] == 0


def test_empty_records_use_legacy_trajectory_like_the_ensemble():
    report = extract_interaction_features({"records": [], "trajectory": [
        event(0), event(10), event(20),
    ]})
    assert report["counts"]["moves"] == 3
    assert report["features"]["move_interval_cv"] == 0


def test_vertical_reversals_ignore_horizontal_and_zero_delta_samples():
    scroll = [{"time": 0, "deltaY": 100}, {"time": 5, "deltaY": 0},
              {"time": 10, "deltaY": -100}, {"time": 20, "deltaX": 100},
              {"time": 30, "deltaY": -100}]
    report = extract_interaction_features({"scrollEvents": scroll})
    assert report["counts"]["scroll_events"] == 4
    assert report["features"]["scroll_interval_cv"] == 0
    assert report["features"]["scroll_delta_abs_cv"] == 0
    assert report["features"]["vertical_scroll_reversal_ratio"] == 0.5


@pytest.mark.parametrize("scroll", [None, {}, [None], [{"time": True}],
                                    [{"time": -1}], [{"time": 1, "deltaY": "100"}],
                                    [{"time": 1, "deltaY": float("inf")}],
                                    [{"time": 1, "deltaY": 1e7}], [{"time": 10**400}]])
def test_invalid_scroll_is_safe_and_not_evidence(scroll):
    report = extract_interaction_features({"scrollEvents": scroll})
    assert report["counts"]["scroll_events"] == 0
    assert report["features"]["scroll_interval_cv"] is None
    json.dumps(report, allow_nan=False)


def test_retained_windows_are_bounded_and_finite_at_large_timestamps():
    mouse = {"records": [event(i * 1e13) for i in range(150)],
             "scrollEvents": [{"time": i * 1e13, "deltaY": 1e6} for i in range(80)]}
    report = extract_interaction_features(mouse)
    assert report["counts"]["mouse_events"] == 100
    assert report["counts"]["scroll_events"] == 50
    assert len(sanitize_scroll_events(mouse["scrollEvents"])) == 50
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("move_count", [0, 25])
def test_interactions_cannot_change_production_verdict_score_or_weights(move_count):
    class LowLstm:
        def predict_session_scores(self, _chunks):
            return 0.02, 0.03

    class LowTabular:
        def predict_proba(self, _features):
            return 0.02

    detector = EnsembleBotDetector(lstm_model=LowLstm(), tabular_model=LowTabular())
    mouse = {"records": [{**event(i * 16), "x": i / 100} for i in range(move_count)]}
    baseline = detector.predict({"mouse": mouse})
    mouse["scrollEvents"] = [{"time": i * 10, "deltaY": 120} for i in range(50)]
    result = detector.predict({"mouse": mouse})
    assert result["breakdown"]["interaction_shadow"]["features"]["scroll_interval_cv"] == 0
    for prediction in (baseline, result):
        prediction["breakdown"].pop("interaction_shadow")
    assert result == baseline
    assert result["verdict"] == ("HUMAN" if move_count else "SUSPECT")


def capture(id, mouse, *, label="BOT", participant_id=None):
    payload = {"sessionId": id, "mouse": mouse}
    return BotCapture(id, "family", (payload, payload, {"mouse": {"records": []}}),
                      label=label, participant_id=participant_id)


class Detector:
    def predict(self, payload):
        assert payload.get("sessionId")
        return {"verdict": "HUMAN"}


def test_evaluator_measures_one_final_window_per_run_and_excludes_probe():
    runs = [capture("a", {"records": [event(0), event(10), event(20)]}),
            capture("b", {"records": [event(0)]})]
    report = evaluate_interaction_captures(Detector(), runs)
    group = report["groups"][0]
    assert report["runs"] == group["runs"] == 2
    assert group["sent_snapshots"] == 4
    assert group["baseline_final"] == {"HUMAN": 2}
    assert group["features"]["move_interval_cv"]["available_runs"] == 1
    assert group["features"]["move_interval_cv"]["median"] == 0
    assert report["release_approved"] is False


def test_evaluator_counts_human_participants_not_repeated_runs():
    report = evaluate_interaction_captures(Detector(), [
        capture("a", {}, label="HUMAN", participant_id="p1"),
        capture("b", {}, label="HUMAN", participant_id="p1"),
    ])
    assert report["human_runs"] == 2
    assert report["human_participants"] == 1


def test_evaluator_rejects_duplicate_sessions_and_no_data():
    with pytest.raises(ValueError, match="share"):
        evaluate_interaction_captures(Detector(), [capture("a", {}), capture("a", {})])
    with pytest.raises(ValueError, match="At least one"):
        evaluate_interaction_captures(Detector(), [])
