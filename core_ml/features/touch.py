"""Touch gestures from phones and tablets: sanitising, features, research flags.

Collector 1.7.0 sends single-finger gestures as points
``[ms since touch start, x, y, radiusX, radiusY, force]`` in CSS pixels.
Nothing here changes a verdict: mobile behaviour has no validated human
baseline yet (BeCAPTCHA-Mouse/HuMIdb report ~60% accuracy from touch alone
against unseen bot generators), so the analysis is reported and stored for
training only.

Measured 2026-10-27 with Playwright ``tap`` and CDP ``Input.dispatchTouchEvent``
(Pixel 7 emulation, Chromium): every synthetic contact reports radius 1 and
force 1, a tap's touchstart and touchend share one timestamp, and a CDP swipe
is a perfectly straight line of equal steps. Real fingers report a contact
ellipse of several pixels that changes during the stroke.
"""

import math
import statistics

TOUCH_ANALYSIS_VERSION = "touch_v2"
# Policy 19. Autoclickers tap one point at a fixed rate; macro recorders replay a
# swipe exactly. Measured on BrainRun (2,070 human devices, 283,742 windows of
# 20 gestures; 3 scripted devices in the set removed): no human window has 5 taps
# within 0.5 px of one point with an interval CV under 0.10 (the scripted devices:
# 529 windows); 3 replayed swipes (>= 5 points, >= 30 px, same ends within 0.5 px,
# duration within 3 ms) occur on one human device (6 windows), so replay is a
# risk signal only. Touchalytics (37 people, 377 taps): never 2 taps at one point.
AUTOCLICK_RULE = "autoclick_taps_v1"
AUTOCLICK_MIN_TAPS = 5
AUTOCLICK_MAX_INTERVAL_CV = 0.10
SAME_POINT_PX = 0.5
REPLAY_MIN_SWIPES = 3
REPLAY_MIN_POINTS = 5
REPLAY_MIN_DISPLACEMENT_PX = 30.0
REPLAY_DURATION_MS = 3.0
MAX_GESTURES = 20
MAX_POINTS = 48
TAP_MAX_DISPLACEMENT_PX = 10.0
TAP_MAX_DURATION_MS = 300.0
LINEAR_MIN_POINTS = 5
LINEAR_MAX_DEVIATION_PX = 0.5
EVEN_STEP_MAX_CV = 0.05

# Model input: path shape and overall duration only. Radius and force depend on
# the device (many report none); BrainRun, the public training set, has neither
# and records no per-point times, so per-step timing (and the point count, which
# follows the screen refresh rate) would teach the model its recording artefacts.
MODEL_FEATURES = (
    "duration_ms", "displacement_px", "path_px", "straightness", "mean_speed",
    "step_length_cv", "peak_step_position", "max_deviation_ratio", "rms_deviation_ratio",
    "direction_changes",
)


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or value < low or value > high:
        return None
    return value


def sanitize_gestures(touch) -> list:
    """Bounded, finite gestures; a point without time or position is dropped."""
    touch = touch if isinstance(touch, dict) else {}
    raw = touch.get("gestures")
    raw = raw[-MAX_GESTURES:] if isinstance(raw, list) else []
    gestures = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("points"), list):
            continue
        points = []
        for point in item["points"][:MAX_POINTS]:
            if not isinstance(point, list) or len(point) < 3:
                continue
            dt = _number(point[0], 0, 600_000)
            x = _number(point[1], -100_000, 100_000)
            y = _number(point[2], -100_000, 100_000)
            if dt is None or x is None or y is None or (points and dt < points[-1][0]):
                continue
            extra = list(point[3:6]) + [None] * (6 - len(point[:6]))
            points.append([
                dt, x, y,
                _number(extra[0], 0, 1000), _number(extra[1], 0, 1000), _number(extra[2], 0, 10),
            ])
        if points:
            gestures.append({"t0": _number(item.get("t0"), 0, 10**10), "points": points})
    return gestures


def _cv(values):
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    return statistics.pstdev(values) / mean if mean > 0 else None


