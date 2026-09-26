"""Evaluate a frozen production model bundle without fitting on evaluation data."""

import argparse
import json
import os
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from core_ml.dataset.loader import load_real_dataset
from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES, prefix_through_moves
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.model_bundle import verify_model_bundle
from core_ml.train import (
    PRODUCTION_DECISION_THRESHOLD,
    assign_real_session_splits,
    deduplicate_real_sessions,
    records_signature,
)


def classification_metrics(labels, probabilities, threshold: float, predictions=None) -> dict:
    """Return threshold-dependent and ranking metrics for binary detection."""
    y_true = np.asarray(labels, dtype=int)
    y_score = np.asarray(probabilities, dtype=float)
    if y_true.ndim != 1 or y_score.ndim != 1 or len(y_true) != len(y_score):
        raise ValueError("Labels and probabilities must be aligned one-dimensional arrays")
    observed_labels = set(np.unique(y_true).tolist())
    if len(y_true) == 0 or not observed_labels.issubset({0, 1}):
        raise ValueError("Evaluation labels must contain only zero and one")
    if not np.all(np.isfinite(y_score)) or np.any((y_score < 0) | (y_score > 1)):
        raise ValueError("Probabilities must be finite values between zero and one")
    if not 0 <= threshold <= 1:
        raise ValueError("Threshold must be between zero and one")

    y_pred = (
        np.asarray(predictions)
        if predictions is not None
        else (y_score >= threshold).astype(int)
    )
    if y_pred.shape != y_true.shape or not np.isin(y_pred, [0, 1]).all():
        raise ValueError("Predictions must be aligned binary labels")
    y_pred = y_pred.astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    has_both_labels = observed_labels == {0, 1}
    return {
        "threshold": float(threshold),
        "roc_auc": float(roc_auc_score(y_true, y_score)) if has_both_labels else None,
        "pr_auc": float(average_precision_score(y_true, y_score)) if has_both_labels else None,
        "brier_score": float(brier_score_loss(y_true, y_score)),
        "accuracy": float(np.mean(y_pred == y_true)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "false_positive_rate": float(fp / max(1, fp + tn)),
        "false_negative_rate": float(fn / max(1, fn + tp)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def _load_detector(weights_dir: str, threshold: float) -> tuple[EnsembleBotDetector, dict]:
    feature_names = list(ENV_FEATURE_NAMES) + list(STATISTICAL_FEATURE_NAMES)
    manifest = verify_model_bundle(weights_dir, feature_names)
    tabular = TabularBotClassifier()
    lstm = MouseTrajectoryLSTM()
    if not tabular.load(
        os.path.join(weights_dir, "tabular_model.joblib"),
        expected_feature_names=feature_names,
    ):
        raise RuntimeError("Tabular artifact could not be loaded")
    if not lstm.load_weights(os.path.join(weights_dir, "behavioral_lstm.pt")):
        raise RuntimeError("LSTM artifact could not be loaded")
    return EnsembleBotDetector(
        tabular_model=tabular,
        lstm_model=lstm,
        threshold=threshold,
        suspect_threshold=min(0.45, threshold),
        tabular_available=True,
        lstm_available=True,
    ), manifest


def evaluate_dataset(
    dataset_root: str,
    weights_dir: str,
    *,
    split: str = "all",
    threshold: float = PRODUCTION_DECISION_THRESHOLD,
    allow_training_overlap: bool = False,
    max_move_points: int = None,
) -> dict:
    """Evaluate a model bundle and reject overlap with its training trajectories."""
    sessions = []
    for scenario in ("humans_and_moderate_bots", "humans_and_advanced_bots"):
        sessions.extend(
            load_real_dataset(
                dataset_root,
                scenario=scenario,
                include_phase2=True,
                with_metadata=True,
            )
        )
    sessions = deduplicate_real_sessions(sessions)
    assignments = assign_real_session_splits(sessions)
    selected = [
        session
        for session, assignment in zip(sessions, assignments)
        if split == "all" or assignment == split
    ]
    if not selected:
        raise ValueError(f"No sessions found for evaluation split {split!r}")
    if max_move_points is not None and (type(max_move_points) is not int or max_move_points < 1):
        raise ValueError("max_move_points must be a positive integer")

    detector, manifest = _load_detector(weights_dir, threshold)
    hashes_by_split = (
        manifest.get("training", {})
        .get("dataset", {})
        .get("trajectory_hashes_by_split", {})
    )
    training_hashes = set(hashes_by_split.get("train", []))
    known_bundle_hashes = {
        signature
        for hashes in hashes_by_split.values()
        for signature in hashes
    }
    selected_hashes = {records_signature(session.records) for session in selected}
    overlap = sorted(training_hashes & selected_hashes)
    known_overlap_count = len(known_bundle_hashes & selected_hashes)
    if overlap and not allow_training_overlap:
        raise ValueError(
            f"Evaluation data overlaps {len(overlap)} training trajectories; "
            "use an independent dataset or explicitly allow the diagnostic run"
        )

    labels = []
    probabilities = []
    predictions = []
    deferred_count = 0
    for session in selected:
        records = (
            session.records if max_move_points is None
            else prefix_through_moves(session.early_records or session.records, max_move_points)
        )
        result = detector.predict({
            "sessionId": session.session_id,
            "fingerprint": {},
            "botd": {"heuristicScore": 0.0, "detectors": {}, "reasons": []},
            "mouse": {"records": records},
        })
        labels.append(session.label)
        probabilities.append(result["bot_probability"])
        predictions.append(result["is_bot"])
        deferred_count += result["decision_state"] == "INSUFFICIENT_EVIDENCE"

    metrics = classification_metrics(labels, probabilities, threshold, predictions)
    metrics["deferred_count"] = deferred_count
    metrics["decision_coverage"] = 1.0 - deferred_count / len(selected)

    return {
        "bundle_id": manifest.get("bundle_id"),
        "decision_policy_version": DECISION_POLICY_VERSION,
        "dataset_name": Path(dataset_root).resolve().name,
        "evaluation_kind": (
            "external"
            if known_overlap_count == 0
            else "heldout_same_dataset"
            if known_overlap_count == len(selected_hashes)
            else "mixed_known_and_external"
        ),
        "split": split,
        "max_move_points": max_move_points,
        "session_count": len(selected),
        "human_count": int(labels.count(0)),
        "bot_count": int(labels.count(1)),
        "training_overlap_count": len(overlap),
        "known_bundle_dataset_overlap_count": known_overlap_count,
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate a frozen bot-detection model bundle")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument(
        "--weights-dir",
        default=os.path.join(os.path.dirname(__file__), "weights"),
    )
    parser.add_argument("--split", choices=("all", "train", "val", "test"), default="all")
    parser.add_argument("--threshold", type=float, default=PRODUCTION_DECISION_THRESHOLD)
    parser.add_argument("--max-move-points", type=int, default=None)
    parser.add_argument("--allow-training-overlap", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = evaluate_dataset(
        args.dataset_root,
        args.weights_dir,
        split=args.split,
        threshold=args.threshold,
        allow_training_overlap=args.allow_training_overlap,
        max_move_points=args.max_move_points,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
