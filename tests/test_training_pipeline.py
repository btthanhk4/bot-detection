import json

import numpy as np
import pytest
import torch

from core_ml.dataset.loader import RealMouseSession
from core_ml.train import (
    audit_training_dataset,
    assign_real_session_splits,
    deduplicate_real_sessions,
    predict_lstm_sessions,
    publish_model_artifacts,
    resolve_training_device,
    resolve_training_indices,
    train_lstm,
)
from core_ml.experiments.run_all import (
    experiment_inference_latency,
    get_experiment_indices,
    get_fit_validation_indices,
    to_json_safe,
    truncate_moves,
)


def _session(session_id, label, source="phase2", split="unspecified", records=None):
    return RealMouseSession(
        records=records or [{"time": 0, "x": 0.1, "y": 0.2, "type": "move"}],
        label=label,
        session_id=session_id,
        source=source,
        split=split,
        scenario="test",
    )


def test_split_preserves_official_test_and_is_deterministic():
    sessions = [_session("official", 0, "phase1", "test")]
    sessions += [_session(f"human-{i}", 0) for i in range(20)]
    sessions += [_session(f"bot-{i}", 1) for i in range(20)]

    first = assign_real_session_splits(sessions)
    second = assign_real_session_splits(list(reversed(sessions)))
    reverse_map = {session.session_id: split for session, split in zip(reversed(sessions), second)}

    assert first[0] == "test"
    assert {session.session_id: split for session, split in zip(sessions, first)} == reverse_map
    assert set(first[1:]) == {"train", "val", "test"}


def test_deduplication_rejects_conflicting_labels():
    records = [{"time": 0, "x": 0.1, "y": 0.2, "type": "move"}]
    with pytest.raises(ValueError, match="Conflicting labels"):
        deduplicate_real_sessions([
            _session("human", 0, records=records),
            _session("bot", 1, records=records),
        ])


def test_lstm_metrics_are_aggregated_per_session():
    class MeanModel:
        def predict_session_proba(self, chunks):
            return float(chunks[:, 0, 0].mean())

    chunks = torch.zeros(3, 24, 8)
    chunks[0, 0, 0] = 0.2
    chunks[1, 0, 0] = 0.4
    chunks[2, 0, 0] = 0.9
    labels, probabilities = predict_lstm_sessions(
        MeanModel(), chunks, [10, 10, 20], [10, 20, 30], np.array([0] * 10 + [1] * 11)
    )

    assert labels.tolist() == [1, 1]
    assert probabilities.tolist() == pytest.approx([0.3, 0.9])


def test_experiments_share_published_test_split():
    y = np.array([0, 1, 0, 1, 0, 1])
    splits = np.array(["train", "train", "val", "val", "test", "test"])

    train_idx, test_idx = get_experiment_indices(y, splits)

    assert train_idx.tolist() == [0, 1, 2, 3]
    assert test_idx.tolist() == [4, 5]


def test_experiment_validation_falls_back_when_published_train_has_one_label():
    labels = np.array([0, 0, 1, 1, 0, 1, 0, 1])
    splits = np.array(["train", "train", "val", "val", "train", "train", "test", "test"])
    shared_train, _ = get_experiment_indices(labels, splits)

    fit_idx, val_idx = get_fit_validation_indices(labels, splits, shared_train)

    assert set(fit_idx).isdisjoint(val_idx)
    assert set(fit_idx) | set(val_idx) == set(shared_train)
    assert set(labels[fit_idx]) == {0, 1}
    assert set(labels[val_idx]) == {0, 1}


def test_latency_benchmark_rejects_empty_feature_matrix():
    with pytest.raises(ValueError, match="non-empty 2D"):
        experiment_inference_latency(np.empty((0, 3)), object(), iterations=1, warmup_runs=0)


def test_truncate_moves_filters_non_move_and_malformed_records():
    records = [
        {"type": "down", "x": 1},
        None,
        {"type": "move", "x": 2},
        {"type": "move", "x": 3},
    ]

    assert truncate_moves(records, 1) == [{"type": "move", "x": 2}]


def test_experiment_results_are_strict_json_safe():
    converted = to_json_safe({"thresholds": np.array([float("inf"), np.float32(0.5)])})

    assert converted == {"thresholds": [None, 0.5]}


def test_training_split_recovers_when_real_validation_and_test_are_missing():
    labels = np.array([0, 1] * 20)
    splits = np.array(["train"] * len(labels))

    train_idx, val_idx, test_idx = resolve_training_indices(labels, splits)

    assert set(train_idx).isdisjoint(val_idx)
    assert set(train_idx).isdisjoint(test_idx)
    assert set(val_idx).isdisjoint(test_idx)
    assert set(labels[val_idx]) == {0, 1}
    assert set(labels[test_idx]) == {0, 1}


