"""Compare collector-window mouse behavior across labeled data sources."""

import argparse
import json
from collections import Counter, defaultdict
from statistics import median

from core_ml.collector_windows import export_window
from core_ml.dataset.field_captures import load_bot_captures, load_human_captures
from core_ml.dataset.loader import load_real_dataset
from core_ml.evaluate import _load_detector
from core_ml.features.mouse_features import compute_statistical_features
from core_ml.train import (
    PRODUCTION_DECISION_THRESHOLD,
    deduplicate_real_sessions,
)


FEATURES = (
    "mean_speed",
    "time_regularity",
    "curvature_mean",
    "velocity_autocorrelation",
    "idle_time_ratio",
    "straightness",
)


def summarize_group(rows: list[dict]) -> dict:
    """Aggregate by session, not by correlated collector snapshots."""
    if not rows:
        raise ValueError("At least one labeled session is required")
    score_medians = {}
    for key in ("behavioral_lstm_score", "tabular_score"):
        values = [
            row["breakdown"][key] for row in rows
            if row["breakdown"].get("risk_score_in_domain")
        ]
        score_medians[key] = round(median(values), 4) if values else None
    return {
        "sessions": len(rows),
        "verdicts": dict(sorted(Counter(row["verdict"] for row in rows).items())),
        "feature_medians": {
            feature: round(median(row["features"][feature] for row in rows), 4)
            for feature in FEATURES
        },
        "model_score_medians": score_medians,
    }


def evaluate_mouse_domain(dataset_root: str, capture_dir: str, weights_dir: str,
                          human_capture_dir: str | None = None) -> dict:
    """Replay one final collector-sized window per independently labeled run."""
    detector, manifest = _load_detector(weights_dir, PRODUCTION_DECISION_THRESHOLD)
    sessions = []
    for scenario in ("humans_and_moderate_bots", "humans_and_advanced_bots"):
        sessions.extend(load_real_dataset(
            dataset_root, scenario=scenario, include_phase2=True, with_metadata=True,
        ))
    sessions = deduplicate_real_sessions(sessions)
    if not sessions:
        raise ValueError("No labeled real sessions were loaded")

    groups = defaultdict(list)
    for session in sessions:
        records = export_window(session.records, len(session.records) - 1)
        prediction = detector.predict({
            "fingerprint": {}, "botd": {"heuristicScore": 0},
            "mouse": {"records": records},
        })
        groups[f"{session.source}_{'bot' if session.label else 'human'}"].append({
            "verdict": prediction["verdict"],
            "breakdown": prediction["breakdown"],
            "features": compute_statistical_features(records),
        })

    captures = load_bot_captures(capture_dir)
    for capture in captures:
        payload = capture.final_payload
        prediction = detector.predict(payload)
        groups[f"browser_bot_{capture.family}"].append({
            "verdict": prediction["verdict"],
            "breakdown": prediction["breakdown"],
            "features": compute_statistical_features(payload["mouse"]["records"]),
        })

    if human_capture_dir:
        for capture in load_human_captures(human_capture_dir):
            payload = capture.final_payload
            prediction = detector.predict(payload)
            groups["browser_human"].append({
                "verdict": prediction["verdict"],
                "breakdown": prediction["breakdown"],
                "features": compute_statistical_features(payload["mouse"]["records"]),
            })

    return {
        "bundle_id": manifest["bundle_id"],
        "note": "Last collector window per labeled session; not a production accuracy estimate",
        "groups": {name: summarize_group(rows) for name, rows in sorted(groups.items())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--human-capture-dir")
    parser.add_argument("--weights-dir", default="core_ml/weights")
    args = parser.parse_args()
    print(json.dumps(evaluate_mouse_domain(
        args.dataset_root, args.capture_dir, args.weights_dir, args.human_capture_dir,
    ), indent=2, sort_keys=True))
