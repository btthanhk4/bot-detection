"""
Dataset Loader & Synthetic Telemetry Generator (Optimized v2)
=============================================================
- Loads REAL mouse trajectories from web_bot_detection_dataset (phase1/phase2)
- Parses the [m(x,y)][c(l)] notation format into structured records
- Provides advanced synthetic generator with Bézier bot evasion patterns
- Sliding window chunking for LSTM input preparation
"""

import json
import math
import os
import random
import re
import numpy as np


# ---------- Real Dataset Parser ----------

def parse_movement_notation(notation: str) -> list:
    """
    Parses the web_bot_detection_dataset movement notation format:
    [m(x,y)] = mouse move, [c(l)] = click left, [c(r)] = click right,
    [s(n)] = scroll by n ticks.
    Returns list of dicts: {time, x, y, type}
    """
    pattern = re.compile(r'\[([a-z]+)\(([^)]*)\)\]')
    matches = pattern.findall(notation)

    records = []
    t = 0
    last_x, last_y = 0.0, 0.0

    for action, args in matches:
        if action == 'm':
            parts = args.split(',')
            if len(parts) == 2:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                except ValueError:
                    continue

                # Deterministic timestamp estimation based on distance
                # (Fitts's law-inspired: larger movements take more time)
                if records:
                    dx = x - last_x
                    dy = y - last_y
                    dist = math.sqrt(dx * dx + dy * dy)
                    # Fixed base interval ~12ms (83Hz), scaled by distance
                    base_dt = 12.0
                    dist_factor = min(dist / 50.0, 5.0)  # cap at 5x
                    dt = base_dt * (1.0 + dist_factor * 0.5)
                    t += max(1, int(dt))

                records.append({
                    "time": t,
                    "x": x,
                    "y": y,
                    "type": "move"
                })
                last_x, last_y = x, y

        elif action == 'c':
            t += random.randint(50, 150)
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "click"
            })

        elif action == 's':
            t += random.randint(20, 80)
            # Scroll events don't change position
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "scroll"
            })

    return records


