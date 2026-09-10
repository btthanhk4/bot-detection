"""
Environment & Fingerprint Feature Extraction Module
Combines FingerprintJS hardware components and BotD heuristic detectors.
Implements consistency checking inspired by FP-Inconsistent (arXiv:2406.07647).
"""

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
    # New FP-Inconsistent checks (v2)
    "touch_desktop_mismatch",
    "low_screen_resolution",
    "no_audio_support",
    "low_font_count",
]


def extract_env_vector(fingerprint: dict, botd: dict) -> np.ndarray:
    """
    Extracts a fixed-length numerical feature vector from combined FingerprintJS and BotD telemetry.
    Returns: 1D numpy float32 array of length len(FEATURE_NAMES)
    """
    fp = fingerprint or {}
    bd = botd or {}
    detectors = bd.get("detectors", {})

    # BotD flags
    h_score = float(bd.get("heuristicScore", 0.0))
    flagged_cnt = float(bd.get("flaggedCount", 0))

    flag_wd = 1.0 if detectors.get("webdriver", False) else 0.0
    flag_dist = 1.0 if detectors.get("distinctiveProperties", False) else 0.0
    flag_gpu = 1.0 if detectors.get("virtualGpu", False) else 0.0
    flag_plug = 1.0 if detectors.get("pluginsInconsistency", False) else 0.0
    flag_lang = 1.0 if detectors.get("languagesInconsistency", False) else 0.0
    flag_win = 1.0 if detectors.get("windowSize", False) else 0.0
    flag_trace = 1.0 if detectors.get("errorTrace", False) else 0.0
    flag_proc = 1.0 if detectors.get("hasProcess", False) else 0.0
    flag_plat = 1.0 if detectors.get("platformMismatch", False) else 0.0
    flag_hua = 1.0 if detectors.get("headlessUa", False) else 0.0

    # FingerprintJS hardware components
    cpu = float(fp.get("hardwareConcurrency", 4))
    mem = float(fp.get("deviceMemory", 4))
    c_depth = float(fp.get("colorDepth", 24))
    p_ratio = float(fp.get("pixelRatio", 1.0))
    p_len = float(fp.get("pluginsLength", 0))
    touch = float(fp.get("maxTouchPoints", 0))

    # Screen resolution parsing
    res_str = str(fp.get("screenResolution", "1920x1080"))
    try:
        parts = res_str.split("x")
        sw = float(parts[0]) if len(parts) > 0 else 1920.0
        sh = float(parts[1]) if len(parts) > 1 else 1080.0
    except Exception:
        sw, sh = 1920.0, 1080.0
    s_ratio = float(sw / sh) if sh > 0 else 1.777

    fonts = float(fp.get("fontsCount", 0))
    has_audio = 1.0 if fp.get("audioHash") and fp.get("audioHash") != "unsupported" else 0.0
    has_canvas = 1.0 if fp.get("canvasHash") and fp.get("canvasHash") != "unsupported" else 0.0

    # Consistency indicators (FP-Inconsistent)
    is_virtual_concurrency = 1.0 if cpu <= 1 or (cpu == 2 and mem >= 16) else 0.0
    ua = str(fp.get("userAgent", "")).lower()
    is_desktop_chrome_zero_plugins = 1.0 if ("chrome" in ua and "mobile" not in ua and p_len == 0) else 0.0

    # New FP-Inconsistent checks
    # Touch points on desktop device (touch > 0 but UA is desktop)
    is_mobile_ua = any(k in ua for k in ["mobile", "android", "iphone", "ipad"])
    touch_desktop_mismatch = 1.0 if (touch > 0 and not is_mobile_ua) else 0.0

    # Unusually low screen resolution (common in headless/VM environments)
    low_screen_resolution = 1.0 if (sw <= 800 and sh <= 600) else 0.0

    # No audio support (common in headless Chrome)
    no_audio_support = 1.0 if (not has_audio) else 0.0

    # Very low font count (headless environments have few fonts)
    low_font_count = 1.0 if (fonts < 5 and fonts > 0) else (1.0 if fonts == 0 else 0.0)

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

    return np.array(features, dtype=np.float32)


def get_feature_dict(fingerprint: dict, botd: dict) -> dict:
    """Helper to return feature vector as dictionary for DataFrame / explanation."""
    vec = extract_env_vector(fingerprint, botd)
    return dict(zip(FEATURE_NAMES, vec.tolist()))
