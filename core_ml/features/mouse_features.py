"""
Mouse Dynamics Feature Extraction Module
Inspired by DELBOT-Mouse (https://github.com/chrisgdt/DELBOT-Mouse)
Provides both sequential tensor extraction for LSTM and statistical summary features for tabular classifiers.
"""

import math
import numpy as np
import torch


def compute_statistical_features(records: list) -> dict:
    """
    Extract comprehensive statistical motion features from a list of mouse points.
    Each record: {'time': int, 'x': float, 'y': float, 'type': str, ...}
    """
    if not records or len(records) < 3:
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
        }

    times = [r.get("time", 0) for r in records]
    xs = [r.get("x", 0.0) for r in records]
    ys = [r.get("y", 0.0) for r in records]

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
            valid_chunks.append(c)
        elif len(c) > chunk_size:
            valid_chunks.append(c[:chunk_size])
        else:
            # Pad with zeros if shorter
            padded = list(c) + [[0.0] * n_features] * (chunk_size - len(c))
            valid_chunks.append(padded)

    tensor = torch.tensor(valid_chunks, dtype=torch.float32)
    # Clip extreme values for numerical stability
    tensor = torch.clamp(tensor, -100.0, 100.0)
    return tensor
