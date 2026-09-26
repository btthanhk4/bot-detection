"""
Mouse Dynamics Feature Extraction Module (Production-Ready v3)
===============================================================
Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
Single Source of Truth for Mouse Statistical Motion Features.
Features:
  - 14 core kinematic features (speed, accel, jerk, straightness, etc.)
  - 6 discriminative features: curvature, time_regularity, velocity_autocorrelation,
    acceleration_zero_crossing_rate, movement_efficiency
  - Resilient input handling (None-safe, coordinate auto-normalization)
"""

import math
import numpy as np
import torch


MAX_MOUSE_RECORDS = 100
MAX_FEATURE_MAGNITUDE = 1_000_000.0
MAX_RAW_COORDINATE = 100_000.0
MAX_EVENT_TIME = 9_000_000_000_000_000.0


# Single Source of Truth for Mouse Statistical Features
STATISTICAL_FEATURE_NAMES = [
    "mean_speed",
    "std_speed",
    "max_speed",
    "mean_accel",
    "std_accel",
    "straightness",
    "pause_ratio",
    "direction_changes_x",
    "direction_changes_y",
    "jerk_mean",
    "angular_entropy",
    # Discriminative motion features (v2)
    "curvature_mean",
    "curvature_std",
    "time_regularity",
    "velocity_autocorrelation",
    "accel_zero_crossing_rate",
    "movement_efficiency",
    # Behavioral patterns (v2.1)
    "click_to_move_ratio",
    "speed_skewness",
    "idle_time_ratio",
]


def _get_empty_stats(point_count: int = 0, move_count: int = 0) -> dict:
    stats = {k: 0.0 for k in STATISTICAL_FEATURE_NAMES}
    stats.update({
        "point_count": point_count,
        "move_point_count": move_count,
        "duration_ms": 0.0,
        "straightness": 1.0,
        "max_accel": 0.0,
    })
    return stats


def sanitize_mouse_records(records: list, max_records: int = MAX_MOUSE_RECORDS) -> list:
    """Return finite, chronological mouse events with a bounded size."""
    if not isinstance(records, list):
        return []

    valid_records = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        raw_time = record.get("time", record.get("t"))
        if record.get("x") is None or record.get("y") is None or raw_time is None:
            continue
        try:
            numeric_time = float(raw_time)
            numeric_x = float(record["x"])
            numeric_y = float(record["y"])
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(value) for value in (numeric_time, numeric_x, numeric_y)):
            continue
        if (
            numeric_time < 0
            or numeric_time > MAX_EVENT_TIME
            or abs(numeric_x) > MAX_RAW_COORDINATE
            or abs(numeric_y) > MAX_RAW_COORDINATE
        ):
            continue
        sanitized = {
            "time": numeric_time,
            "x": numeric_x,
            "y": numeric_y,
            "type": str(record.get("type", "move")),
            "_input_order": index,
        }
        if record.get("source") in ("mouse", "touch"):
            sanitized["source"] = record["source"]
        valid_records.append(sanitized)

    valid_records.sort(key=lambda record: (record["time"], record["_input_order"]))
    if max_records > 0:
        valid_records = valid_records[-max_records:]
    for record in valid_records:
        record.pop("_input_order", None)
    return valid_records


def prefix_through_moves(records: list, max_move_points: int) -> list:
    """Keep events through the Nth move to audit early-session decisions."""
    if type(max_move_points) is not int or max_move_points < 1:
        raise ValueError("max_move_points must be a positive integer")
    prefix = []
    moves = 0
    for record in records:
        prefix.append(record)
        if isinstance(record, dict) and record.get("type") == "move":
            moves += 1
            if moves == max_move_points:
                break
    return prefix


