import numpy as np
import pytest
import torch

from core_ml.dataset.loader import RealMouseSession
from core_ml.train import (
    assign_real_session_splits,
    deduplicate_real_sessions,
    predict_lstm_sessions,
    resolve_training_indices,
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


def test_experiments_do_not_mix_invalid_official_test_back_into_training():
    labels = np.array([0, 1, 0, 1, 0])
    splits = np.array(["train", "train", "val", "val", "test"])

    with pytest.raises(ValueError, match="Official test split"):
        get_experiment_indices(labels, splits)
