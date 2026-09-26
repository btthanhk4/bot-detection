import pytest

from core_ml.evaluate import classification_metrics, prefix_through_moves


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