def test_training_rejects_one_class_official_test_instead_of_reporting_fake_auc():
    labels = np.array([0, 1, 0, 1, 0])
    splits = np.array(["train", "train", "val", "val", "test"])

    with pytest.raises(ValueError, match="too small or imbalanced"):
        resolve_training_indices(labels, splits)


def test_training_device_selection_is_explicit(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    assert resolve_training_device("auto").type == "cpu"
    assert resolve_training_device("cpu").type == "cpu"
    with pytest.raises(RuntimeError, match="CUDA was requested"):
        resolve_training_device("cuda")
    with pytest.raises(ValueError, match="auto, cpu, cuda"):
        resolve_training_device("quantum")


def test_lstm_training_keeps_cpu_runtime_supported():
    from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM

    model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
    X_train = torch.zeros(4, 24, 8)
    y_train = torch.tensor([0.0, 1.0, 0.0, 1.0])
    X_val = torch.ones(2, 24, 8)
    y_val = torch.tensor([0.0, 1.0])

    train_lstm(
        model,
        X_train,
        y_train,
        X_val,
        y_val,
        epochs=1,
        batch_size=2,
        patience=1,
        device="cpu",
    )

    assert next(model.parameters()).device.type == "cpu"


def test_model_artifacts_are_published_as_a_pair(tmp_path):
    class Artifact:
        def __init__(self, content):
            self.content = content

        def save(self, path):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(self.content)

        def save_weights(self, path):
            self.save(path)

    publish_model_artifacts(
        Artifact("tabular-new"),
        Artifact("lstm-new"),
        str(tmp_path),
        feature_names=["feature-a"],
        training_metadata={"dataset": {"session_count": 2}},
    )

    assert (tmp_path / "tabular_model.joblib").read_text() == "tabular-new"
    assert (tmp_path / "behavioral_lstm.pt").read_text() == "lstm-new"
    manifest = json.loads((tmp_path / "model_manifest.json").read_text())
    assert manifest["feature_names"] == ["feature-a"]
    assert manifest["training"]["dataset"]["session_count"] == 2
    assert set(manifest["artifacts"]) == {
        "tabular_model.joblib",
        "behavioral_lstm.pt",
    }


def test_model_artifact_staging_failure_preserves_existing_pair(tmp_path):
    class TabularArtifact:
        def save(self, path):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("tabular-new")

    class BrokenLstmArtifact:
        def save_weights(self, _path):
            raise RuntimeError("save failed")

    tabular_path = tmp_path / "tabular_model.joblib"
    lstm_path = tmp_path / "behavioral_lstm.pt"
    tabular_path.write_text("tabular-old")
    lstm_path.write_text("lstm-old")

    with pytest.raises(RuntimeError, match="save failed"):
        publish_model_artifacts(TabularArtifact(), BrokenLstmArtifact(), str(tmp_path))

    assert tabular_path.read_text() == "tabular-old"
    assert lstm_path.read_text() == "lstm-old"
    assert not list(tmp_path.glob("*.tmp"))


def test_dataset_audit_is_deterministic_and_counts_sources():
    telemetry = [
        {"sessionId": "synthetic_1", "mouse": {"records": [{"x": 1}]}},
        {"sessionId": "real_1", "mouse": {"records": [{"x": 2}]}},
    ]

    first = audit_training_dataset(telemetry, [0, 1], ["train", "test"])
    second = audit_training_dataset(
        list(reversed(telemetry)), [1, 0], ["test", "train"]
    )

    assert first == second
    assert first["session_count"] == 2
    assert first["source_counts"] == {"real": 1, "synthetic": 1}


def test_dataset_audit_rejects_cross_split_trajectory_leakage():
    records = [{"time": 0, "x": 0.1, "y": 0.2, "type": "move"}]
    telemetry = [
        {"sessionId": "one", "mouse": {"records": records}},
        {"sessionId": "two", "mouse": {"records": records}},
    ]

    with pytest.raises(ValueError, match="leakage"):
        audit_training_dataset(telemetry, [0, 0], ["train", "test"])


def test_dataset_audit_rejects_conflicting_labels():
    records = [{"time": 0, "x": 0.1, "y": 0.2, "type": "move"}]
    telemetry = [
        {"sessionId": "one", "mouse": {"records": records}},
        {"sessionId": "two", "mouse": {"records": records}},
    ]

    with pytest.raises(ValueError, match="Conflicting labels"):
        audit_training_dataset(telemetry, [0, 1], ["train", "train"])


def test_experiments_do_not_mix_invalid_official_test_back_into_training():
    labels = np.array([0, 1, 0, 1, 0])
    splits = np.array(["train", "train", "val", "val", "test"])

    with pytest.raises(ValueError, match="Official test split"):
        get_experiment_indices(labels, splits)
