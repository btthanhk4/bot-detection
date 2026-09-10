"""
Mouse Dynamics Feature Extraction Module (Optimized v2)
=======================================================
Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
Added 6 new discriminative features:
  - curvature_mean/std, time_regularity, velocity_autocorrelation,
    acceleration_zero_crossing_rate, movement_efficiency
"""

import math
import numpy as np
import torch


def compute_statistical_features(records: list) -> dict:
    """
    Extract comprehensive statistical motion features from a list of mouse points.
    Each record: {'time': int, 'x': float, 'y': float, 'type': str, ...}
    Returns dict with 20 features (14 original + 6 new).
    """
    # Filter to move events only — click/scroll events at same position
    # create artificial speed=0 entries that corrupt kinematic features
    move_records = [r for r in records if r.get("type", "move") == "move"]

    if not move_records or len(move_records) < 3:
        return {
            "point_count": len(records),
            "duration_ms": 0.0,
            "mean_speed": 0.0,
            "std_speed": 0.0,
            "max_speed": 0.0,
            "mean_accel": 0.0,
            "std_accel": 0.0,
            "max_accel": 0.0,
            "straightness": 1.0,
            "pause_ratio": 0.0,
            "direction_changes_x": 0,
            "direction_changes_y": 0,
            "jerk_mean": 0.0,
            "angular_entropy": 0.0,
            # New features
            "curvature_mean": 0.0,
            "curvature_std": 0.0,
            "time_regularity": 0.0,
            "velocity_autocorrelation": 0.0,
            "accel_zero_crossing_rate": 0.0,
            "movement_efficiency": 0.0,
            # Additional discriminative features (v2.1)
            "click_to_move_ratio": 0.0,
            "speed_skewness": 0.0,
            "idle_time_ratio": 0.0,
        }

    times = [r.get("time", 0) for r in move_records]
    xs = [r.get("x", 0.0) for r in move_records]
    ys = [r.get("y", 0.0) for r in move_records]

    duration = max(1.0, float(times[-1] - times[0]))

    # Compute differential elements
    dxs, dys, dts = [], [], []
    speeds, accels = [], []
    angles = []

    for i in range(1, len(records)):
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
            angles.append(math.atan2(dy, dx))

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
    jerks = [abs(accels[i] - accels[i - 1]) / dts[i] for i in range(1, len(accels))] if len(accels) > 1 else [0.0]
    jerk_mean = float(np.mean(jerks))

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
    for i in range(1, len(angles)):
        angle_diff = abs(angles[i] - angles[i - 1])
        if angle_diff > math.pi:
            angle_diff = 2 * math.pi - angle_diff
        # Normalize by segment length
        seg_dist = math.sqrt(dxs[i]**2 + dys[i]**2) if i < len(dxs) else 1e-6
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
        s_mean = np.mean(speeds_arr)
        s_std = np.std(speeds_arr)
        if s_std > 1e-6:
            autocov = np.mean((speeds_arr[:-1] - s_mean) * (speeds_arr[1:] - s_mean))
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
    click_count = sum(1 for r in records if r.get("type") == "click")
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

    return {
        "point_count": len(records),
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
        # New features
        "curvature_mean": curvature_mean,
        "curvature_std": curvature_std,
        "time_regularity": time_regularity,
        "velocity_autocorrelation": velocity_autocorrelation,
        "accel_zero_crossing_rate": accel_zero_crossing_rate,
        "movement_efficiency": movement_efficiency,
        # Additional discriminative features (v2.1)
        "click_to_move_ratio": click_to_move_ratio,
        "speed_skewness": speed_skewness,
        "idle_time_ratio": idle_time_ratio,
    }


def extract_sequential_chunks(chunks: list, chunk_size: int = 24, n_features: int = 8) -> torch.Tensor:
    """
    Converts raw chunk arrays (from collector) into PyTorch float tensor of shape (batch_size, seq_len=24, n_features=8).
    Features per point: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
    """
    if not chunks:
        # Return dummy empty tensor
        return torch.zeros((0, chunk_size, n_features), dtype=torch.float32)

    valid_chunks = []
    for c in chunks:
        if len(c) == chunk_size:
            # Verify feature dimension
            row_len = len(c[0]) if c and isinstance(c[0], (list, tuple)) else 0
            if row_len >= n_features:
                # Truncate extra features if needed
                valid_chunks.append([row[:n_features] for row in c])
            elif row_len > 0:
                # Pad features with 0
                valid_chunks.append([list(row) + [0.0] * (n_features - row_len) for row in c])
            else:
                valid_chunks.append(c)
        elif len(c) > chunk_size:
            valid_chunks.append(c[:chunk_size])
        else:
            # Pad with zeros if shorter
            padded = list(c) + [[0.0] * n_features] * (chunk_size - len(c))
            valid_chunks.append(padded)

    if not valid_chunks:
        return torch.zeros((0, chunk_size, n_features), dtype=torch.float32)

    tensor = torch.tensor(valid_chunks, dtype=torch.float32)
    # Clip extreme values for numerical stability
    tensor = torch.clamp(tensor, -100.0, 100.0)
    return tensor
