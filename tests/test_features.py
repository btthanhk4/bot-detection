"""
Unit tests for mouse and environment feature extraction modules.
"""

import numpy as np
import torch

from core_ml.features.env_features import (
    extract_env_vector,
    safe_float,
    safe_bool,
    FEATURE_NAMES as ENV_FEATURE_NAMES,
)
from core_ml.features.mouse_features import (
    compute_statistical_features,
    extract_mouse_stat_vector,
    extract_sequential_chunks,
    STATISTICAL_FEATURE_NAMES,
)


class TestEnvFeatures:
    def test_safe_conversions(self):
        assert safe_float(None, 5.0) == 5.0
        assert safe_float("12.34") == 12.34
        assert safe_float("invalid", 1.0) == 1.0
        assert safe_float(float("nan"), 0.0) == 0.0
        assert safe_float(float("inf"), 0.0) == 0.0

        assert safe_bool(True) is True
        assert safe_bool(False) is False
        assert safe_bool("true") is True
        assert safe_bool("1") is True
        assert safe_bool(1) is True
        assert safe_bool("false") is False
        assert safe_bool("0") is False
        assert safe_bool(0) is False
        assert safe_bool(None) is False

    def test_extract_env_vector_complete(self):
        fp = {
            "hardwareConcurrency": 8,
            "deviceMemory": 16,
            "colorDepth": 24,
            "pixelRatio": 2.0,
            "pluginsLength": 5,
            "maxTouchPoints": 0,
            "screenResolution": "1920x1080",
            "fontsCount": 25,
            "audioHash": "123.456",
            "canvasHash": "abc1234",
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
        }
        botd = {
            "heuristicScore": 0.0,
            "flaggedCount": 0,
            "detectors": {
                "webdriver": False,
                "virtualGpu": False,
            },
        }
        vec = extract_env_vector(fp, botd)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (len(ENV_FEATURE_NAMES),)
        assert not np.isnan(vec).any()
        assert not np.isinf(vec).any()

    def test_extract_env_vector_none_safe(self):
        vec_none = extract_env_vector(None, None)
        assert len(vec_none) == len(ENV_FEATURE_NAMES)
        assert not np.isnan(vec_none).any()

        vec_empty = extract_env_vector({}, {})
        assert len(vec_empty) == len(ENV_FEATURE_NAMES)
        assert not np.isnan(vec_empty).any()

    def test_env_features_array_resolution(self):
        # Supports array/tuple format [width, height]
        fp_arr = {"screenResolution": [2560, 1440]}
        vec = extract_env_vector(fp_arr, {})
        # screen_width is at index 18, screen_height at 19
        assert vec[18] == 2560.0
        assert vec[19] == 1440.0

        # Malformed nested types
        vec3 = extract_env_vector({"hardwareConcurrency": "not_a_num"}, {"detectors": None})
        assert vec3.shape == (len(ENV_FEATURE_NAMES),)
        assert not np.isnan(vec3).any()

    def test_extreme_environment_values_stay_finite(self):
        vec = extract_env_vector(
            {
                "hardwareConcurrency": 10**400,
                "deviceMemory": -(10**400),
                "screenResolution": [10**400, 10**400],
            },
            {"heuristicScore": 10**400},
        )

        assert np.isfinite(vec).all()


