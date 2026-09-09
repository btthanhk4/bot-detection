"""
Dataset Loader & Synthetic Telemetry Generator
Loads real sample trajectories from Tuần 3 repos (DELBOT-Mouse, web_bot_detection_dataset)
and provides realistic synthetic generator for bootstrapping models and testing.
"""

import math
import os
import random
import numpy as np


def generate_synthetic_human_trajectory(n_points: int = 40) -> list:
    """Generates realistic human mouse movement using smooth curves and natural jitter."""
    records = []
    t = 0
    # Start point
    x = random.uniform(0.1, 0.4)
    y = random.uniform(0.1, 0.4)
    # Target point
    target_x = random.uniform(0.6, 0.9)
    target_y = random.uniform(0.6, 0.9)

    records.append({"time": t, "x": round(x, 4), "y": round(y, 4), "type": "move"})

    for i in range(1, n_points):
        # Human movement: ease-in ease-out curve + micro-tremors
        progress = i / float(n_points)
        smooth_p = 3 * (progress ** 2) - 2 * (progress ** 3)
        dt = random.randint(12, 35)  # variable human intervals (12-35ms)
        t += dt

        cur_x = x + (target_x - x) * smooth_p + random.gauss(0, 0.003)
        cur_y = y + (target_y - y) * smooth_p + random.gauss(0, 0.003)

        records.append({
            "time": t,
            "x": round(max(0.0, min(1.0, cur_x)), 4),
            "y": round(max(0.0, min(1.0, cur_y)), 4),
            "type": "move",
        })

    # Add final click
    records.append({"time": t + random.randint(80, 200), "x": records[-1]["x"], "y": records[-1]["y"], "type": "click"})
    return records


def generate_synthetic_bot_trajectory(bot_type: str = "linear", n_points: int = 25) -> list:
    """
    Generates robotic trajectories:
    - linear: perfectly straight line with constant speed and zero jitter
    - instant: 1-2 jump points directly to target (teleportation)
    - grid: discrete steps on a grid
    """
    records = []
    t = 0
    x = random.uniform(0.1, 0.3)
    y = random.uniform(0.1, 0.3)
    target_x = random.uniform(0.7, 0.9)
    target_y = random.uniform(0.7, 0.9)

    records.append({"time": t, "x": round(x, 4), "y": round(y, 4), "type": "move"})

    if bot_type == "instant":
        # Bot just teleports directly to target and clicks
        t += random.randint(5, 15)
        records.append({"time": t, "x": round(target_x, 4), "y": round(target_y, 4), "type": "move"})
        t += random.randint(5, 15)
        records.append({"time": t, "x": round(target_x, 4), "y": round(target_y, 4), "type": "click"})
        return records

    # Linear constant-velocity bot
    for i in range(1, n_points):
        progress = i / float(n_points)
        dt = 16  # strictly constant interval (e.g. 60Hz loop)
        t += dt
        cur_x = x + (target_x - x) * progress
        cur_y = y + (target_y - y) * progress
        records.append({
            "time": t,
            "x": round(cur_x, 4),
            "y": round(cur_y, 4),
            "type": "move",
        })

    records.append({"time": t + 10, "x": round(target_x, 4), "y": round(target_y, 4), "type": "click"})
    return records


def generate_synthetic_telemetry(is_bot: bool = False, bot_level: str = "moderate") -> dict:
    """
    Creates a full realistic telemetry payload for training & testing.
    """
    session_id = f"sess_{random.randint(100000, 999999)}"
    visitor_id = f"fp_{random.randint(1000, 9999)}"

    if not is_bot:
        # Realistic Human
        records = generate_synthetic_human_trajectory(n_points=random.randint(30, 60))
        fp = {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "platform": "Win32",
            "language": "vi-VN",
            "languages": ["vi-VN", "vi", "en-US", "en"],
            "hardwareConcurrency": random.choice([4, 8, 12, 16]),
            "deviceMemory": random.choice([8, 16, 32]),
            "maxTouchPoints": 0,
            "screenResolution": random.choice(["1920x1080", "1536x864", "2560x1440"]),
            "colorDepth": 24,
            "pixelRatio": 1.0,
            "pluginsLength": random.randint(3, 5),
            "webglVendor": "Google Inc. (NVIDIA)",
            "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "canvasHash": "a1b2c3d4",
            "audioHash": "35.12345",
            "fontsCount": random.randint(25, 45),
        }
        botd = {
            "isBot": False,
            "heuristicScore": 0.0,
            "flaggedCount": 0,
            "detectors": {
                "webdriver": False,
                "distinctiveProperties": False,
                "virtualGpu": False,
                "pluginsInconsistency": False,
                "languagesInconsistency": False,
                "windowSize": False,
                "errorTrace": False,
                "hasProcess": False,
                "platformMismatch": False,
                "headlessUa": False,
            },
            "reasons": [],
        }
    else:
        # Bot
        if bot_level == "naive":
            records = generate_synthetic_bot_trajectory(bot_type="instant")
            botd_flags = {"webdriver": True, "pluginsInconsistency": True, "virtualGpu": True, "headlessUa": True}
        elif bot_level == "moderate":
            records = generate_synthetic_bot_trajectory(bot_type="linear", n_points=24)
            botd_flags = {"webdriver": random.choice([True, False]), "pluginsInconsistency": True, "virtualGpu": False}
        else:
            # Advanced bot (tries to mimic human trajectory but has subtle kinematic anomalies)
            records = generate_synthetic_bot_trajectory(bot_type="linear", n_points=30)
            botd_flags = {"platformMismatch": True}

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
            "fontsCount": 2,
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

    # Generate chunks for mouse
    chunks = []
    chunk_size = 24
    if len(records) >= chunk_size:
        slice_p = records[:chunk_size]
        chunk_matrix = []
        for j in range(1, len(slice_p)):
            dt = max(1, slice_p[j]["time"] - slice_p[j - 1]["time"]) / 1000.0
            dx = slice_p[j]["x"] - slice_p[j - 1]["x"]
            dy = slice_p[j]["y"] - slice_p[j - 1]["y"]
            dist = math.sqrt(dx * dx + dy * dy)
            chunk_matrix.append([dx, dy, dx / dt, dy / dt, dist / dt, 0.0, dist, dt])
        chunk_matrix.append([0.0] * 8)
        chunks.append(chunk_matrix)

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