def compute_statistical_features(records: list) -> dict:
    """
    Extract comprehensive statistical motion features from a list of mouse points.
    Each record: {'time': int|float, 'x': float, 'y': float, 'type': str, ...}
    Returns dict with 20 features (STATISTICAL_FEATURE_NAMES) plus point_count metadata.
    Auto-normalizes coordinates if raw pixel coordinates (> 1.0) are detected.
    """
    if not records or not isinstance(records, list):
        return _get_empty_stats()

    # Validate before capping so trailing garbage cannot hide valid movement.
    valid_records = sanitize_mouse_records(records, max_records=MAX_MOUSE_RECORDS)

    if not valid_records:
        return _get_empty_stats(point_count=len(valid_records))

    move_records = [r for r in valid_records if r["type"] == "move"]
    if len(move_records) < 3:
        return _get_empty_stats(point_count=len(valid_records), move_count=len(move_records))

    times = [r["time"] for r in move_records]
    xs = [r["x"] for r in move_records]
    ys = [r["y"] for r in move_records]

    # Coordinate auto-normalization:
    # If coordinates are in pixel space (> 1.0), normalize to [0, 1] screen coordinates
    max_abs_x = max((abs(x) for x in xs), default=1.0)
    max_abs_y = max((abs(y) for y in ys), default=1.0)
    scale_w = max(1920.0, max_abs_x) if max_abs_x > 1.0 else 1.0
    scale_h = max(1080.0, max_abs_y) if max_abs_y > 1.0 else 1.0
    xs = [max(0.0, min(1.0, x / scale_w)) for x in xs]
    ys = [max(0.0, min(1.0, y / scale_h)) for y in ys]

    duration = max(1.0, float(times[-1] - times[0]))

    # Compute differential elements
    dxs, dys, dts = [], [], []
    speeds, accels = [], []
    angles = []
    moving_segments = []

    for i in range(1, len(move_records)):
        dt = max(0.001, (times[i] - times[i - 1]) / 1000.0)  # in seconds
        dx = xs[i] - xs[i - 1]
        dy = ys[i] - ys[i - 1]
        dist = math.sqrt(dx * dx + dy * dy)
        speed = dist / dt

        dxs.append(dx)
        dys.append(dy)
        dts.append(dt)
        speeds.append(speed)

        if dist > 1e-6:
            angle = math.atan2(dy, dx)
            angles.append(angle)
            moving_segments.append((angle, dist))

    for i in range(1, len(speeds)):
        dt = dts[i]
        accel = abs(speeds[i] - speeds[i - 1]) / dt
        accels.append(accel)

    speeds_arr = np.array(speeds, dtype=np.float32)
    accels_arr = np.array(accels, dtype=np.float32) if accels else np.zeros(1, dtype=np.float32)

    # Net displacement vs total distance
    net_dist = math.sqrt((xs[-1] - xs[0]) ** 2 + (ys[-1] - ys[0]) ** 2)
    total_dist = sum(math.sqrt(dx * dx + dy * dy) for dx, dy in zip(dxs, dys))
    straightness = float(net_dist / total_dist) if total_dist > 1e-6 else 1.0

    # Pause ratio (fraction of movements with near zero speed)
    pause_count = sum(1 for s in speeds if s < 0.01)
    pause_ratio = float(pause_count / len(speeds)) if speeds else 0.0

    # Direction changes (zero crossings in dx and dy)
    dir_changes_x = sum(1 for i in range(1, len(dxs)) if dxs[i] * dxs[i - 1] < 0)
    dir_changes_y = sum(1 for i in range(1, len(dys)) if dys[i] * dys[i - 1] < 0)

    # Jerk (rate of change of acceleration)
    jerks = [abs(accels[i] - accels[i - 1]) / dts[i + 1] for i in range(1, len(accels)) if i + 1 < len(dts)] if len(accels) > 1 else [0.0]
    jerk_mean = float(np.mean(jerks)) if jerks else 0.0

    # Angular entropy (humans have varied curvature; simple bots move in straight lines/grid)
    if len(angles) > 4:
        hist, _ = np.histogram(angles, bins=8, range=(-math.pi, math.pi))
        prob = hist / (np.sum(hist) + 1e-9)
        entropy = -sum(p * math.log2(p + 1e-9) for p in prob if p > 0)
    else:
        entropy = 0.0

    # ========== NEW FEATURES ==========

    # 1. Curvature: angle change / distance at each point (3-point formula)
    curvatures = []
    for i in range(1, len(moving_segments)):
        angle, seg_dist = moving_segments[i]
        previous_angle, _ = moving_segments[i - 1]
        angle_diff = abs(angle - previous_angle)
        if angle_diff > math.pi:
            angle_diff = 2 * math.pi - angle_diff
        curvature = angle_diff / (seg_dist + 1e-6)
        curvatures.append(curvature)

    curvature_mean = float(np.mean(curvatures)) if curvatures else 0.0
    curvature_std = float(np.std(curvatures)) if curvatures else 0.0

    # 2. Time regularity: std(dt)/mean(dt) — bots have very regular timing
    dts_ms = [(times[i] - times[i-1]) for i in range(1, len(times))]
    dts_ms = [d for d in dts_ms if d > 0]
    if dts_ms and np.mean(dts_ms) > 0:
        time_regularity = float(np.std(dts_ms) / (np.mean(dts_ms) + 1e-9))
    else:
        time_regularity = 0.0

    # 3. Velocity autocorrelation (lag-1): bots tend to have autocorr ≈ 1.0
    if len(speeds) > 2:
        s_mean = float(np.mean(speeds_arr))
        s_std = float(np.std(speeds_arr))
        if s_std > 1e-6:
            autocov = float(np.mean((speeds_arr[:-1] - s_mean) * (speeds_arr[1:] - s_mean)))
            velocity_autocorrelation = float(autocov / (s_std**2))
        else:
            velocity_autocorrelation = 1.0  # constant speed → perfect autocorrelation
    else:
        velocity_autocorrelation = 0.0

    # 4. Acceleration zero-crossing rate: how often acceleration changes sign
    if len(accels) > 1:
        accel_signs = np.sign(np.diff(speeds_arr))
        zero_crossings = sum(1 for i in range(1, len(accel_signs)) if accel_signs[i] * accel_signs[i-1] < 0)
        accel_zero_crossing_rate = float(zero_crossings / (len(accel_signs) + 1e-9))
    else:
        accel_zero_crossing_rate = 0.0

    # 5. Movement efficiency: combines spatial efficiency with temporal efficiency
    active_time = sum(dt for dt, s in zip(dts, speeds) if s > 0.01)
    if total_dist > 1e-6 and active_time > 0:
        spatial_eff = net_dist / total_dist
        temporal_eff = active_time / (sum(dts) + 1e-9)
        movement_efficiency = float(spatial_eff * temporal_eff)
    else:
        movement_efficiency = 0.0

    # 6. Click-to-move ratio: bots click frequently relative to movement
    click_count = sum(1 for r in valid_records if r.get("type") == "click")
    move_count = len(move_records)
    click_to_move_ratio = float(click_count / (move_count + 1e-9))

    # 7. Speed distribution skewness: humans have right-skewed speed (many slow, few fast)
    if len(speeds) > 3:
        s_mean = float(np.mean(speeds_arr))
        s_std = float(np.std(speeds_arr))
        if s_std > 1e-6:
            speed_skewness = float(np.mean(((speeds_arr - s_mean) / s_std) ** 3))
        else:
            speed_skewness = 0.0
    else:
        speed_skewness = 0.0

    # 8. Idle time ratio: fraction of session spent idle (no movement > 500ms)
    idle_threshold_s = 0.5  # 500ms
    idle_time = sum(dt for dt in dts if dt > idle_threshold_s)
    total_time = sum(dts) if dts else 1e-9
    idle_time_ratio = float(idle_time / (total_time + 1e-9))

    stats = {
        "point_count": len(valid_records),
        "move_point_count": len(move_records),
        "duration_ms": duration,
        "mean_speed": float(np.mean(speeds_arr)),
        "std_speed": float(np.std(speeds_arr)),
        "max_speed": float(np.max(speeds_arr)),
        "mean_accel": float(np.mean(accels_arr)),
        "std_accel": float(np.std(accels_arr)),
        "max_accel": float(np.max(accels_arr)),
        "straightness": straightness,
        "pause_ratio": pause_ratio,
        "direction_changes_x": dir_changes_x,
        "direction_changes_y": dir_changes_y,
        "jerk_mean": jerk_mean,
        "angular_entropy": float(entropy),
        # Discriminative motion features (v2)
        "curvature_mean": curvature_mean,
        "curvature_std": curvature_std,
        "time_regularity": time_regularity,
        "velocity_autocorrelation": velocity_autocorrelation,
        "accel_zero_crossing_rate": accel_zero_crossing_rate,
        "movement_efficiency": movement_efficiency,
        # Behavioral patterns (v2.1)
        "click_to_move_ratio": click_to_move_ratio,
        "speed_skewness": speed_skewness,
        "idle_time_ratio": idle_time_ratio,
    }
    for key, value in stats.items():
        if key in ("point_count", "move_point_count"):
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            numeric = 0.0
        stats[key] = max(-MAX_FEATURE_MAGNITUDE, min(MAX_FEATURE_MAGNITUDE, numeric))
    return stats


