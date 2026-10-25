import json
import math
import random
from copy import deepcopy

import pytest

from core_ml.features.interaction_features import _cv, _window_cv, extract_interaction_features
from core_ml.models.ensemble import EnsembleBotDetector


def point(i, x=None, y=0.2, **extra):
    return {"time": i * 16, "x": i / 100 if x is None else x, "y": y,
            "type": "move", "source": "mouse", **extra}


def measure(records):
    return extract_interaction_features({"records": records})


@pytest.mark.parametrize("scale", [1e-200, 1.0, 1e200])
def test_fast_window_cv_matches_reference_across_numeric_scales(scale):
    rng = random.Random(42)
    for _ in range(100):
        values = [rng.random() for _ in range(13)]
        # Keep the reference variance in range; Python 3.10 squares before sqrt.
        assert _window_cv([value * scale for value in values]) == pytest.approx(_cv(values), abs=1e-12)
    assert _window_cv([scale] * 13) == 0
    assert _window_cv([0.0] * 12 + [scale]) == pytest.approx(math.sqrt(12))


def test_uniform_line_has_local_measurements_without_bot_verdict():
    records = [point(i) for i in range(14)]
    original = deepcopy(records)
    report = measure(records)
    assert report["feature_version"] == "interaction_window_v2"
    assert report["features"]["move_window_speed_cv_min"] == 0
    assert report["features"]["move_window_speed_cv_median"] == 0
    assert report["features"]["move_window_straightness_max"] == 1
    assert report["features"]["move_window_regular_line_score_max"] == 1
    assert report["features"]["move_window_turn_cv_min"] is None
    assert report["counts"]["motion_windows_valid"] == 1
    assert report["counts"]["turn_windows_valid"] == 0
    assert report["release_approved"] is False
    assert report["mode"] == "measurement_only"
    assert "shadow_verdict" not in report
    assert records == original


@pytest.mark.parametrize("prefix_length", [1, 3, 7, 13])
def test_stride_one_finds_an_off_grid_regular_segment(prefix_length):
    noisy = [point(i, x=(i % 2) * 0.7, y=(i % 3) * 0.2)
             for i in range(prefix_length)]
    regular = [point(i + prefix_length, x=0.2 + i * 0.01) for i in range(14)]
    suffix = [point(i + prefix_length + 14, x=(i % 2) * 0.7) for i in range(8)]
    report = measure(noisy + regular + suffix)
    assert report["features"]["move_window_regular_line_score_max"] == 1
    assert report["features"]["move_window_speed_cv_median"] > 0
    assert report["counts"]["motion_windows_valid"] == prefix_length + 9


def test_uniform_circle_measures_turn_regularity_not_a_straight_line():
    records = [point(i, x=0.5 + 0.2 * math.cos(i * 0.25),
                     y=0.5 + 0.2 * math.sin(i * 0.25)) for i in range(28)]
    report = measure(records)
    assert report["features"]["move_window_turn_cv_min"] == 0
    assert report["features"]["move_window_speed_cv_min"] == 0
    assert report["features"]["move_window_regular_line_score_max"] < 0.7
    assert report["counts"]["turn_windows_valid"] == 15


@pytest.mark.parametrize("count,stationary", [(0, False), (1, False), (13, False), (20, True)])
def test_missing_short_or_stationary_motion_does_not_invent_local_evidence(count, stationary):
    report = measure([point(i, x=0.2 if stationary else None) for i in range(count)])
    local = {k: v for k, v in report["features"].items() if k.startswith("move_window_")}
    assert len(local) == 5
    assert all(value is None for value in local.values())
    assert report["counts"]["motion_windows_valid"] == 0
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("boundary", ["touch", "pause", "duplicate"])
def test_motion_windows_do_not_bridge_touch_pauses_or_duplicate_timestamps(boundary):
    records = [point(i) for i in range(14)]
    if boundary == "touch":
        records.insert(7, point(6.5, source="touch"))
    elif boundary == "pause":
        for record in records[7:]:
            record["time"] += 1000
    else:
        records[7]["time"] = records[6]["time"]
    assert measure(records)["counts"]["motion_windows_valid"] == 0


def test_legacy_records_sorting_and_uniform_unit_changes_are_supported():
    records = [point(i, x=0.5 + 0.2 * math.cos(i * 0.2),
                     y=0.5 + 0.2 * math.sin(i * 0.2)) for i in range(20)]
    baseline = measure(records)
    changed = [{"t": row["time"], "x": row["x"] * 800 + 10,
                "y": row["y"] * 800 + 20} for row in reversed(records)]
    report = extract_interaction_features({"trajectory": changed})
    for key, value in baseline["features"].items():
        if key.startswith("move_window_"):
            assert report["features"][key] == pytest.approx(value, abs=1e-6)


def test_degenerate_small_timestamps_cannot_produce_nonfinite_output():
    records = [point(i, time=i * 1e-320) for i in range(14)]
    report = measure(records)
    assert report["counts"]["motion_windows_valid"] == 0
    json.dumps(report, allow_nan=False)


def test_duplicate_positions_do_not_create_a_direction_for_turn_measurements():
    records = [point(i) for i in range(14)]
    records[5]["x"] = records[4]["x"]
    report = measure(records)
    assert report["counts"]["motion_windows_valid"] == 1
    assert report["counts"]["turn_windows_valid"] == 0
    assert report["features"]["move_window_turn_cv_min"] is None


def test_local_windows_are_bounded_by_the_existing_collector_window():
    report = measure([point(i, x=(i % 20) / 100) for i in range(1000)])
    assert report["counts"]["mouse_events"] == 100
    assert report["counts"]["motion_windows_examined"] == 87
    assert report["counts"]["motion_windows_valid"] == 87


def test_touch_only_motion_is_not_reclassified_as_mouse():
    report = measure([point(i, source="touch") for i in range(30)])
    assert report["counts"]["touch_events_excluded"] == 30
    assert report["counts"]["motion_windows_valid"] == 0
    assert report["features"]["move_window_regular_line_score_max"] is None


def test_non_move_events_do_not_become_motion_points():
    records = [point(i) for i in range(13)]
    records += [point(14, type="click"), point(15, type="down"), point(16, type="up")]
    assert measure(records)["counts"]["motion_windows_valid"] == 0


def test_local_measurements_cannot_change_production_decision(monkeypatch):
    class Lstm:
        def predict_session_scores(self, _chunks):
            return 0.02, 0.03

    class Tabular:
        def predict_proba(self, _features):
            return 0.02

    detector = EnsembleBotDetector(lstm_model=Lstm(), tabular_model=Tabular())
    payload = {"mouse": {"records": [point(i) for i in range(30)]}}
    measured = detector.predict(payload)
    assert measured["breakdown"]["interaction_shadow"]["features"][
        "move_window_regular_line_score_max"] == 1
    monkeypatch.setattr("core_ml.models.ensemble.extract_interaction_features", lambda _: {})
    baseline = detector.predict(payload)
    for result in (measured, baseline):
        result["breakdown"].pop("interaction_shadow")
    assert measured == baseline
    assert measured["verdict"] == "HUMAN"
