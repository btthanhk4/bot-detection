import math

import numpy as np

from core_ml.features.motor_features import (
    extract_motor_features,
    neuromotor_features,
    timing_features,
)


def _records(points):
    return [{"time": t, "x": x, "y": y, "type": "move"} for t, x, y in points]


def _lognormal_stroke(n=60, dt=10.0, distance=400.0, mu=-1.6, sigma=0.35):
    """A human-like single stroke whose speed follows a lognormal profile."""
    t = np.arange(1, n + 1) * dt / 1000.0
    speed = distance / (math.sqrt(2 * math.pi) * sigma * t) * np.exp(-((np.log(t) - mu) ** 2) / (2 * sigma ** 2))
    x = np.concatenate([[0.0], np.cumsum(speed[1:] * np.diff(t))])
    return [(ti * 1000.0, xi, 0.4 * xi) for ti, xi in zip(t, x)]


def test_lognormal_stroke_is_recognised_as_a_good_fit():
    t, x, y = map(np.array, zip(*_lognormal_stroke()))
    features = neuromotor_features(t, x, y)
    assert features["neu_lognorm_r2_mean"] > 0.9
    assert features["neu_peak_time_ratio_mean"] < 0.5  # lognormal peaks early


def test_constant_speed_line_has_mostly_flat_acceleration():
    points = [(i * 16.0, i * 5.0, 100.0) for i in range(80)]
    t, x, y = map(np.array, zip(*points))
    assert neuromotor_features(t, x, y)["neu_near_zero_accel_frac"] > 0.8


def test_timing_flags_teleports_repeats_and_regular_intervals():
    points = [(i * 16.0, 10.0 + i, 10.0) for i in range(30)] + [(30 * 16.0, 900.0, 600.0)]
    points += [(31 * 16.0, 900.0, 600.0)]
    t, x, y = map(np.array, zip(*points))
    features = timing_features(t, x, y, clicks=[(32 * 16.0, 1200.0, 50.0)])
    assert features["tim_teleport_frac"] > 0
    assert features["tim_zero_step_frac"] > 0
    assert features["tim_dt_mode_share"] == 1.0
    assert features["tim_click_gap_px"] > 300


def test_short_or_malformed_input_yields_no_invented_values():
    assert extract_motor_features([]) == {}
    bad = [{"time": "x", "x": 1, "y": 2}, {"time": float("nan"), "x": 1, "y": 1}]
    assert extract_motor_features(bad) == {}
    features = extract_motor_features(_records([(i * 16.0, i, i) for i in range(8)]))
    assert all(isinstance(v, float) for v in features.values())
