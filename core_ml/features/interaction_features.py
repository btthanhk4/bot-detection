"""Bounded interaction-window measurements; not a classifier or session totals."""

import math
from statistics import fmean, median, pstdev

from core_ml.features.mouse_features import MAX_EVENT_TIME, sanitize_mouse_records


INTERACTION_FEATURE_VERSION = "interaction_window_v2"
MAX_SCROLL_EVENTS = 50
MAX_SCROLL_DELTA = 1_000_000.0
LOCAL_MOVE_WINDOW = 14
LOCAL_MOVE_MAX_GAP_MS = 250
INTERACTION_FEATURE_NAMES = (
    "move_interval_median_ms", "move_interval_cv", "move_zero_interval_ratio",
    "click_interval_median_ms", "click_interval_cv", "press_duration_median_ms",
    "pre_click_pause_median_ms", "scroll_interval_median_ms", "scroll_interval_cv",
    "scroll_delta_abs_cv", "vertical_scroll_reversal_ratio",
    "move_window_speed_cv_min", "move_window_speed_cv_median",
    "move_window_straightness_max", "move_window_regular_line_score_max",
    "move_window_turn_cv_min",
)


def _number(value):
    if type(value) not in (int, float):
        return None
    try:
        numeric = float(value)
    except OverflowError:
        return None
    return numeric if math.isfinite(numeric) else None


def sanitize_scroll_events(events, max_events=MAX_SCROLL_EVENTS):
    """Preserve chronological wheel samples without accepting NaN or booleans."""
    if not isinstance(events, list):
        return []
    valid = []
    for event in events:
        if not isinstance(event, dict):
            continue
        time = _number(event.get("time"))
        dx = _number(event.get("deltaX", 0))
        dy = _number(event.get("deltaY", 0))
        if (time is None or dx is None or dy is None or not 0 <= time <= MAX_EVENT_TIME
                or max(abs(dx), abs(dy)) > MAX_SCROLL_DELTA):
            continue
        valid.append({"time": time, "deltaX": dx, "deltaY": dy})
    valid.sort(key=lambda event: event["time"])
    return valid[-max_events:] if max_events > 0 else valid


def _intervals(events):
    return [b["time"] - a["time"] for a, b in zip(events, events[1:])]


def _cv(values):
    if len(values) < 2:
        return None
    mean = fmean(values)
    return pstdev(values) / mean if mean > 0 else None


def _median(values):
    return median(values) if values else None


def _window_cv(values):
    """Fast two-pass CV for a finite, nonnegative window with a positive peak."""
    peak = max(values)
    scaled = [value / peak for value in values]
    mean = fmean(scaled)
    return math.sqrt(fmean((value - mean) ** 2 for value in scaled)) / mean


