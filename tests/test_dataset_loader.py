"""
Unit tests for real dataset parsers and synthetic generators.
"""

import pytest
from core_ml.dataset.loader import (
    parse_movement_notation,
    parse_phase2_record,
    records_to_chunks,
    generate_synthetic_telemetry,
)


class TestDatasetLoader:
    def test_parse_movement_notation(self):
        notation = "[m(150,250)][m(160,260)][c(l)][s(1)][m(180,290)]"
        records = parse_movement_notation(notation)
        assert len(records) == 5
        assert records[0]["type"] == "move"
        assert records[2]["type"] == "click"
        assert records[3]["type"] == "scroll"

        # Coordinates must be normalized in [0, 1]
        for r in records:
            assert 0.0 <= r["x"] <= 1.0
            assert 0.0 <= r["y"] <= 1.0

    def test_parse_phase2_record(self):
        phase2_sample = {
            "mousemove_total_behaviour": "[m(500,600)][m(520,630)][c(l)]",
            "mousemove_times": "1672531199000, 1672531199050, 1672531199100",
            "mousemove_client_height_width": "[(1080, 1920)]",
        }
        records = parse_phase2_record(phase2_sample)
        assert len(records) == 3
        # Timestamps normalized to relative 0
        assert records[0]["time"] == 0
        assert records[1]["time"] == 50
        assert records[2]["time"] == 100
        # Coordinates normalized
        assert 0.0 <= records[0]["x"] <= 1.0
        assert 0.0 <= records[0]["y"] <= 1.0

    def test_records_to_chunks(self):
        # 50 move points
        records = [
            {"time": i * 20, "x": 0.1 + i * 0.01, "y": 0.2 + i * 0.01, "type": "move"}
            for i in range(50)
        ]
        chunks = records_to_chunks(records, chunk_size=24, stride=12)
        assert len(chunks) > 0
        assert len(chunks[0]) == 24
        # 8 features per point
        assert len(chunks[0][0]) == 8

    def test_generate_synthetic_telemetry(self):
        human = generate_synthetic_telemetry(is_bot=False)
        assert "fingerprint" in human
        assert "botd" in human
        assert "mouse" in human
        assert human["botd"]["heuristicScore"] < 0.35

        bot = generate_synthetic_telemetry(is_bot=True, bot_level="naive")
        assert bot["botd"]["detectors"]["webdriver"] is True

        advanced_bot = generate_synthetic_telemetry(is_bot=True, bot_level="advanced")
        assert "records" in advanced_bot["mouse"]
