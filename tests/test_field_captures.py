import json

import numpy as np
import pytest
import torch

from core_ml.dataset.field_captures import (
    capture_training_windows,
    evaluate_bot_captures,
    load_bot_captures,
)
from core_ml.train import main as train_main, train_lstm
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM


def _payload(count, action="heartbeat", session_id="sess-1"):
    return {
        "sessionId": session_id,
        "action": action,
        "mouse": {"records": [
            {"time": i * 11, "x": i / 100, "y": 0.3, "type": "move", "source": "mouse"}
            for i in range(count)
        ]},
        "botd": {"heuristicScore": 0.0},
    }


def _write(path, capture_id="run-1", label="BOT", family="heavy", session_id="sess-1"):
    path.write_text(json.dumps({
        "schema": "bot-mouse-capture-v1",
        "captureId": capture_id,
        "label": label,
        "family": family,
        "snapshots": [
            _payload(25, session_id=session_id),
            _payload(40, session_id=session_id),
            _payload(40, "test-probe", session_id=session_id),
        ],
    }), encoding="utf-8")


def test_capture_windows_deduplicate_but_keep_one_browser_run(tmp_path):
    _write(tmp_path / "a.json")
    runs = load_bot_captures(str(tmp_path))
    assert len(runs) == 1
    assert runs[0].family == "heavy"
    assert len(capture_training_windows(runs[0])) == 2
    assert len(runs[0].final_payload["mouse"]["records"]) == 40

    class Detector:
        def predict(self, payload):
            return {"verdict": "HUMAN" if payload["action"] == "test-probe" else "BOT"}

    report = evaluate_bot_captures(Detector(), runs)
    assert report["runs"] == 1
    assert report["families"]["heavy"] == {
        "runs": 1, "final_bot": 1, "final_human": 0, "final_suspect": 0,
        "ever_human": 0, "ever_bot": 1,
        "probe_bot": 0, "probe_human": 1,
        "final_suspect_reasons": {},
    }


def test_capture_report_counts_final_suspect_reasons_once_per_run(tmp_path):
    _write(tmp_path / "a.json")
    _write(tmp_path / "b.json", capture_id="run-2", family="scrub", session_id="sess-2")
    runs = load_bot_captures(str(tmp_path))

    class Detector:
        def predict(self, payload):
            return {
                "verdict": "SUSPECT",
                "breakdown": {"suspect_reason_codes": [
                    "INSUFFICIENT_MOUSE", "CLIENT_AUTOMATION_SIGNAL",
                ]},
            }

    report = evaluate_bot_captures(Detector(), runs)
    assert report["runs"] == 2
    for family in ("heavy", "scrub"):
        assert report["families"][family]["final_suspect"] == 1
        assert report["families"][family]["final_suspect_reasons"] == {
            "CLIENT_AUTOMATION_SIGNAL": 1, "INSUFFICIENT_MOUSE": 1,
        }


def test_capture_loader_rejects_false_labels_and_duplicate_runs(tmp_path):
    _write(tmp_path / "a.json", label="HUMAN")
    with pytest.raises(ValueError, match="Invalid label"):
        load_bot_captures(str(tmp_path))
    _write(tmp_path / "a.json")
    _write(tmp_path / "b.json")
    with pytest.raises(ValueError, match="duplicate capture ID"):
        load_bot_captures(str(tmp_path))


def test_capture_loader_rejects_oversized_collector_window(tmp_path):
    _write(tmp_path / "a.json")
    path = tmp_path / "a.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture["snapshots"][0] = _payload(101)
    path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid collector window"):
        load_bot_captures(str(tmp_path))


def test_capture_replays_observed_user_agent_not_client_claim(tmp_path):
    _write(tmp_path / "a.json")
    path = tmp_path / "a.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture["snapshots"][0]["_server_user_agent"] = "HeadlessChrome/forged"
    capture["serverUserAgents"] = ["Chrome/normal", "HeadlessChrome/observed", "Chrome/probe"]
    path.write_text(json.dumps(capture), encoding="utf-8")
    run = load_bot_captures(str(tmp_path))[0]
    assert run.sent_snapshots[0]["_server_user_agent"] == "Chrome/normal"
    assert run.final_payload["_server_user_agent"] == "HeadlessChrome/observed"
    assert run.probe_payload["_server_user_agent"] == "Chrome/probe"


def test_capture_rejects_misaligned_observed_headers(tmp_path):
    _write(tmp_path / "a.json")
    path = tmp_path / "a.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture["serverUserAgents"] = ["Chrome/only-one"]
    path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(ValueError, match="observed User-Agent"):
        load_bot_captures(str(tmp_path))


@pytest.mark.parametrize("invalid_action", ["heartbeat", "test-final"])
def test_capture_rejects_missing_final_probe(tmp_path, invalid_action):
    _write(tmp_path / "a.json")
    path = tmp_path / "a.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture["snapshots"][-1]["action"] = invalid_action
    path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(ValueError, match="test-probe"):
        load_bot_captures(str(tmp_path))


def test_capture_rejects_mixed_sessions(tmp_path):
    _write(tmp_path / "a.json")
    path = tmp_path / "a.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture["snapshots"][1]["sessionId"] = "sess-other"
    path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(ValueError, match="one session"):
        load_bot_captures(str(tmp_path))


def test_capture_rejects_same_session_in_multiple_files(tmp_path):
    _write(tmp_path / "a.json", capture_id="run-1", family="heavy")
    _write(tmp_path / "b.json", capture_id="run-2", family="scrub")
    with pytest.raises(ValueError, match="Duplicate session ID"):
        load_bot_captures(str(tmp_path))


def test_field_training_cannot_target_production_bundle(tmp_path):
    with pytest.raises(ValueError, match="diagnostic-only"):
        train_main(capture_dir=str(tmp_path), weights_dir=str(tmp_path / "weights"))


def test_tabular_training_rejects_invalid_capture_weights():
    classifier = TabularBotClassifier()
    X = np.asarray([[0.0], [1.0]], dtype=np.float32)
    y = np.asarray([0, 1])
    with pytest.raises(ValueError, match="Sample weights"):
        classifier.fit(X, y, sample_weight=np.asarray([1.0, -1.0]))


def test_lstm_training_accepts_session_weights_and_rejects_invalid_values():
    model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
    X = torch.zeros(4, 24, 8)
    y = torch.tensor([0.0, 1.0, 0.0, 1.0])
    with pytest.raises(ValueError, match="sample weights"):
        train_lstm(model, X, y, X[:2], y[:2], sample_weight=[1, 0, 1, 1])
    train_lstm(
        model, X, y, X[:2], y[:2], epochs=1, batch_size=2, device="cpu",
        sample_weight=[1, 4, 1, 4],
    )