def records_to_chunks(records: list, chunk_size: int = 24, stride: int = 12) -> list:
    """Build canonical LSTM transition windows from server-validated move events."""
    if chunk_size <= 0 or stride <= 0:
        return []

    moves = [
        record for record in sanitize_mouse_records(records, max_records=MAX_MOUSE_RECORDS)
        if record["type"] == "move"
    ]
    if len(moves) < chunk_size + 1:
        return []

    max_abs_x = max(abs(record["x"]) for record in moves)
    max_abs_y = max(abs(record["y"]) for record in moves)
    scale_w = max(1920.0, max_abs_x) if max_abs_x > 1.0 else 1.0
    scale_h = max(1080.0, max_abs_y) if max_abs_y > 1.0 else 1.0

    feature_rows = []
    prev_speed_x = 0.0
    prev_speed_y = 0.0
    for previous, current in zip(moves, moves[1:]):
        dt = max(0.001, (current["time"] - previous["time"]) / 1000.0)
        previous_x = max(0.0, min(1.0, previous["x"] / scale_w))
        previous_y = max(0.0, min(1.0, previous["y"] / scale_h))
        current_x = max(0.0, min(1.0, current["x"] / scale_w))
        current_y = max(0.0, min(1.0, current["y"] / scale_h))
        dx = current_x - previous_x
        dy = current_y - previous_y
        distance = math.sqrt(dx * dx + dy * dy)
        speed_x = dx / dt
        speed_y = dy / dt
        speed = distance / dt
        acceleration = math.sqrt(
            (speed_x - prev_speed_x) ** 2 + (speed_y - prev_speed_y) ** 2
        ) / dt
        feature_rows.append([
            max(-MAX_FEATURE_MAGNITUDE, min(MAX_FEATURE_MAGNITUDE, value))
            for value in (dx, dy, speed_x, speed_y, speed, acceleration, distance, dt)
        ])
        prev_speed_x = speed_x
        prev_speed_y = speed_y

    return [
        feature_rows[start:start + chunk_size]
        for start in range(0, len(feature_rows) - chunk_size + 1, stride)
    ]


