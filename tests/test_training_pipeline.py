import numpy as np
import pytest
import torch

from core_ml.dataset.loader import RealMouseSession
from core_ml.train import (
    assign_real_session_splits,
    deduplicate_real_sessions,
    predict_lstm_sessions,
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
