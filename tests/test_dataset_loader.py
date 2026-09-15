"""
Unit tests for real dataset parsers and synthetic generators.
"""

import pytest
import json
import shutil
import subprocess
from pathlib import Path
import numpy as np
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

        assert records == parse_movement_notation(notation)

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

    def test_collector_chunks_match_python_feature_contract(self):
        if not shutil.which("node"):
            pytest.skip("Node.js is not installed")

        records = [
            {"time": i * 17, "x": 0.1 + i * 0.01, "y": 0.2 + (i % 4) * 0.003, "type": "move"}
            for i in range(30)
        ]
        records.insert(8, {"time": 120, "x": 0.17, "y": 0.209, "type": "click"})
        root = Path(__file__).resolve().parents[1]
        subprocess.run(["node", "build.js"], cwd=root / "collector", check=True, capture_output=True)
        script = (
            "const BotCollector=require('./collector/dist/bot-collector.js');"
            "const c=new BotCollector({autoSendInterval:0});"
            f"c.mouseRecorder.records={json.dumps(records)};"
            "process.stdout.write(JSON.stringify(c.mouseRecorder.getChunks(24)));"
        )
        output = subprocess.run(
            ["node", "-e", script], cwd=root, check=True, capture_output=True, text=True
        ).stdout

        js_chunks = json.loads(output)
        py_chunks = records_to_chunks(records, chunk_size=24, stride=12)
        assert np.allclose(js_chunks, py_chunks, rtol=1e-6, atol=1e-8)

    def test_parsers_clamp_negative_coordinates(self):
        records = parse_movement_notation("[m(-50,-20)][m(100,200)]")
        assert all(0.0 <= item["x"] <= 1.0 and 0.0 <= item["y"] <= 1.0 for item in records)