def extract_mouse_stat_vector(records_or_stats) -> np.ndarray:
    """
    Extract ordered float32 feature vector of length 20 from raw records or stats dict.
    Guarantees consistent feature ordering across all models and modules.
    Safe against None, NaN, and Inf.
    """
    if records_or_stats is None:
        return np.zeros(len(STATISTICAL_FEATURE_NAMES), dtype=np.float32)
    if isinstance(records_or_stats, list):
        stats = compute_statistical_features(records_or_stats)
    elif isinstance(records_or_stats, dict):
        stats = records_or_stats
    else:
        return np.zeros(len(STATISTICAL_FEATURE_NAMES), dtype=np.float32)

    vec = []
    for k in STATISTICAL_FEATURE_NAMES:
        val = stats.get(k, 0.0)
        try:
            numeric = float(val)
        except (TypeError, ValueError, OverflowError):
            vec.append(0.0)
            continue
        vec.append(numeric if math.isfinite(numeric) else 0.0)
    return np.array(vec, dtype=np.float32)


def extract_sequential_chunks(chunks: list, chunk_size: int = 24, n_features: int = 8) -> torch.Tensor:
    """
    Converts raw chunk arrays into PyTorch float tensor of shape (batch_size, seq_len=24, n_features=8).
    Features per point: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
    Resilient to malformed rows, non-numeric values, None entries, and irregular lengths.
    """
    if not chunks or not isinstance(chunks, list):
        return torch.zeros((0, chunk_size, n_features), dtype=torch.float32)

    # Defensive cap to prevent GPU/RAM memory exhaustion
    if len(chunks) > 50:
        chunks = chunks[-50:]

    valid_chunks = []
    for c in chunks:
        if not isinstance(c, (list, tuple)) or len(c) != chunk_size:
            continue
        cleaned_rows = []
        chunk_is_valid = True
        for row in c:
            if not isinstance(row, (list, tuple)) or len(row) != n_features:
                chunk_is_valid = False
                break
            cleaned_row = []
            for val in row:
                try:
                    fval = float(val)
                except (ValueError, TypeError, OverflowError):
                    chunk_is_valid = False
                    break
                if not math.isfinite(fval):
                    chunk_is_valid = False
                    break
                cleaned_row.append(fval)
            if not chunk_is_valid:
                break
            cleaned_rows.append(cleaned_row)

        if chunk_is_valid:
            valid_chunks.append(cleaned_rows)

    if not valid_chunks:
        return torch.zeros((0, chunk_size, n_features), dtype=torch.float32)

    tensor = torch.tensor(valid_chunks, dtype=torch.float32)
    tensor = torch.clamp(tensor, -100.0, 100.0)
    return tensor
