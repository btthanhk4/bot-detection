import json
import math
import subprocess
import sys
from copy import deepcopy

import pytest

from core_ml.analyze_mouse_actions import (
    MAX_INPUT_EVENTS, analyze_document, analyze_mouse_actions,
)


def point(time, x, y=0.2, type="move", **extra):
    return {"time": time, "x": x, "y": y, "type": type, "source": "mouse", **extra}


def report(records, **extra):
    return analyze_mouse_actions({"records": records, **extra})


def test_per_event_derivatives_match_hand_calculation_without_invented_initial_values():
    records = [point(i * 100, x) for i, x in enumerate([0, 0.01, 0.04, 0.09])]
    original = deepcopy(records)
    measured = report(records)
    events = measured["events"]
    assert [e["speed"] for e in events] == pytest.approx([None, 0.1, 0.3, 0.5])
    assert events[1]["acceleration"] is None
    assert events[2]["acceleration"] == pytest.approx(2)
    assert events[2]["jerk"] is None
    assert events[3]["acceleration"] == pytest.approx(2)
    assert events[3]["jerk"] == pytest.approx(0, abs=1e-12)
    assert measured["strokes"][0]["mean_speed"] == pytest.approx(0.3)
    assert measured["strokes"][0]["straightness"] == pytest.approx(1)
    assert measured["counts"]["accelerations_available"] == 2
    assert records == original


def test_turn_and_vector_acceleration_capture_a_right_angle():
    events = report([point(0, 0, 0), point(100, 0.1, 0), point(200, 0.1, 0.1)])["events"]
    assert events[2]["turn_radians"] == pytest.approx(math.pi / 2)
    assert events[2]["curvature"] == pytest.approx(math.pi / 0.2)
    assert events[2]["acceleration"] == pytest.approx(math.sqrt(200))
    assert events[2]["tangential_acceleration"] == pytest.approx(0)


@pytest.mark.parametrize("gap,flag", [(0, "duplicate_timestamp"), (251, "gap_boundary")])
def test_duplicate_times_and_gaps_reset_motion_history(gap, flag):
    measured = report([point(0, 0), point(10, 0.1), point(10 + gap, 0.8), point(20 + gap, 0.9)])
    events = measured["events"]
    assert flag in events[2]["flags"]
    assert events[2]["speed"] is None
    assert events[3]["speed"] == pytest.approx(10)
    assert events[3]["acceleration"] is None
    assert len(measured["strokes"]) == 2


def test_exact_gap_limit_is_inclusive_and_stationary_direction_is_unknown():
    measured = report([point(0, 0.1), point(250, 0.1), point(500, 0.2)])
    assert len(measured["strokes"]) == 1
    assert measured["events"][1]["speed"] == 0
    assert measured["events"][2]["turn_radians"] is None
    stationary = report([point(i * 10, 0.2) for i in range(4)])["strokes"][0]
    assert stationary["mean_speed"] == 0
    assert stationary["straightness"] is None
    assert stationary["speed_cv"] is None


def test_click_boundaries_reset_derivatives_but_keep_observed_click_timing():
    measured = report([point(0, 0.1), point(10, 0.2), point(20, 0.2, type="click"), point(30, 0.4)])
    assert measured["events"][-1]["speed"] is None
    assert measured["clicks"][0]["since_last_move_ms"] == 10
    assert measured["clicks"][0]["since_last_click_ms"] is None


def test_unambiguous_press_retains_path_and_click_context():
    measured = report([point(0, 0.1, type="down"), point(30, 0.2), point(50, 0.3, type="up"),
                       point(50, 0.3, type="click"), point(200, 0.3, type="click")])
    press = measured["presses"][0]
    assert press["status"] == "paired"
    assert press["duration_ms"] == 50
    assert press["move_event_ids"] == [1]
    assert press["sampled_path_length"] == pytest.approx(0.2)
    assert press["displacement"] == pytest.approx(0.2)
    assert measured["clicks"][0]["since_last_move_ms"] == 20
    assert measured["clicks"][1]["since_last_click_ms"] == 150


def test_missing_press_endpoints_stay_missing():
    measured = report([point(10, 0.1, type="up"), point(20, 0.1, type="click"),
                       point(30, 0.1, type="down")])
    assert [p["status"] for p in measured["presses"]] == ["missing_down", "missing_up"]
    assert all(p["duration_ms"] is None for p in measured["presses"])
    assert measured["clicks"][0]["since_last_move_ms"] is None


def test_overlapping_presses_cannot_be_guessed_without_button_identity():
    measured = report([point(i * 10, 0.1, type=t) for i, t in enumerate(
        ["down", "down", "up", "up", "down", "up"])])
    assert measured["counts"]["paired_presses"] == 0
    assert all(p["status"] == "ambiguous_overlap" for p in measured["presses"])


def test_touch_interrupts_mouse_derivatives_press_pairing_and_click_context():
    measured = report([point(0, 0.1, type="down"), point(10, 0.2),
                       point(20, 0.9, source="touch"), point(30, 0.3),
                       point(40, 0.4, type="up"), point(50, 0.4, type="click")])
    assert measured["events"][2]["speed"] is None
    assert measured["events"][3]["speed"] is None
    assert [p["status"] for p in measured["presses"]] == ["interrupted", "missing_down"]
    assert measured["counts"]["touch_events"] == 1
    assert measured["clicks"][0]["since_last_move_ms"] == 20


