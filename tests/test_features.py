"""
Unit tests for mouse and environment feature extraction modules.
"""

import math
import numpy as np
import pytest
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
        vec1 = extract_env_vector(None, None)
        assert vec1.shape == (len(ENV_FEATURE_NAMES),)
        assert not np.isnan(vec1).any()

        vec2 = extract_env_vector({}, {})
        assert vec2.shape == (len(ENV_FEATURE_NAMES),)
        assert not np.isnan(vec2).any()

        # Malformed nested types
        vec3 = extract_env_vector({"hardwareConcurrency": "not_a_num"}, {"detectors": None})
        assert vec3.shape == (len(ENV_FEATURE_NAMES),)
        assert not np.isnan(vec3).any()


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

        # Truncated or padded chunks
        short_chunk = [[[0.1, 0.1, 0.5, 0.5, 0.7, 1.2, 0.014, 0.016] for _ in range(10)]]
        padded_tensor = extract_sequential_chunks(short_chunk, chunk_size=24, n_features=8)
        assert padded_tensor.shape == (1, 24, 8)

    def test_dos_defensive_caps(self):
        # 1. 2,000 points sent by adversarial caller capped to 500
        excessive_records = [
            {"time": i * 10, "x": 0.1 + (i % 10) * 0.01, "y": 0.2 + (i % 5) * 0.01, "type": "move"}
            for i in range(2000)
        ]
        stats = compute_statistical_features(excessive_records)
        assert stats["point_count"] == 500

        # 2. 200 chunks sent by caller capped to 50
        excessive_chunks = [
            [[0.01, 0.01, 0.5, 0.5, 0.7, 1.2, 0.014, 0.016] for _ in range(24)]
            for _ in range(200)
        ]
        tensor = extract_sequential_chunks(excessive_chunks)
        assert tensor.shape[0] == 50
