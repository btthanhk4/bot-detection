import pytest

from core_ml.evaluate_mouse_domain import FEATURES, summarize_group


def test_domain_summary_counts_sessions_and_excludes_out_of_domain_scores():
    def row(verdict, speed, in_domain):
        return {
            "verdict": verdict,
            "features": {key: (speed if key == "mean_speed" else 0.0) for key in FEATURES},
            "breakdown": {
                "risk_score_in_domain": in_domain,
                "behavioral_lstm_score": 0.8 if in_domain else 0.5,
                "tabular_score": 0.7 if in_domain else 0.5,
            },
        }

    summary = summarize_group([
        row("SUSPECT", 0.2, True),
        row("HUMAN", 0.4, False),
        row("SUSPECT", 0.6, True),
    ])
    assert summary["sessions"] == 3
    assert summary["verdicts"] == {"HUMAN": 1, "SUSPECT": 2}
    assert summary["feature_medians"]["mean_speed"] == 0.4
    assert summary["model_score_medians"] == {
        "behavioral_lstm_score": 0.8, "tabular_score": 0.7,
    }


def test_domain_summary_requires_labeled_sessions():
    with pytest.raises(ValueError, match="At least one"):
        summarize_group([])