def gesture_features(points) -> dict:
    """Shape and timing of one stroke; ``kind`` is tap or swipe."""
    xs = [p[1] for p in points]
    ys = [p[2] for p in points]
    duration = points[-1][0] - points[0][0]
    displacement = math.hypot(xs[-1] - xs[0], ys[-1] - ys[0])
    steps = [(points[i][0] - points[i - 1][0], math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
             for i in range(1, len(points))]
    path = sum(length for _, length in steps)
    timed = [(dt, length) for dt, length in steps if dt > 0]
    speeds = [length / dt for dt, length in timed]
    accels = [abs(speeds[i] - speeds[i - 1]) / timed[i][0] for i in range(1, len(speeds))]
    deviations = []
    if displacement > 0:
        ux, uy = (xs[-1] - xs[0]) / displacement, (ys[-1] - ys[0]) / displacement
        deviations = [abs((x - xs[0]) * uy - (y - ys[0]) * ux) for x, y in zip(xs, ys)]
    angles = [math.atan2(ys[i] - ys[i - 1], xs[i] - xs[i - 1])
              for i in range(1, len(points)) if steps[i - 1][1] > 0.5]
    turns = sum(
        1 for i in range(1, len(angles))
        if abs((angles[i] - angles[i - 1] + math.pi) % (2 * math.pi) - math.pi) > math.pi / 4
    )
    peak = max(speeds) if speeds else 0.0
    moving = [length for _, length in steps if length > 0]
    radii = [r for p in points for r in (p[3], p[4]) if r is not None]
    forces = [p[5] for p in points if p[5] is not None]
    return {
        "kind": "tap" if displacement < TAP_MAX_DISPLACEMENT_PX and duration <= TAP_MAX_DURATION_MS else "swipe",
        "points": len(points),
        "duration_ms": round(duration, 1),
        "displacement_px": round(displacement, 1),
        "path_px": round(path, 1),
        "straightness": round(displacement / path, 4) if path > 0 else None,
        "mean_speed": round(path / duration, 4) if duration > 0 else None,
        "peak_speed": round(peak, 4) if speeds else None,
        "speed_cv": _round(_cv(speeds)),
        "peak_speed_position": round(speeds.index(peak) / max(1, len(speeds) - 1), 3) if speeds else None,
        "mean_abs_accel": _round(statistics.fmean(accels)) if accels else None,
        "max_deviation_ratio": _round(max(deviations) / displacement) if deviations else None,
        "max_deviation_px": round(max(deviations), 2) if deviations else None,
        "rms_deviation_ratio": (
            _round(math.sqrt(statistics.fmean([d * d for d in deviations])) / displacement) if deviations else None
        ),
        "step_interval_cv": _round(_cv([dt for dt, _ in steps])),
        "step_length_cv": _round(_cv(moving)),
        # Touch events arrive once per frame, so the longest step marks peak speed.
        "peak_step_position": (
            round([length for _, length in steps].index(max(moving)) / max(1, len(steps) - 1), 3) if moving else None
        ),
        "direction_changes": turns,
        "radius_mean": _round(statistics.fmean(radii)) if radii else None,
        "radius_spread": round(max(radii) - min(radii), 2) if radii else None,
        "force_mean": _round(statistics.fmean(forces)) if forces else None,
        "force_spread": round(max(forces) - min(forces), 3) if forces else None,
    }


def _round(value, digits=4):
    return round(value, digits) if value is not None else None


def feature_vector(features: dict) -> list:
    """Model input with missing values as 0."""
    return [float(features.get(name) or 0.0) for name in MODEL_FEATURES]


def _synthetic_contact(points) -> bool:
    """CDP/Playwright default contact: radius exactly 1 and force 1 on every point, release included.

    Android input injection (HID devices, replay scripts; Gesture Fingerprint)
    reports pressure 1, no contact area and pressure 0 on release, but so does a
    real low-end Android phone without pressure or size sensors (measured on the
    live site 2026-10-27: Adreno 610, radius 0.3, force 1, release 0). In a
    browser the two cannot be told apart, so only the CDP signature counts.
    """
    return all(p[3] == 1 and p[4] == 1 and p[5] == 1 for p in points)


def _autoclick_group(gestures, features) -> tuple:
    """Largest group of taps at one point, and whether it is metronomic."""
    taps = [(g["t0"], g["points"][0][1], g["points"][0][2])
            for g, f in zip(gestures, features) if f["kind"] == "tap" and g["t0"] is not None]
    largest, metronomic = 0, 0
    for _, x, y in taps:
        times = sorted(t for t, bx, by in taps if abs(bx - x) <= SAME_POINT_PX and abs(by - y) <= SAME_POINT_PX)
        largest = max(largest, len(times))
        gaps = [b - a for a, b in zip(times, times[1:])]
        if len(times) >= AUTOCLICK_MIN_TAPS and min(gaps) > 0:
            mean = statistics.fmean(gaps)
            if statistics.pstdev(gaps) / mean < AUTOCLICK_MAX_INTERVAL_CV:
                metronomic = max(metronomic, len(times))
    return largest, metronomic


def _replayed_swipes(gestures, features) -> int:
    """Largest group of swipes with the same ends and duration."""
    swipes = [g["points"] for g, f in zip(gestures, features)
              if f["kind"] == "swipe" and f["points"] >= REPLAY_MIN_POINTS
              and f["displacement_px"] >= REPLAY_MIN_DISPLACEMENT_PX]
    largest = 0
    for a in swipes:
        same = [b for b in swipes
                if all(abs(b[i][k] - a[i][k]) <= SAME_POINT_PX for i in (0, -1) for k in (1, 2))
                and abs((b[-1][0] - b[0][0]) - (a[-1][0] - a[0][0])) <= REPLAY_DURATION_MS]
        largest = max(largest, len(same))
    return largest


def analyze_touch(touch) -> dict:
    """Summary of a session's touch gestures; flags feed the phone rules of policy 18+."""
    gestures = sanitize_gestures(touch)
    features = [gesture_features(g["points"]) for g in gestures]
    taps = [f for f in features if f["kind"] == "tap"]
    swipes = [f for f in features if f["kind"] == "swipe"]
    zero_time_taps = [f for f in taps if f["duration_ms"] < 1 and f["points"] >= 2]
    linear = [
        f for f in swipes
        if f["points"] >= LINEAR_MIN_POINTS and f["max_deviation_px"] is not None
        and f["max_deviation_px"] <= LINEAR_MAX_DEVIATION_PX
        and f["step_length_cv"] is not None and f["step_length_cv"] <= EVEN_STEP_MAX_CV
    ]
    synthetic_contact = [g for g in gestures if _synthetic_contact(g["points"])]
    same_point_taps, autoclick_taps = _autoclick_group(gestures, features)
    replayed = _replayed_swipes(gestures, features)
    flags = []
    if gestures and len(synthetic_contact) == len(gestures):
        flags.append("SYNTHETIC_CONTACT")
    if len(zero_time_taps) >= 2:
        flags.append("ZERO_TIME_TAPS")
    if len(linear) >= 2:
        flags.append("RULER_SWIPES")
    if autoclick_taps >= AUTOCLICK_MIN_TAPS:
        flags.append("AUTOCLICK_TAPS")
    if replayed >= REPLAY_MIN_SWIPES:
        flags.append("REPLAYED_SWIPES")
    total = touch.get("total") if isinstance(touch, dict) else None
    return {
        "analysis_version": TOUCH_ANALYSIS_VERSION,
        "gestures": len(gestures),
        "gestures_total": int(_number(total, 0, 10**7) or len(gestures)),
        "taps": len(taps),
        "swipes": len(swipes),
        "zero_time_taps": len(zero_time_taps),
        "ruler_swipes": len(linear),
        "synthetic_contact_gestures": len(synthetic_contact),
        "same_point_taps": same_point_taps,
        "autoclick_taps": autoclick_taps,
        "replayed_swipes": replayed,
        "research_flags": flags,
    }