@pytest.mark.parametrize("bad", [None, {}, {"time": True, "x": 0, "y": 0},
                                  point(15, float("nan")), point(15, 0, type=[]),
                                  point(15, 0, source="pen"), point(15, 10**10000)])
def test_invalid_event_cuts_continuity_instead_of_joining_across_it(bad):
    measured = report([point(0, 0.1), point(10, 0.2), bad, point(20, 0.3), point(30, 0.4)])
    assert measured["coverage"]["invalid_events"] == 1
    assert measured["events"][2]["speed"] is None
    assert "input_discontinuity" in measured["events"][2]["flags"]
    assert measured["events"][3]["speed"] == pytest.approx(10)
    json.dumps(measured, allow_nan=False)


def test_reordered_records_are_disclosed_and_do_not_link_backwards_input():
    measured = report([point(20, 0.2), point(0, 0), point(10, 0.1)])
    assert measured["coverage"]["input_reordered"] is True
    assert [e["input_index"] for e in measured["events"]] == [1, 2, 0]
    assert measured["events"][-1]["speed"] is None


def test_client_derivatives_and_prediction_fields_are_ignored():
    plain = [point(0, 0), point(10, 0.1)]
    forged = [{**e, "speed": 9999, "accel": 8888, "jerk": 1111} for e in plain]
    assert report(plain) == report(forged, stats={"bot_probability": 1.0}, verdict="BOT")
    assert report(plain)["used_for_classification"] is False


@pytest.mark.parametrize("step", [1e-308, 1e-320])
def test_extreme_finite_timestamps_never_export_nonfinite_derivatives(step):
    measured = report([point(i * step, i * 0.1) for i in range(5)])
    json.dumps(measured, allow_nan=False)


def test_bounds_disclose_both_inspection_and_retention_without_claiming_full_session():
    measured = report([point(i * 10, 0.1) for i in range(MAX_INPUT_EVENTS + 2)])
    assert measured["coverage"]["uninspected_events"] == 2
    assert measured["coverage"]["valid_events_outside_window"] == MAX_INPUT_EVENTS - 100
    assert len(measured["events"]) == 100
    assert measured["events"][0]["speed"] is None
    assert measured["coverage"]["complete_session"] is False


def test_legacy_numeric_strings_and_raw_coordinates_keep_units_explicit():
    measured = report([], trajectory=[{"t": "0", "x": "100", "y": "100"},
                                      {"t": "100", "x": "200", "y": "100"}])
    assert measured["events"][1]["speed"] == 1000
    assert measured["units"]["coordinate_space"] == "unknown"
    assert measured["units"]["pixel_geometry_available"] is False


def test_wheel_measurements_use_unknown_units_and_no_reverse_vote_across_long_gaps():
    measured = report([], scrollEvents=[{"time": 0, "deltaY": 5}, {"time": 10, "deltaY": -5},
                                        {"time": 1000, "deltaY": 5}, {"time": True, "deltaY": 1}])
    assert [e["vertical_reversal"] for e in measured["wheel"]] == [None, True, None]
    assert measured["coverage"]["wheel"]["invalid_events"] == 1
    assert measured["coverage"]["wheel"]["delta_units"] == "unknown_deltaMode_not_collected"


@pytest.mark.parametrize("mouse", [None, [], True, {"records": 1, "scrollEvents": 2}])
def test_empty_or_malformed_window_is_missing_evidence(mouse):
    measured = analyze_mouse_actions(mouse)
    assert measured["events"] == []
    assert measured["counts"]["speeds_available"] == 0
    assert measured["coverage"]["first_time_ms"] is None
    json.dumps(measured, allow_nan=False)


def test_capture_selects_last_sent_window_and_excludes_probe_and_identifiers():
    payload = {"sessionId": "private-session", "visitorId": "private-visitor",
               "mouse": {"records": [point(0, 0.1)]}}
    probe = {**payload, "action": "test-probe", "mouse": {"records": [point(0, 0.9)]}}
    measured = analyze_document({"snapshots": [payload, probe]})
    assert measured["events"][0]["x"] == 0.1
    assert measured["selection"]["snapshot_index"] == 0
    assert "private-" not in json.dumps(measured)
    assert analyze_document({"snapshots": [payload, probe]}, 0) == measured


@pytest.mark.parametrize("document,index", [([], None), ({"snapshots": []}, None),
    ({"snapshots": [None]}, None), ({"snapshots": [{"action": "test-probe"}]}, None),
    ({"snapshots": [{}, {"action": "test-probe"}]}, 1), ({"snapshots": [{}]}, -1),
    ({"snapshots": [{}]}, True), ({"mouse": {}}, 0)])
def test_document_selection_rejects_invalid_or_probe_only_input(document, index):
    with pytest.raises(ValueError):
        analyze_document(document, index)


def test_cli_writes_strict_json_and_prevents_input_overwrite(tmp_path):
    capture = tmp_path / "input.json"
    output = tmp_path / "detail.json"
    content = json.dumps({"mouse": {"records": [point(0, 0), point(10, 0.1)]}})
    capture.write_text(content, encoding="utf-8-sig")
    cmd = [sys.executable, "-m", "core_ml.analyze_mouse_actions", "--input", str(capture), "--output"]
    result = subprocess.run([*cmd, str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["events"][1]["speed"] == 10
    result = subprocess.run([*cmd, str(capture)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "must not overwrite" in result.stderr
    assert capture.read_text(encoding="utf-8-sig") == content
