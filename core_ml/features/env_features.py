"""
Environment & Fingerprint Feature Extraction Module (Production-Ready v3)
Combines FingerprintJS hardware components and BotD heuristic detectors.
Implements consistency checking inspired by FP-Inconsistent (arXiv:2406.07647).
Fully resilient to None/null fields, malformed types, and missing dictionaries.
"""

import math
import numpy as np


FEATURE_NAMES = [
    "heuristic_score",
    "flagged_count",
    "flag_webdriver",
    "flag_distinctive_props",
    "flag_virtual_gpu",
    "flag_plugins_inconsistency",
    "flag_languages_inconsistency",
    "flag_window_size",
    "flag_error_trace",
    "flag_has_process",
    "flag_platform_mismatch",
    "flag_headless_ua",
    "cpu_cores",
    "device_memory_gb",
    "color_depth",
    "pixel_ratio",
    "plugins_length",
    "max_touch_points",
    "screen_width",
    "screen_height",
    "screen_ratio",
    "fonts_count",
    "has_audio",
    "has_canvas",
    "is_virtual_concurrency",
    "is_desktop_chrome_zero_plugins",
    # FP-Inconsistent checks
    "touch_desktop_mismatch",
    "low_screen_resolution",
    "no_audio_support",
    "low_font_count",
]

MAX_FEATURE_MAGNITUDE = 1_000_000.0


def safe_float(val, default: float = 0.0) -> float:
    """Safely convert any value to float, handling None, NaN, Inf, and TypeErrors."""
    if val is None:
        return float(default)
    try:
        f = float(val)
        return float(default) if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError, OverflowError):
        return float(default)


def safe_bool(val) -> bool:
    """Safely evaluate boolean truthiness handling boolean, numeric, and string types."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return False


def extract_env_vector(fingerprint: dict, botd: dict) -> np.ndarray:
    """
    Extracts a fixed-length numerical feature vector from combined FingerprintJS and BotD telemetry.
    Returns: 1D numpy float32 array of length len(FEATURE_NAMES) (30 features).
    Fully robust against None, empty dicts, missing keys, or null fields.
    """
    fp = fingerprint if isinstance(fingerprint, dict) else {}
    bd = botd if isinstance(botd, dict) else {}
    detectors = bd.get("detectors")
    if not isinstance(detectors, dict):
        detectors = {}

    # BotD flags
    h_score = safe_float(bd.get("heuristicScore"), 0.0)
    flagged_cnt = safe_float(bd.get("flaggedCount"), 0.0)

    flag_wd = 1.0 if safe_bool(detectors.get("webdriver")) else 0.0
    flag_dist = 1.0 if safe_bool(detectors.get("distinctiveProperties")) else 0.0
    flag_gpu = 1.0 if safe_bool(detectors.get("virtualGpu")) else 0.0
    flag_plug = 1.0 if safe_bool(detectors.get("pluginsInconsistency")) else 0.0
    flag_lang = 1.0 if safe_bool(detectors.get("languagesInconsistency")) else 0.0
    flag_win = 1.0 if safe_bool(detectors.get("windowSize")) else 0.0
    flag_trace = 1.0 if safe_bool(detectors.get("errorTrace")) else 0.0
    flag_proc = 1.0 if safe_bool(detectors.get("hasProcess")) else 0.0
    flag_plat = 1.0 if safe_bool(detectors.get("platformMismatch")) else 0.0
    flag_hua = 1.0 if safe_bool(detectors.get("headlessUa")) else 0.0

    # FingerprintJS hardware components
    cpu = safe_float(fp.get("hardwareConcurrency"), 4.0)
    mem = safe_float(fp.get("deviceMemory"), 4.0)
    c_depth = safe_float(fp.get("colorDepth"), 24.0)
    p_ratio = safe_float(fp.get("pixelRatio"), 1.0)
    p_len = safe_float(fp.get("pluginsLength"), 0.0)
    touch = safe_float(fp.get("maxTouchPoints"), 0.0)

    # Screen resolution parsing (supports "1920x1080", [1920, 1080], etc.)
    res_val = fp.get("screenResolution")
    if isinstance(res_val, (list, tuple)) and len(res_val) >= 2:
        sw = safe_float(res_val[0], 1920.0)
        sh = safe_float(res_val[1], 1080.0)
    elif isinstance(res_val, str) and "x" in res_val:
        parts = res_val.split("x")
        sw = safe_float(parts[0], 1920.0) if len(parts) > 0 else 1920.0
        sh = safe_float(parts[1], 1080.0) if len(parts) > 1 else 1080.0
    else:
        sw, sh = 1920.0, 1080.0
    s_ratio = float(sw / sh) if sh > 0 else 1.777

    fonts = safe_float(fp.get("fontsCount"), 0.0)
    a_hash = fp.get("audioHash")
    has_audio = 1.0 if (a_hash and str(a_hash).lower() not in ("unsupported", "error", "none", "")) else 0.0
    c_hash = fp.get("canvasHash")
    has_canvas = 1.0 if (c_hash and str(c_hash).lower() not in ("unsupported", "error", "none", "")) else 0.0

    # Consistency indicators (FP-Inconsistent)
    is_virtual_concurrency = 1.0 if cpu <= 1 or (cpu == 2 and mem >= 16) else 0.0
    ua = str(fp.get("userAgent") or "").lower()
    is_desktop_chrome_zero_plugins = 1.0 if ("chrome" in ua and "mobile" not in ua and p_len == 0) else 0.0

    # Touch points on desktop device (touch > 0 but UA is desktop)
    is_mobile_ua = any(k in ua for k in ["mobile", "android", "iphone", "ipad"])
    touch_desktop_mismatch = 1.0 if (touch > 0 and not is_mobile_ua) else 0.0

    # Unusually low screen resolution (common in headless/VM environments)
    low_screen_resolution = 1.0 if (sw <= 800 and sh <= 600) else 0.0

    # No audio support (common in headless Chrome)
    no_audio_support = 1.0 if (not has_audio) else 0.0

    # Very low font count (headless environments have few fonts)
    low_font_count = 1.0 if fonts < 5 else 0.0

    features = [
        h_score,
        flagged_cnt,
        flag_wd,
        flag_dist,
        flag_gpu,
        flag_plug,
        flag_lang,
        flag_win,
        flag_trace,
        flag_proc,
        flag_plat,
        flag_hua,
        cpu,
        mem,
        c_depth,
        p_ratio,
        p_len,
        touch,
        sw,
        sh,
        s_ratio,
        fonts,
        has_audio,
        has_canvas,
        is_virtual_concurrency,
        is_desktop_chrome_zero_plugins,
        # New features
        touch_desktop_mismatch,
        low_screen_resolution,
        no_audio_support,
        low_font_count,
    ]

    # Keep malformed but finite client values from overflowing float32 and
    # poisoning model tensors. Normal browser values are far below this.
    bounded = np.clip(
        np.asarray(features, dtype=np.float64),
        -MAX_FEATURE_MAGNITUDE,
        MAX_FEATURE_MAGNITUDE,
    )
    bounded = np.nan_to_num(
        bounded,
        nan=0.0,
        posinf=MAX_FEATURE_MAGNITUDE,
        neginf=-MAX_FEATURE_MAGNITUDE,
    )
    return bounded.astype(np.float32)


def get_feature_dict(fingerprint: dict, botd: dict) -> dict:
    """Helper to return feature vector as dictionary for DataFrame / explanation."""
    vec = extract_env_vector(fingerprint, botd)
    return dict(zip(FEATURE_NAMES, vec.tolist()))
