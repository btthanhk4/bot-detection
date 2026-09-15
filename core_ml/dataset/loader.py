"""
Dataset Loader & Synthetic Telemetry Generator (Optimized v3)
=============================================================
- Loads REAL mouse trajectories from web_bot_detection_dataset
  * Phase 1: folder-per-session format with estimated timestamps
  * Phase 2: MongoDB JSON-lines format with REAL browser timestamps
- Parses the [m(x,y)][c(l)] notation format into structured records
- Provides advanced synthetic generator with Bézier bot evasion patterns
- Sliding window chunking for LSTM input preparation
"""

import json
import math
import os
import random
import re
import hashlib
from dataclasses import dataclass
import numpy as np

from core_ml.features.mouse_features import records_to_chunks as _canonical_records_to_chunks


@dataclass
class RealMouseSession:
    records: list
    label: int
    session_id: str
    source: str
    split: str
    scenario: str


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
            t += 100
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "click"
            })

        elif action == 's':
            t += 50
            # Scroll events don't change position
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "scroll"
            })

    if records:
        max_x = max((r["x"] for r in records), default=1.0)
        max_y = max((r["y"] for r in records), default=1.0)
        scale_w = max(1920.0, max_x) if max_x > 1.0 else 1.0
        scale_h = max(1080.0, max_y) if max_y > 1.0 else 1.0
        for r in records:
            r["x"] = round(max(0.0, min(1.0, r["x"] / scale_w)), 5)
            r["y"] = round(max(0.0, min(1.0, r["y"] / scale_h)), 5)

    return records


def parse_phase2_record(record: dict) -> list:
    """
    Parse a Phase 2 MongoDB-exported record into structured mouse records.
    Phase 2 records have:
      - mousemove_total_behaviour: M4D notation string [m(x,y)][c(l)]...
      - mousemove_times: comma-separated REAL browser timestamps (epoch ms)
      - mousemove_client_height_width: viewport sizes [(h,w)]...
    
    Normalizes coordinates to [0.0, 1.0] using the actual browser client dimensions.
    """
    notation = record.get("mousemove_total_behaviour", "")
    times_str = record.get("mousemove_times", "")
    
    if not notation:
        return []

    # Extract client viewport width and height
    hw_str = record.get("mousemove_client_height_width", "")
    view_w, view_h = 1920.0, 1080.0
    if hw_str:
        hw_matches = re.findall(r'\((\d+),\s*(\d+)\)', hw_str)
        if hw_matches:
            try:
                view_h = max(100.0, float(hw_matches[0][0]))
                view_w = max(100.0, float(hw_matches[0][1]))
            except Exception:
                view_w, view_h = 1920.0, 1080.0
    
    # Parse actions from M4D notation
    pattern = re.compile(r'\[([a-z]+)\(([^)]*)\)\]')
    actions = pattern.findall(notation)
    
    # Parse real timestamps (comma-separated epoch milliseconds)
    timestamps = []
    if times_str:
        timestamps = [int(t.strip()) for t in times_str.split(',') if t.strip().isdigit()]
    
    has_real_timestamps = len(timestamps) > 0
    
    records = []
    event_idx = 0  # Index into timestamps (1:1 with ALL events, not just moves)
    last_x, last_y = 0.0, 0.0
    last_time = timestamps[0] if timestamps else 0
    
    for action, args in actions:
        # Consume real timestamp for this event (all event types share the same timestamp array)
        if has_real_timestamps and event_idx < len(timestamps):
            t = timestamps[event_idx]
            event_idx += 1
        else:
            t = None  # Will use fallback below
        
        if action == 'm':
            parts = args.split(',')
            if len(parts) == 2:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                except ValueError:
                    continue
                
                if t is None:
                    # Fallback to Fitts's law estimation
                    if records:
                        dx = x - last_x
                        dy = y - last_y
                        dist = math.sqrt(dx * dx + dy * dy)
                        base_dt = 12.0
                        dist_factor = min(dist / 50.0, 5.0)
                        dt = base_dt * (1.0 + dist_factor * 0.5)
                        last_time += max(1, int(dt))
                    t = last_time
                
                records.append({
                    "time": t,
                    "x": x,
                    "y": y,
                    "type": "move"
                })
                last_x, last_y = x, y
                last_time = t
        
        elif action == 'c':
            if t is None:
                t = last_time + 100
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "click"
            })
            last_time = t
        
        elif action == 's':
            if t is None:
                t = last_time + 50
            records.append({
                "time": t,
                "x": last_x,
                "y": last_y,
                "type": "scroll"
            })
            last_time = t
    
    # Normalize timestamps to relative (start from 0) for consistency
    if records and has_real_timestamps:
        t0 = records[0]["time"]
        for r in records:
            r["time"] = r["time"] - t0

    # Normalize coordinates to [0.0, 1.0] matching client-side collector
    if records:
        for r in records:
            r["x"] = round(max(0.0, min(1.0, r["x"] / view_w)), 5)
            r["y"] = round(max(0.0, min(1.0, r["y"] / view_h)), 5)
    
    return records


