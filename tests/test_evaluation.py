import pytest

from core_ml.evaluate import classification_metrics, prefix_through_moves
from core_ml.evaluate_robustness import evaluate_robustness
from core_ml.dataset.loader import RealMouseSession


def test_classification_metrics_reports_operational_error_rates():
    metrics = classification_metrics(
        [0, 0, 1, 1],
        [0.1, 0.8, 0.9, 0.2],
        threshold=0.7,
    )

    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_negative_rate"] == 0.5
    assert 0 <= metrics["pr_auc"] <= 1
    assert 0 <= metrics["brier_score"] <= 1


@pytest.mark.parametrize(
    "labels, probabilities",
    [([], []), ([0, 1], [0.1]), ([0, 1], [0.1, float("nan")])],
)
def test_classification_metrics_rejects_invalid_evaluation_data(labels, probabilities):
    with pytest.raises(ValueError):
        classification_metrics(labels, probabilities, threshold=0.7)


def test_classification_metrics_supports_human_only_false_positive_audit():
    metrics = classification_metrics([0, 0], [0.1, 0.8], threshold=0.7)

    assert metrics["roc_auc"] is None
    assert metrics["pr_auc"] is None
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 0, "tp": 0}


def test_classification_metrics_uses_actual_policy_decisions():
    metrics = classification_metrics(
        [0, 1], [0.95, 0.99], threshold=0.7, predictions=[False, True]
    )

    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 0, "fn": 0, "tp": 1}
    assert metrics["false_positive_rate"] == 0


def test_classification_metrics_rejects_misaligned_decisions():
    with pytest.raises(ValueError, match="Predictions"):
        classification_metrics([0, 1], [0.2, 0.9], 0.7, predictions=[True])


def test_prefix_through_moves_keeps_interleaved_events():
    records = [
        {"type": "down"}, {"type": "move", "x": 1},
        {"type": "click"}, {"type": "move", "x": 2}, {"type": "up"},
    ]

    assert prefix_through_moves(records, 2) == records[:4]
    with pytest.raises(ValueError, match="positive integer"):
        prefix_through_moves(records, 0)


def test_robustness_report_counts_verdicts_by_session(monkeypatch):
    from core_ml import evaluate_robustness as module

    class Detector:
        def predict(self, telemetry):
            records = telemetry["mouse"]["records"]
            return {"verdict": "BOT" if records[0]["x"] > 0.5 else "HUMAN"}

    sessions = [
        RealMouseSession(
            records=[{"time": i * 10, "x": x, "y": 0.2, "type": "move"} for i in range(30)],
            label=label, session_id=str(label), source="phase2", split="val", scenario="test",
        )
        for label, x in ((0, 0.1), (1, 0.9))
    ]
    monkeypatch.setattr(module, "load_real_dataset", lambda *_args, **kwargs: sessions if kwargs["scenario"] == "humans_and_moderate_bots" else [])
    monkeypatch.setattr(module, "assign_real_session_splits", lambda _sessions: ["val", "val"])
    monkeypatch.setattr(module, "_load_detector", lambda *_args: (Detector(), {"bundle_id": "candidate", "training": {}}))

    report = evaluate_robustness("unused", "unused", checkpoints=2)
    assert report["session_counts"] == {"human": 1, "bot": 1}
    assert report["rolling_windows"] == {"human": {"HUMAN": 2}, "bot": {"BOT": 2}}
    assert report["human_sessions_ever_bot"] == 0
    assert report["bot_sessions_ever_human"] == 0
    assert report["verdict_transitions"] == {"human": {}, "bot": {}}


def test_robustness_reports_only_within_session_verdict_transitions(monkeypatch):
    from core_ml import evaluate_robustness as module

    class Detector:
        def predict(self, telemetry):
            moves = len(telemetry["mouse"]["records"])
            return {"verdict": "SUSPECT" if moves <= 25 else "HUMAN"}

    sessions = [RealMouseSession(
        records=[{"time": i * 10, "x": i / 30, "y": 0.2, "type": "move"} for i in range(30)],
        label=0, session_id="human", source="phase2", split="val", scenario="test",
    )]
    monkeypatch.setattr(module, "load_real_dataset", lambda *_args, **kwargs: sessions if kwargs["scenario"] == "humans_and_moderate_bots" else [])
    monkeypatch.setattr(module, "assign_real_session_splits", lambda _sessions: ["val"])
    monkeypatch.setattr(module, "_load_detector", lambda *_args: (Detector(), {"bundle_id": "candidate", "training": {}}))

    report = evaluate_robustness("unused", "unused", checkpoints=2)
    assert report["verdict_transitions"] == {"human": {"SUSPECT->HUMAN": 1}, "bot": {}}
    with pytest.raises(ValueError, match="suspect_threshold"):
        evaluate_robustness("unused", "unused", suspect_threshold=1.0)


def test_robustness_routes_browser_signals_to_each_prediction(monkeypatch):
    from core_ml import evaluate_robustness as module

    received = []

    class Detector:
        def predict(self, telemetry):
            received.append(telemetry["botd"])
            return {"verdict": "SUSPECT"}

    sessions = [RealMouseSession(
        records=[{"time": i * 10, "x": i / 30, "y": 0.2, "type": "move"} for i in range(30)],
        label=0, session_id="human", source="phase2", split="val", scenario="test",
    )]
    monkeypatch.setattr(module, "load_real_dataset", lambda *_args, **kwargs: sessions if kwargs["scenario"] == "humans_and_moderate_bots" else [])
    monkeypatch.setattr(module, "assign_real_session_splits", lambda _sessions: ["val"])
    monkeypatch.setattr(module, "_load_detector", lambda *_args: (Detector(), {"bundle_id": "candidate", "training": {}}))

    report = evaluate_robustness("unused", "unused", checkpoints=2, heuristic_score=0.6, webdriver=True)
    assert report["heuristic_score"] == 0.6
    assert report["webdriver"] is True
    assert len(received) == 5
    assert all(signal == {"heuristicScore": 0.6, "detectors": {"webdriver": True}} for signal in received)
    with pytest.raises(ValueError, match="heuristic_score"):
        evaluate_robustness("unused", "unused", heuristic_score=float("nan"))