class TestMouseFeatures:
    def test_statistical_features_synthetic_points(self):
        records = [
            {"time": i * 16, "x": 0.1 + i * 0.01, "y": 0.2 + (i % 2) * 0.005, "type": "move"}
            for i in range(25)
        ]
        records.append({"time": 400, "x": 0.35, "y": 0.2, "type": "click"})

        stats = compute_statistical_features(records)
        assert isinstance(stats, dict)
        assert stats["point_count"] == 26
        assert stats["move_point_count"] == 25
        assert 0.0 <= stats["straightness"] <= 1.0
        assert stats["mean_speed"] > 0
        assert stats["click_to_move_ratio"] > 0

        vec = extract_mouse_stat_vector(stats)
        assert len(vec) == len(STATISTICAL_FEATURE_NAMES)
        assert not np.isnan(vec).any()

    def test_statistical_features_none_and_empty(self):
        stats_none = compute_statistical_features(None)
        assert stats_none["point_count"] == 0
        assert stats_none["straightness"] == 1.0

        stats_empty = compute_statistical_features([])
        assert stats_empty["point_count"] == 0

        stats_malformed = compute_statistical_features([None, {}, {"x": None}, "bad_record"])
        assert stats_malformed["point_count"] == 0

        vec = extract_mouse_stat_vector(None)
        assert len(vec) == len(STATISTICAL_FEATURE_NAMES)
        assert (vec == 0.0).all()

        malformed_vec = extract_mouse_stat_vector({"mean_speed": "not-a-number", "std_speed": None})
        assert not np.isnan(malformed_vec).any()
        assert (malformed_vec == 0.0).all()

    def test_pixel_auto_normalization(self):
        # Raw pixel coordinates (> 1.0)
        records_pixel = [
            {"time": i * 20, "x": 100.0 + i * 10.0, "y": 200.0 + i * 5.0, "type": "move"}
            for i in range(20)
        ]
        stats = compute_statistical_features(records_pixel)
        # Normalized speeds should be reasonable (< 50) rather than thousands of px/s
        assert stats["mean_speed"] < 50.0

    def test_extract_sequential_chunks(self):
        chunk_raw = [
            [[0.01, 0.01, 0.5, 0.5, 0.7, 1.2, 0.014, 0.016] for _ in range(24)]
            for _ in range(3)
        ]
        tensor = extract_sequential_chunks(chunk_raw, chunk_size=24, n_features=8)
        assert isinstance(tensor, torch.Tensor)
        assert tensor.shape == (3, 24, 8)

        # None / empty resilience
        empty_tensor = extract_sequential_chunks(None)
        assert empty_tensor.shape == (0, 24, 8)

        # Incomplete chunks must be rejected, never padded into valid evidence.
        short_chunk = [[[0.1, 0.1, 0.5, 0.5, 0.7, 1.2, 0.014, 0.016] for _ in range(10)]]
        rejected_tensor = extract_sequential_chunks(short_chunk, chunk_size=24, n_features=8)
        assert rejected_tensor.shape == (0, 24, 8)

        malformed_chunk = [[[0.1] * 7 for _ in range(24)]]
        assert extract_sequential_chunks(malformed_chunk).shape == (0, 24, 8)

    def test_dos_defensive_caps(self):
        # 1. 2,000 points sent by adversarial caller capped to collector window
        excessive_records = [
            {"time": i * 10, "x": 0.1 + (i % 10) * 0.01, "y": 0.2 + (i % 5) * 0.01, "type": "move"}
            for i in range(2000)
        ]
        stats = compute_statistical_features(excessive_records)
        assert stats["point_count"] == 100

        # Invalid trailing records cannot evict all valid movement before validation.
        valid_then_garbage = excessive_records[:30] + [{"x": None}] * 600
        valid_stats = compute_statistical_features(valid_then_garbage)
        assert valid_stats["move_point_count"] == 30

        # 2. 200 chunks sent by caller capped to 50
        excessive_chunks = [
            [[0.01, 0.01, 0.5, 0.5, 0.7, 1.2, 0.014, 0.016] for _ in range(24)]
            for _ in range(200)
        ]
        tensor = extract_sequential_chunks(excessive_chunks)
        assert tensor.shape[0] == 50

    def test_mouse_features_out_of_order_timestamps(self):
        # Out of order timestamps should be chronologically sorted automatically
        unordered_records = [
            {"time": 300, "x": 0.3, "y": 0.3, "type": "move"},
            {"time": 100, "x": 0.1, "y": 0.1, "type": "move"},
            {"time": 200, "x": 0.2, "y": 0.2, "type": "move"},
            {"time": 400, "x": 0.4, "y": 0.4, "type": "move"},
        ]
        stats = compute_statistical_features(unordered_records)
        assert stats["duration_ms"] == 300.0  # 400 - 100
        assert stats["mean_speed"] > 0
        assert not np.isnan(stats["mean_speed"])

    def test_extreme_mouse_coordinates_stay_finite_and_bounded(self):
        records = [
            {
                "time": i,
                "x": (-1 if i % 2 else 1) * 10**300,
                "y": (-1 if i % 3 else 1) * 10**300,
                "type": "move",
            }
            for i in range(30)
        ]

        stats = compute_statistical_features(records)
        vector = extract_mouse_stat_vector(stats)

        assert np.isfinite(vector).all()
        assert np.max(np.abs(vector)) <= 1_000_000.0

    def test_extreme_mouse_outlier_does_not_poison_valid_window(self):
        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        records.append({"time": 1000, "x": 10**300, "y": 10**300, "type": "move"})

        stats = compute_statistical_features(records)

        assert stats["move_point_count"] == 30
        assert stats["mean_speed"] > 0
