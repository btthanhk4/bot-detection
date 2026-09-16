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
    load_phase2_dataset,
    load_real_dataset,
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

    def test_collector_payload_omits_redundant_chunks(self):
        if not shutil.which("node"):
            pytest.skip("Node.js is not installed")

        root = Path(__file__).resolve().parents[1]
        subprocess.run(["node", "build.js"], cwd=root / "collector", check=True, capture_output=True)
        script = """
const BotCollector = require('./collector/dist/bot-collector.js');
const collector = new BotCollector({autoSendInterval: 0});
collector.cachedFingerprint = {visitorId: 'visitor', components: {}};
collector.cachedBotd = {};
collector.mouseRecorder.records = Array.from({length: 500}, (_, i) => ({
  time: i * 16, x: i / 500, y: i / 1000, type: 'move'
}));
collector.getPayload().then(payload => process.stdout.write(JSON.stringify({
  hasChunks: Object.prototype.hasOwnProperty.call(payload.mouse, 'chunks'),
  recordCount: payload.mouse.records.length,
  payloadBytes: Buffer.byteLength(JSON.stringify(payload))
})));
"""
        result = json.loads(subprocess.run(
            ["node", "-e", script], cwd=root, check=True, capture_output=True, text=True
        ).stdout)

        assert result["hasChunks"] is False
        assert result["recordCount"] == 100
        assert result["payloadBytes"] < 262144

    def test_parsers_clamp_negative_coordinates(self):
        records = parse_movement_notation("[m(-50,-20)][m(100,200)]")
        assert all(0.0 <= item["x"] <= 1.0 and 0.0 <= item["y"] <= 1.0 for item in records)

    def test_real_dataset_preserves_official_phase1_split(self, tmp_path):
        scenario = "humans_and_moderate_bots"
        data_root = tmp_path / "phase1" / "data" / "mouse_movements" / scenario
        annotations = tmp_path / "phase1" / "annotations" / scenario
        for offset, session_id in enumerate(("train-human", "test-bot")):
            session_dir = data_root / session_id
            session_dir.mkdir(parents=True)
            notation = "".join(
                f"[m({100 + i + offset * 50},{200 + i})]" for i in range(12)
            )
            (session_dir / "mouse_movements.json").write_text(
                json.dumps({"total_behaviour": notation}), encoding="utf-8"
            )
        annotations.mkdir(parents=True)
        (annotations / "train").write_text("train-human human\n", encoding="utf-8")
        (annotations / "test").write_text("test-bot moderate_bot\n", encoding="utf-8")

        sessions = load_real_dataset(
            str(tmp_path), scenario=scenario, include_phase2=False, with_metadata=True
        )

        by_id = {session.session_id: session for session in sessions}
        assert by_id["train-human"].split == "train"
        assert by_id["train-human"].label == 0
        assert by_id["test-bot"].split == "test"
        assert by_id["test-bot"].label == 1
        assert all(session.source == "phase1" for session in sessions)

    def test_phase2_invalid_duplicate_does_not_hide_valid_session(self, tmp_path):
        data_dir = tmp_path / "phase2" / "data" / "mouse_movements" / "humans"
        data_dir.mkdir(parents=True)
        data_file = data_dir / "mouse_movements_humans.json"
        invalid = {
            "session_id": "same-session",
            "mousemove_total_behaviour": "[m(1,1)]",
        }
        valid = {
            "session_id": "same-session",
            "mousemove_total_behaviour": "".join(f"[m({i},{i})]" for i in range(12)),
        }
        data_file.write_text(
            "\n".join([json.dumps(invalid), json.dumps(valid)]), encoding="utf-8"
        )

        sessions = load_phase2_dataset(str(tmp_path), with_metadata=True)

        assert len(sessions) == 1
        assert sessions[0].session_id == "same-session"
        assert len(sessions[0].records) == 12

    def test_phase2_rejects_duplicate_session_id_with_conflicting_labels(self, tmp_path):
        notation = "".join(f"[m({i},{i})]" for i in range(12))
        record = json.dumps(
            {"session_id": "shared-session", "mousemove_total_behaviour": notation}
        )
        human_dir = tmp_path / "phase2" / "data" / "mouse_movements" / "humans"
        bot_dir = tmp_path / "phase2" / "data" / "mouse_movements" / "bots"
        human_dir.mkdir(parents=True)
        bot_dir.mkdir(parents=True)
        (human_dir / "mouse_movements_humans.json").write_text(record, encoding="utf-8")
        (bot_dir / "mouse_movements_moderate_bots.json").write_text(record, encoding="utf-8")

        with pytest.raises(ValueError, match="Conflicting labels"):
            load_phase2_dataset(
                str(tmp_path), scenario="humans_and_moderate_bots", with_metadata=True
            )

    def test_phase2_long_sessions_keep_recent_tail(self, tmp_path):
        data_dir = tmp_path / "phase2" / "data" / "mouse_movements" / "humans"
        data_dir.mkdir(parents=True)
        point_count = 5002
        record = {
            "session_id": "long-session",
            "mousemove_total_behaviour": "".join(f"[m({i % 100},{i % 100})]" for i in range(point_count)),
            "mousemove_times": ",".join(str(i) for i in range(point_count)),
        }
        (data_dir / "mouse_movements_humans.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

        sessions = load_phase2_dataset(str(tmp_path), with_metadata=True)

        assert len(sessions[0].records) == 5000
        assert sessions[0].records[0]["time"] == 2

    def test_phase2_invalid_timestamp_does_not_shift_later_events(self):
        record = {
            "mousemove_total_behaviour": "[m(10,10)][m(20,20)][m(30,30)]",
            "mousemove_times": "1000,invalid,1040",
            "mousemove_client_height_width": "(100,100)",
        }

        records = parse_phase2_record(record)

        assert [item["time"] for item in records] == [0, 13, 40]

    def test_phase2_preserves_event_order_when_timestamps_move_backwards(self):
        record = {
            "mousemove_total_behaviour": "[m(10,10)][m(20,20)][m(30,30)]",
            "mousemove_times": "1000,900,1100",
            "mousemove_client_height_width": "(100,100)",
        }

        records = parse_phase2_record(record)

        assert [item["time"] for item in records] == [0, 0, 100]
        assert [item["x"] for item in records] == [0.1, 0.2, 0.3]

    def test_dataset_parsers_skip_non_finite_coordinates(self):
        phase1 = parse_movement_notation("[m(nan,10)][m(20,20)]")
        phase2 = parse_phase2_record({
            "mousemove_total_behaviour": "[m(inf,10)][m(20,20)]",
            "mousemove_times": "1000,1020",
            "mousemove_client_height_width": "(100,100)",
        })

        assert len(phase1) == 1
        assert len(phase2) == 1
        assert phase1[0]["x"] >= 0
        assert phase2[0]["x"] == 0.2

    def test_loader_rejects_duplicate_trajectory_with_conflicting_labels(self, tmp_path):
        scenario = "humans_and_moderate_bots"
        data_root = tmp_path / "phase1" / "data" / "mouse_movements" / scenario
        annotations = tmp_path / "phase1" / "annotations" / scenario
        notation = "".join(f"[m({100 + i},{200 + i})]" for i in range(12))
        for session_id in ("human", "bot"):
            session_dir = data_root / session_id
            session_dir.mkdir(parents=True)
            (session_dir / "mouse_movements.json").write_text(
                json.dumps({"total_behaviour": notation}), encoding="utf-8"
            )
        annotations.mkdir(parents=True)
        (annotations / "train").write_text("human human\nbot moderate_bot\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Conflicting labels"):
            load_real_dataset(
                str(tmp_path), scenario=scenario, include_phase2=False, with_metadata=True
            )