def load_phase2_dataset(dataset_root: str, scenario: str = None, with_metadata: bool = False):
    """
    Load Phase 2 data from MongoDB-exported JSON lines files.
    Phase 2 has real browser timestamps and richer data (~220MB).
    
    Structure:
        phase2/data/mouse_movements/humans/mouse_movements_humans.json
        phase2/data/mouse_movements/bots/mouse_movements_moderate_bots.json
        phase2/data/mouse_movements/bots/mouse_movements_advanced_bots.json
        phase2/annotations/humans_and_advanced_bots/humans_and_advanced_bots
        phase2/annotations/humans_and_moderate_and_advanced_bots/...
    
    Returns:
        list of (records, label) tuples, label: 0=human, 1=bot
    """
    sessions = []
    phase2_root = os.path.join(dataset_root, "phase2")
    
    if not os.path.isdir(phase2_root):
        return sessions
    
    # Build label map from Phase 2 annotations
    # Phase 2 annotation format: "session_id_suffix label"
    label_map = {}  # session_id -> label (0=human, 1=bot)
    ann_root = os.path.join(phase2_root, "annotations")
    if os.path.isdir(ann_root):
        for scenario_dir in os.listdir(ann_root):
            scenario_path = os.path.join(ann_root, scenario_dir)
            if not os.path.isdir(scenario_path):
                continue
            for fname in os.listdir(scenario_path):
                fpath = os.path.join(scenario_path, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            parts = line.split()
                            if len(parts) == 2:
                                sid, label_str = parts
                                # Remove suffix like _0, _1, _2 to get base session_id
                                base_sid = re.sub(r'_\d+$', '', sid)
                                if "human" in label_str:
                                    label_map[sid] = 0
                                    label_map[base_sid] = 0
                                else:
                                    label_map[sid] = 1
                                    label_map[base_sid] = 1
    
    # Load data files
    data_files = [(os.path.join(phase2_root, "data", "mouse_movements", "humans", "mouse_movements_humans.json"), 0)]
    if scenario != "humans_and_advanced_bots":
        data_files.append((os.path.join(phase2_root, "data", "mouse_movements", "bots", "mouse_movements_moderate_bots.json"), 1))
    if scenario != "humans_and_moderate_bots":
        data_files.append((os.path.join(phase2_root, "data", "mouse_movements", "bots", "mouse_movements_advanced_bots.json"), 1))
    
    seen_sessions = set()  # Deduplicate by session_id
    
    for fpath, default_label in data_files:
        if not os.path.isfile(fpath):
            continue
        
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    session_id = record.get("session_id", "")
                    if not session_id or session_id in seen_sessions:
                        continue
                    seen_sessions.add(session_id)
                    
                    # Parse mouse records with REAL timestamps
                    mouse_records = parse_phase2_record(record)
                    if len(mouse_records) < 10:
                        continue
                    
                    # Cap at 5000 records per session to keep training fast
                    # (Phase 2 sessions can have 34K+ records)
                    if len(mouse_records) > 5000:
                        mouse_records = mouse_records[:5000]
                    
                    # Determine label from annotation or fallback to file-based label
                    label = label_map.get(session_id, default_label)
                    
                    session = RealMouseSession(
                        records=mouse_records,
                        label=label,
                        session_id=session_id,
                        source="phase2",
                        split="unspecified",
                        scenario=scenario or "all",
                    )
                    sessions.append(session if with_metadata else (mouse_records, label))
        except Exception as e:
            print(f"  Warning: Error loading Phase 2 file {os.path.basename(fpath)}: {e}")
            continue
    
    return sessions


def load_real_dataset(dataset_root: str, scenario: str = "humans_and_moderate_bots",
                      include_phase2: bool = True, with_metadata: bool = False):
    """
    Loads real mouse movement sessions from web_bot_detection_dataset.
    Loads Phase 1 (folder-per-session) and optionally Phase 2 (JSON lines with real timestamps).
    
    Args:
        dataset_root: Path to web_bot_detection_dataset
        scenario: "humans_and_moderate_bots" or "humans_and_advanced_bots"
        include_phase2: If True, also load Phase 2 data (with real timestamps)
    
    Returns:
        list of (records, label) tuples, where label is 0 (human) or 1 (bot)
    """
    sessions = []
    seen_session_ids = set()

    # ===== Phase 1: folder-per-session format =====
    phase1_data = os.path.join(dataset_root, "phase1", "data", "mouse_movements", scenario)
    phase1_ann_train = os.path.join(dataset_root, "phase1", "annotations", scenario, "train")
    phase1_ann_test = os.path.join(dataset_root, "phase1", "annotations", scenario, "test")

    # Parse Phase 1 annotation files
    label_map = {}
    for split, ann_file in [("train", phase1_ann_train), ("test", phase1_ann_test)]:
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
                            label_map[session_id] = (0, split)
                        else:
                            label_map[session_id] = (1, split)  # moderate_bot, advanced_bot

    # Load Phase 1 sessions
    if os.path.isdir(phase1_data):
        for session_id in os.listdir(phase1_data):
            session_dir = os.path.join(phase1_data, session_id)
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

                annotation = label_map.get(session_id)
                if annotation is None:
                    continue  # skip sessions without known labels

                label, split = annotation
                sessions.append(RealMouseSession(
                    records=records,
                    label=label,
                    session_id=session_id,
                    source="phase1",
                    split=split,
                    scenario=scenario,
                ))
                seen_session_ids.add(session_id)
            except (json.JSONDecodeError, Exception):
                continue

    # ===== Phase 2: MongoDB JSON-lines with REAL timestamps =====
    if include_phase2:
        sessions.extend(load_phase2_dataset(dataset_root, scenario=scenario, with_metadata=True))

    unique_sessions = []
    seen_trajectories = set()
    for session in sessions:
        payload = json.dumps(session.records, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hashlib.sha256(payload).digest()
        if signature not in seen_trajectories:
            seen_trajectories.add(signature)
            unique_sessions.append(session)
    if with_metadata:
        return unique_sessions
    return [(session.records, session.label) for session in unique_sessions]


def records_to_chunks(records: list, chunk_size: int = 24, stride: int = 12, n_features: int = 8) -> list:
    """
    Convert raw mouse records into LSTM-ready chunks using sliding window.
    Features: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
    Works directly in normalized screen coordinate space [0.0, 1.0].
    """
    if n_features != 8:
        return []
    return _canonical_records_to_chunks(records, chunk_size=chunk_size, stride=stride)


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

    # Use the same feature contract as real data and the browser collector.
    chunks = records_to_chunks(records, chunk_size=24, stride=12)

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