def load_real_dataset(dataset_root: str, scenario: str = "humans_and_moderate_bots"):
    """
    Loads real mouse movement sessions from web_bot_detection_dataset.
    Loads BOTH Phase 1 and Phase 2 data for maximum coverage.
    
    Args:
        dataset_root: Path to web_bot_detection_dataset (e.g., Tuần 3/repos/web_bot_detection_dataset)
        scenario: "humans_and_moderate_bots" or "humans_and_advanced_bots"
    
    Returns:
        list of (records, label) tuples, where label is 0 (human) or 1 (bot)
    """
    sessions = []

    # Load from both Phase 1 and Phase 2
    for phase in ["phase1", "phase2"]:
        phase_data = os.path.join(dataset_root, phase, "data", "mouse_movements", scenario)
        phase_ann_train = os.path.join(dataset_root, phase, "annotations", scenario, "train")
        phase_ann_test = os.path.join(dataset_root, phase, "annotations", scenario, "test")

        # Parse annotation files
        label_map = {}
        for ann_file in [phase_ann_train, phase_ann_test]:
            if os.path.isfile(ann_file):
                with open(ann_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) == 2:
                            session_id, label_str = parts
                            if label_str == "human":
                                label_map[session_id] = 0
                            else:
                                label_map[session_id] = 1  # moderate_bot, advanced_bot
            elif os.path.isdir(ann_file):
                # Handle case where annotation path is a directory
                for fname in os.listdir(ann_file):
                    fpath = os.path.join(ann_file, fname)
                    if os.path.isfile(fpath):
                        with open(fpath, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                parts = line.split()
                                if len(parts) == 2:
                                    session_id, label_str = parts
                                    label_map[session_id] = 0 if label_str == "human" else 1

        # Load sessions from this phase
        if os.path.isdir(phase_data):
            for session_id in os.listdir(phase_data):
                session_dir = os.path.join(phase_data, session_id)
                if not os.path.isdir(session_dir):
                    continue

                json_path = os.path.join(session_dir, "mouse_movements.json")
                if not os.path.exists(json_path):
                    continue

                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    notation = data.get("total_behaviour", "")
                    if not notation:
                        continue

                    records = parse_movement_notation(notation)
                    if len(records) < 10:
                        continue

                    label = label_map.get(session_id, -1)
                    if label == -1:
                        continue  # skip sessions without known labels

                    sessions.append((records, label))
                except (json.JSONDecodeError, Exception):
                    continue

    return sessions


def records_to_chunks(records: list, chunk_size: int = 24, stride: int = 12, n_features: int = 8) -> list:
    """
    Convert raw mouse records into LSTM-ready chunks using sliding window.
    Features: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
    """
    # Filter to moves only with positive time diff
    moves = [r for r in records if r.get("type") == "move"]
    if len(moves) < chunk_size + 1:
        return []

    # Normalize coordinates to [0, 1] based on observed range
    xs = [r["x"] for r in moves]
    ys = [r["y"] for r in moves]
    x_range = max(xs) - min(xs) if max(xs) > min(xs) else 1.0
    y_range = max(ys) - min(ys) if max(ys) > min(ys) else 1.0
    x_min, y_min = min(xs), min(ys)

    # Compute kinematic features
    feature_rows = []
    prev_speed_x, prev_speed_y = 0.0, 0.0
    for i in range(1, len(moves)):
        dt = max(1, moves[i]["time"] - moves[i-1]["time"]) / 1000.0  # seconds
        dx = (moves[i]["x"] - moves[i-1]["x"]) / x_range
        dy = (moves[i]["y"] - moves[i-1]["y"]) / y_range
        dist = math.sqrt(dx * dx + dy * dy)
        speed_x = dx / dt
        speed_y = dy / dt
        speed = dist / dt
        accel = math.sqrt((speed_x - prev_speed_x)**2 + (speed_y - prev_speed_y)**2) / dt

        feature_rows.append([dx, dy, speed_x, speed_y, speed, accel, dist, dt])
        prev_speed_x, prev_speed_y = speed_x, speed_y

    # Sliding window chunking
    chunks = []
    for start in range(0, len(feature_rows) - chunk_size + 1, stride):
        chunk = feature_rows[start:start + chunk_size]
        if len(chunk) == chunk_size:
            chunks.append(chunk)

    return chunks


# ---------- Improved Synthetic Generators ----------

def generate_synthetic_human_trajectory(n_points: int = 40) -> list:
    """Generates realistic human mouse movement using smooth curves, pauses, and natural jitter."""
    records = []
    t = 0
    x = random.uniform(0.1, 0.4)
    y = random.uniform(0.1, 0.4)
    target_x = random.uniform(0.6, 0.9)
    target_y = random.uniform(0.6, 0.9)

    # Add random intermediate control point for curved path
    ctrl_x = random.gauss((x + target_x) / 2, 0.15)
    ctrl_y = random.gauss((y + target_y) / 2, 0.15)

    records.append({"time": t, "x": round(x, 4), "y": round(y, 4), "type": "move"})

    for i in range(1, n_points):
        progress = i / float(n_points)
        # Ease-in ease-out with Bézier curve (quadratic)
        smooth_p = 3 * (progress ** 2) - 2 * (progress ** 3)

        # Quadratic Bézier interpolation for curved trajectory
        bx = (1 - smooth_p)**2 * x + 2 * (1 - smooth_p) * smooth_p * ctrl_x + smooth_p**2 * target_x
        by = (1 - smooth_p)**2 * y + 2 * (1 - smooth_p) * smooth_p * ctrl_y + smooth_p**2 * target_y

        # Variable human intervals (12-45ms) with occasional micro-pauses
        dt = random.randint(12, 35)
        if random.random() < 0.08:  # 8% chance of micro-pause
            dt += random.randint(50, 200)
        t += dt

        # Natural jitter (motor noise)
        cur_x = bx + random.gauss(0, 0.003)
        cur_y = by + random.gauss(0, 0.003)

        records.append({
            "time": t,
            "x": round(max(0.0, min(1.0, cur_x)), 4),
            "y": round(max(0.0, min(1.0, cur_y)), 4),
            "type": "move",
        })

    # Occasional overshoot and correction (very human behavior)
    if random.random() < 0.4:
        overshoot_x = target_x + random.gauss(0, 0.02)
        overshoot_y = target_y + random.gauss(0, 0.02)
        t += random.randint(15, 30)
        records.append({"time": t, "x": round(overshoot_x, 4), "y": round(overshoot_y, 4), "type": "move"})
        t += random.randint(20, 50)
        records.append({"time": t, "x": round(target_x, 4), "y": round(target_y, 4), "type": "move"})

    # Click after natural dwell time
    records.append({"time": t + random.randint(80, 300), "x": records[-1]["x"], "y": records[-1]["y"], "type": "click"})
    return records


def generate_synthetic_bot_trajectory(bot_type: str = "linear", n_points: int = 25) -> list:
    """
    Generates various bot trajectory patterns:
    - linear: constant speed straight line
    - instant: teleportation to target
    - grid: discrete grid-snapped steps
    - bezier: sophisticated bot using Bézier curves (evasion technique)
    """
    records = []
    t = 0
    x = random.uniform(0.1, 0.3)
    y = random.uniform(0.1, 0.3)
    target_x = random.uniform(0.7, 0.9)
    target_y = random.uniform(0.7, 0.9)

    records.append({"time": t, "x": round(x, 4), "y": round(y, 4), "type": "move"})

    if bot_type == "instant":
        t += random.randint(5, 15)
        records.append({"time": t, "x": round(target_x, 4), "y": round(target_y, 4), "type": "move"})
        t += random.randint(5, 15)
        records.append({"time": t, "x": round(target_x, 4), "y": round(target_y, 4), "type": "click"})
        return records

    elif bot_type == "grid":
        # Grid-snapped movement (pixel-perfect steps)
        step_x = (target_x - x) / n_points
        step_y = (target_y - y) / n_points
        for i in range(1, n_points):
            t += 16  # constant 60fps
            # Snap to grid (round to nearest 0.01)
            cur_x = round(x + step_x * i, 2)
            cur_y = round(y + step_y * i, 2)
            records.append({"time": t, "x": cur_x, "y": cur_y, "type": "move"})

    elif bot_type == "bezier":
        # Sophisticated bot: uses Bézier but with too-perfect timing and no jitter
        ctrl_x = (x + target_x) / 2 + random.uniform(-0.1, 0.1)
        ctrl_y = (y + target_y) / 2 + random.uniform(-0.1, 0.1)
        for i in range(1, n_points):
            progress = i / float(n_points)
            # Bot uses smooth interpolation but with very regular intervals
            dt = random.randint(14, 18)  # near-constant intervals
            t += dt
            bx = (1 - progress)**2 * x + 2 * (1 - progress) * progress * ctrl_x + progress**2 * target_x
            by = (1 - progress)**2 * y + 2 * (1 - progress) * progress * ctrl_y + progress**2 * target_y
            # Very slight noise (too small compared to human)
            bx += random.gauss(0, 0.0005)
            by += random.gauss(0, 0.0005)
            records.append({"time": t, "x": round(bx, 4), "y": round(by, 4), "type": "move"})

    else:  # linear
        for i in range(1, n_points):
            progress = i / float(n_points)
            # Slight variability in dt (but still too regular vs humans)
            dt = random.randint(14, 18)
            t += dt
            cur_x = x + (target_x - x) * progress
            cur_y = y + (target_y - y) * progress
            records.append({"time": t, "x": round(cur_x, 4), "y": round(cur_y, 4), "type": "move"})

    records.append({"time": t + random.randint(5, 20), "x": round(target_x, 4), "y": round(target_y, 4), "type": "click"})
    return records


def generate_synthetic_telemetry(is_bot: bool = False, bot_level: str = "moderate") -> dict:
    """
    Creates a full realistic telemetry payload for training & testing.
    """
    session_id = f"sess_{random.randint(100000, 999999)}"
    visitor_id = f"fp_{random.randint(1000, 9999)}"

    if not is_bot:
        records = generate_synthetic_human_trajectory(n_points=random.randint(30, 60))
        fp = {
            "userAgent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
            ]),
            "platform": random.choice(["Win32", "MacIntel"]),
            "language": random.choice(["vi-VN", "en-US", "ja"]),
            "languages": random.choice([["vi-VN", "vi", "en-US", "en"], ["en-US", "en"], ["ja", "en-US", "en"]]),
            "hardwareConcurrency": random.choice([4, 8, 12, 16]),
            "deviceMemory": random.choice([8, 16, 32]),
            "maxTouchPoints": 0,
            "screenResolution": random.choice(["1920x1080", "1536x864", "2560x1440", "1366x768"]),
            "colorDepth": 24,
            "pixelRatio": random.choice([1.0, 1.25, 1.5, 2.0]),
            "pluginsLength": random.randint(3, 5),
            "webglVendor": "Google Inc. (NVIDIA)",
            "webglRenderer": random.choice([
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            ]),
            "canvasHash": f"a{random.randint(1000,9999)}",
            "audioHash": f"35.{random.randint(10000,99999)}",
            "fontsCount": random.randint(25, 45),
        }
        botd = {
            "isBot": False,
            "heuristicScore": 0.0,
            "flaggedCount": 0,
            "detectors": {
                "webdriver": False, "distinctiveProperties": False, "virtualGpu": False,
                "pluginsInconsistency": False, "languagesInconsistency": False,
                "windowSize": False, "errorTrace": False, "hasProcess": False,
                "platformMismatch": False, "headlessUa": False,
            },
            "reasons": [],
        }
    else:
        # Bot variants
        if bot_level == "naive":
            records = generate_synthetic_bot_trajectory(bot_type="instant")
            botd_flags = {"webdriver": True, "pluginsInconsistency": True, "virtualGpu": True, "headlessUa": True}
        elif bot_level == "moderate":
            records = generate_synthetic_bot_trajectory(bot_type=random.choice(["linear", "grid"]), n_points=random.randint(20, 30))
            botd_flags = {
                "webdriver": random.choice([True, False]),
                "pluginsInconsistency": True,
                "virtualGpu": random.choice([True, False]),
            }
        else:
            # Advanced bot — uses Bézier + tries to hide fingerprint
            records = generate_synthetic_bot_trajectory(bot_type="bezier", n_points=random.randint(25, 40))
            botd_flags = {"platformMismatch": random.choice([True, False])}

        flagged_count = sum(1 for v in botd_flags.values() if v)
        h_score = round(flagged_count / 10.0, 2)

        fp = {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "platform": "Win32" if not botd_flags.get("platformMismatch") else "Linux x86_64",
            "language": "en-US",
            "languages": ["en-US"],
            "hardwareConcurrency": 2 if botd_flags.get("virtualGpu") else 4,
            "deviceMemory": 2 if botd_flags.get("virtualGpu") else 8,
            "screenResolution": "800x600" if botd_flags.get("windowSize") else "1920x1080",
            "colorDepth": 24,
            "pluginsLength": 0 if botd_flags.get("pluginsInconsistency") else 3,
            "webglVendor": "Google Inc." if not botd_flags.get("virtualGpu") else "Mesa OffScreen",
            "webglRenderer": "Google SwiftShader" if botd_flags.get("virtualGpu") else "ANGLE (Intel)",
            "canvasHash": "c0ffeebot",
            "audioHash": "unsupported",
            "fontsCount": random.randint(0, 5),
        }
        botd = {
            "isBot": flagged_count > 0,
            "heuristicScore": h_score,
            "flaggedCount": flagged_count,
            "detectors": {k: botd_flags.get(k, False) for k in [
                "webdriver", "distinctiveProperties", "virtualGpu", "pluginsInconsistency",
                "languagesInconsistency", "windowSize", "errorTrace", "hasProcess",
                "platformMismatch", "headlessUa"
            ]},
            "reasons": [f"Flagged: {k}" for k, v in botd_flags.items() if v],
        }

    # Generate chunks for LSTM
    chunks = []
    chunk_size = 24
    move_records = [r for r in records if r.get("type") == "move"]
    if len(move_records) >= chunk_size:
        # Sliding window with 50% overlap
        for start in range(0, len(move_records) - chunk_size + 1, chunk_size // 2):
            slice_p = move_records[start:start + chunk_size + 1]
            if len(slice_p) < chunk_size:
                break
            chunk_matrix = []
            prev_sx, prev_sy = 0.0, 0.0
            for j in range(1, min(len(slice_p), chunk_size + 1)):
                dt = max(1, slice_p[j]["time"] - slice_p[j-1]["time"]) / 1000.0
                dx = slice_p[j]["x"] - slice_p[j-1]["x"]
                dy = slice_p[j]["y"] - slice_p[j-1]["y"]
                dist = math.sqrt(dx * dx + dy * dy)
                sx = dx / dt
                sy = dy / dt
                speed = dist / dt
                accel = math.sqrt((sx - prev_sx)**2 + (sy - prev_sy)**2) / dt
                chunk_matrix.append([dx, dy, sx, sy, speed, accel, dist, dt])
                prev_sx, prev_sy = sx, sy
            # Pad to exactly chunk_size if needed
            while len(chunk_matrix) < chunk_size:
                chunk_matrix.append([0.0] * 8)
            chunks.append(chunk_matrix[:chunk_size])

    return {
        "sessionId": session_id,
        "visitorId": visitor_id,
        "timestamp": 1725800000000,
        "pageUrl": "https://silkmoon.vn/products/silk-scarf",
        "fingerprint": fp,
        "botd": botd,
        "mouse": {
            "records": records,
            "chunks": chunks,
        },
    }