def _local_motion_features(events):
    """Measure every short move window; these are descriptors, not bot votes."""
    window = []
    speed_cvs, straightnesses, regular_lines, turn_cvs = [], [], [], []
    examined = 0
    for event in events:
        if event.get("source") == "touch":
            window.clear()
            continue
        if event["type"] != "move":
            continue
        # Never join separate gestures or invent speed at duplicate timestamps.
        if window and not 0 < event["time"] - window[-1]["time"] <= LOCAL_MOVE_MAX_GAP_MS:
            window.clear()
        window.append(event)
        if len(window) > LOCAL_MOVE_WINDOW:
            window.pop(0)
        if len(window) < LOCAL_MOVE_WINDOW:
            continue
        examined += 1
        vectors = [(b["x"] - a["x"], b["y"] - a["y"])
                   for a, b in zip(window, window[1:])]
        lengths = [math.hypot(dx, dy) for dx, dy in vectors]
        path_length = sum(lengths)
        if path_length == 0:
            continue
        speeds = [distance / dt for distance, dt in zip(lengths, _intervals(window))]
        if not all(math.isfinite(speed) for speed in speeds):
            continue
        if max(speeds) == 0:
            continue
        speed_cv = _window_cv(speeds)
        straightness = min(1.0, math.hypot(
            window[-1]["x"] - window[0]["x"],
            window[-1]["y"] - window[0]["y"],
        ) / path_length)
        speed_cvs.append(speed_cv)
        straightnesses.append(straightness)
        regular_lines.append(straightness / (1 + speed_cv))
        # Stationary steps have no direction; a straight line has no turn cadence.
        if all(distance > 0 for distance in lengths):
            turns = [abs(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
                     for (ax, ay), (bx, by) in zip(vectors, vectors[1:])]
            if fmean(turns) > 1e-6:
                turn_cvs.append(_window_cv(turns))
    return {
        "move_window_speed_cv_min": min(speed_cvs, default=None),
        "move_window_speed_cv_median": _median(speed_cvs),
        "move_window_straightness_max": max(straightnesses, default=None),
        "move_window_regular_line_score_max": max(regular_lines, default=None),
        "move_window_turn_cv_min": min(turn_cvs, default=None),
    }, {
        "motion_windows_examined": examined,
        "motion_windows_valid": len(speed_cvs),
        "turn_windows_valid": len(turn_cvs),
    }


def extract_interaction_features(mouse):
    """Missing evidence stays null, and touch is not mixed into mouse timing."""
    mouse = mouse if isinstance(mouse, dict) else {}
    raw = mouse.get("records") or mouse.get("trajectory")
    raw = raw if isinstance(raw, list) else []
    # Reject boolean coordinates/times before the shared numeric-string sanitizer.
    events = sanitize_mouse_records([
        event for event in raw if isinstance(event, dict)
        and not any(isinstance(event.get(key), bool) for key in ("time", "t", "x", "y"))
        and event.get("source") in (None, "mouse", "touch")
        and event.get("type", "move") in ("move", "down", "up", "click")
    ])
    local_features, local_counts = _local_motion_features(events)
    touch_count = sum(event.get("source") == "touch" for event in events)
    events = [event for event in events if event.get("source") != "touch"]
    moves = [event for event in events if event["type"] == "move"]
    clicks = [event for event in events if event["type"] == "click"]
    move_intervals = _intervals(moves)
    click_intervals = _intervals(clicks)
    holds, pre_click_pauses = [], []
    last_move = None
    pending_down = None
    ambiguous_press = False
    for event in events:
        if event["type"] == "move":
            last_move = event
        elif event["type"] == "click" and last_move is not None:
            pre_click_pauses.append(event["time"] - last_move["time"])
        elif event["type"] == "down":
            ambiguous_press = ambiguous_press or pending_down is not None
            pending_down = event
        elif event["type"] == "up":
            if (pending_down is not None and not ambiguous_press
                    and event.get("source") == pending_down.get("source")):
                holds.append(event["time"] - pending_down["time"])
            pending_down = None
            ambiguous_press = False

    scroll = sanitize_scroll_events(mouse.get("scrollEvents"))
    # A zero-delta wheel notification is not a scroll interaction.
    active_scroll = [event for event in scroll if event["deltaX"] or event["deltaY"]]
    scroll_intervals = _intervals(active_scroll)
    vertical = [event["deltaY"] for event in active_scroll if event["deltaY"]]
    features = {
        **local_features,
        "move_interval_median_ms": _median(move_intervals),
        "move_interval_cv": _cv(move_intervals),
        "move_zero_interval_ratio": (
            sum(dt == 0 for dt in move_intervals) / len(move_intervals) if move_intervals else None
        ),
        "click_interval_median_ms": _median(click_intervals),
        "click_interval_cv": _cv(click_intervals),
        "press_duration_median_ms": _median(holds),
        "pre_click_pause_median_ms": _median(pre_click_pauses),
        "scroll_interval_median_ms": _median(scroll_intervals),
        "scroll_interval_cv": _cv(scroll_intervals),
        "scroll_delta_abs_cv": _cv([
            math.hypot(event["deltaX"], event["deltaY"]) for event in active_scroll
        ]),
        "vertical_scroll_reversal_ratio": (
            sum(a * b < 0 for a, b in zip(vertical, vertical[1:])) / (len(vertical) - 1)
            if len(vertical) > 1 else None
        ),
    }
    return {
        "feature_version": INTERACTION_FEATURE_VERSION,
        "mode": "measurement_only",
        "scope": "retained_collector_window",
        "release_approved": False,
        "local_window": {"move_points": LOCAL_MOVE_WINDOW, "max_gap_ms": LOCAL_MOVE_MAX_GAP_MS},
        "features": {key: round(value, 6) if value is not None else None
                     for key, value in features.items()},
        "counts": {
            **local_counts,
            "mouse_events": len(events), "moves": len(moves), "clicks": len(clicks),
            "paired_presses": len(holds), "clicks_with_preceding_move": len(pre_click_pauses),
            "scroll_events": len(active_scroll), "touch_events_excluded": touch_count,
        },
    }
