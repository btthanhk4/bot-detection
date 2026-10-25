"""Offline mouse-only ablation; never writes or promotes a production bundle."""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from xgboost import XGBClassifier

from core_ml.dataset.field_captures import capture_training_windows, load_bot_captures
from core_ml.dataset.loader import load_phase2_dataset
from core_ml.evaluate import _load_detector
from core_ml.features.env_features import FEATURE_NAMES as ENV_NAMES
from core_ml.features.interaction_features import extract_interaction_features
from core_ml.features.mouse_features import (
    STATISTICAL_FEATURE_NAMES, extract_mouse_stat_vector, sanitize_mouse_records,
)
from core_ml.train import (
    PRODUCTION_DECISION_THRESHOLD, PRODUCTION_SUSPECT_THRESHOLD,
    assign_real_session_splits, deduplicate_real_sessions, records_signature,
)


LOCAL_NAMES = (
    "move_window_speed_cv_min", "move_window_speed_cv_median",
    "move_window_straightness_max", "move_window_regular_line_score_max",
    "move_window_turn_cv_min",
)
FEATURE_NAMES = tuple(STATISTICAL_FEATURE_NAMES) + LOCAL_NAMES
PROTOCOL = "mouse_family_ablation_v1"
MODEL_PARAMS = dict(
    n_estimators=120, max_depth=4, learning_rate=0.05, subsample=0.8,
    colsample_bytree=0.8, min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
    eval_metric="logloss", random_state=42, n_jobs=1, tree_method="hist",
)


@dataclass
class MotionRun:
    run_id: str
    label: int
    family: str
    source: str
    split: str
    vectors: np.ndarray
    signatures: tuple[str, ...]
    excluded_windows: int


def generator_family(name):
    """Group fixed/jitter variants together, not by seed or capture filename."""
    for family in ("circular", "heavy-wander", "scrub-hover"):
        if name.startswith(f"stealth-{family}-"):
            return family
    raise ValueError(f"Unknown generator family; define its holdout group first: {name}")


def make_run(run_id, label, family, source, split, windows):
    if type(label) is not int or label not in (0, 1):
        raise ValueError("Independent binary labels are required")
    vectors, signatures, seen = [], [], set()
    excluded = 0
    for raw in windows:
        if any(isinstance(r, dict) and r.get("source") == "touch" for r in raw):
            excluded += 1
            continue
        records = sanitize_mouse_records(raw)
        moves = [r for r in records if r["type"] == "move"]
        if (len(moves) < 25 or len({(r["x"], r["y"]) for r in moves}) < 5
                or len({r["time"] for r in moves}) < 5):
            excluded += 1
            continue
        # Ignore clock origin and source metadata when auditing exact overlap.
        t0 = records[0]["time"]
        signature = records_signature([
            {"x": r["x"], "y": r["y"], "time": r["time"] - t0, "type": r["type"]}
            for r in records
        ])
        if signature in seen:
            continue
        seen.add(signature)
        local = extract_interaction_features({"records": records})["features"]
        vector = np.concatenate([extract_mouse_stat_vector(records), [
            np.nan if local[name] is None else local[name] for name in LOCAL_NAMES
        ]]).astype(np.float32)
        if np.isinf(vector).any():
            raise ValueError("Infinite feature values are not permitted")
        vectors.append(vector)
        signatures.append(signature)
    matrix = np.asarray(vectors, dtype=np.float32).reshape(-1, len(FEATURE_NAMES))
    return MotionRun(run_id, label, family, source, split, matrix, tuple(signatures), excluded)


def audit_partitions(partitions):
    """Fail closed on session overlap, exact-window leakage or label conflicts."""
    ids, windows, manifest = {}, {}, []
    for split, runs in partitions.items():
        for run in runs:
            if run.run_id in ids:
                raise ValueError("Session overlap across or within partitions")
            ids[run.run_id] = split
            for signature in run.signatures:
                previous = windows.get(signature)
                if previous and previous != (split, run.label):
                    raise ValueError("Window leakage or conflicting trajectory labels")
                windows[signature] = (split, run.label)
            manifest.append((split, run.run_id, run.label, run.signatures))
    return hashlib.sha256(json.dumps(sorted(manifest)).encode("utf-8")).hexdigest()


def training_matrix(runs, feature_count):
    eligible = [run for run in runs if len(run.vectors)]
    counts = Counter(run.label for run in eligible)
    if set(counts) != {0, 1}:
        raise ValueError("Training requires eligible sessions from both labels")
    rows = sum(len(run.vectors) for run in eligible)
    weights = np.concatenate([
        np.full(len(run.vectors), rows / (2 * counts[run.label] * len(run.vectors)))
        for run in eligible
    ])
    return (
        np.concatenate([r.vectors[:, :feature_count] for r in eligible]),
        np.concatenate([np.full(len(r.vectors), r.label) for r in eligible]),
        weights,
    )


def evaluate_runs(runs, score_fn):
    """Count session outcomes, including transient errors and missing coverage."""
    groups = {}
    eligible = [run for run in runs if len(run.vectors)]
    scores = np.asarray(score_fn(np.concatenate([r.vectors for r in eligible]))) if eligible else np.array([])
    if (scores.shape != (sum(len(r.vectors) for r in eligible),)
            or not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any()):
        raise ValueError("Candidate returned invalid probabilities")
    offset = 0
    for run in runs:
        values = scores[offset:offset + len(run.vectors)]
        offset += len(values)
        verdicts = ["BOT" if value >= PRODUCTION_DECISION_THRESHOLD else
                    "SUSPECT" if value >= PRODUCTION_SUSPECT_THRESHOLD else "HUMAN"
                    for value in values]
        group = groups.setdefault((run.source, run.label, run.family), {
            "runs": 0, "eligible_windows": 0, "excluded_windows": 0,
            "no_eligible_window_runs": 0, "final": Counter(), "ever_human": 0,
            "ever_bot": 0, "human_windows": 0, "bot_windows": 0,
        })
        group["runs"] += 1
        group["eligible_windows"] += len(values)
        group["excluded_windows"] += run.excluded_windows
        group["no_eligible_window_runs"] += not verdicts
        group["final"].update([verdicts[-1] if verdicts else "SUSPECT"])
        group["ever_human"] += "HUMAN" in verdicts
        group["ever_bot"] += "BOT" in verdicts
        group["human_windows"] += verdicts.count("HUMAN")
        group["bot_windows"] += verdicts.count("BOT")
    return [{"source": source, "label": "BOT" if label else "HUMAN", "family": family,
             **{k: dict(sorted(v.items())) if isinstance(v, Counter) else v for k, v in group.items()}}
            for (source, label, family), group in sorted(groups.items())]


def load_runs(dataset_root, capture_dir):
    # First assign sessions, then materialize windows from their full trajectories.
    sessions = deduplicate_real_sessions(load_phase2_dataset(dataset_root, with_metadata=True))
    if not sessions:
        raise ValueError("No Phase 2 sessions were loaded")
    splits = assign_real_session_splits(sessions)
    if set(splits) != {"train", "val", "test"}:
        raise ValueError("Require fixed train, validation and test session partitions")
    ids = {s.session_id for s in sessions}
    full = {s.session_id: s.sampled_training_windows for s in load_phase2_dataset(
        dataset_root, with_metadata=True, training_window_session_ids=ids,
    )}
    real = []
    for session, split in zip(sessions, splits):
        windows = full.get(session.session_id)
        if windows is None:
            raise ValueError("Full-trajectory windows are missing")
        real.append(make_run(f"phase2:{session.session_id}", session.label, "phase2",
                             "dataset", split, windows))
    captures = load_bot_captures(capture_dir)
    field = [make_run(f"field:{c.capture_id}", 1, generator_family(c.family), "field", "",
                      capture_training_windows(c)) for c in captures]
    if len({run.family for run in field}) < 3:
        raise ValueError("Require at least three generator families for leave-family-out evaluation")
    return real, field


def run_experiment(real, field, frozen_score, artifact_dir):
    artifact_dir = Path(artifact_dir).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    if artifact_dir.is_relative_to(repo_root):
        raise ValueError("Experimental artifacts must be outside the product repository")
    artifact_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "protocol": PROTOCOL, "release_approved": False, "scope": "standalone_mouse_classifier",
        "feature_names": list(FEATURE_NAMES), "model_params": MODEL_PARAMS,
        "thresholds": {"human_below": PRODUCTION_SUSPECT_THRESHOLD, "bot_at_least": PRODUCTION_DECISION_THRESHOLD},
        "human_browser_runs": 0, "phase1_used": False,
        "note": "Fixed hyperparameters/thresholds. Session splits precede windows; entire field "
                "generator families held out, including timing variants. No participant IDs available "
                "for dataset humans. This is not a release replay or production accuracy estimate.",
        "folds": [],
    }
    for heldout in sorted({r.family for r in field}):
        partitions = {split: [r for r in real if r.split == split] for split in ("train", "val", "test")}
        partitions["train"] += [r for r in field if r.family != heldout]
        partitions["test"] += [r for r in field if r.family == heldout]
        digest = audit_partitions(partitions)
        fold = {"heldout_family": heldout, "split_manifest_sha256": digest, "split_counts": {
            split: {"runs": len(runs), "windows": sum(len(r.vectors) for r in runs),
                    "human_runs": sum(r.label == 0 for r in runs),
                    "field_families": sorted({r.family for r in runs if r.source == "field"})}
            for split, runs in partitions.items()
        }, "arms": {}}
        fold["arms"]["frozen_tabular"] = {
            split: evaluate_runs(partitions[split], frozen_score) for split in ("val", "test")
        }
        for name, with_field, n_features in (
            ("refit_existing", False, 20), ("refit_with_field", True, 20),
            ("refit_with_field_local", True, len(FEATURE_NAMES)),
        ):
            train = [r for r in partitions["train"] if with_field or r.source == "dataset"]
            x, y, weights = training_matrix(train, n_features)
            model = XGBClassifier(**MODEL_PARAMS)
            model.fit(x, y, sample_weight=weights)
            score = lambda values: model.predict_proba(values[:, :n_features])[:, 1]  # noqa: E731
            arm = {split: evaluate_runs(partitions[split], score) for split in ("val", "test")}
            artifact = artifact_dir / f"{heldout}-{name}.ubj"
            model.save_model(artifact)
            arm["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            arm["feature_importances"] = dict(sorted(
                zip(FEATURE_NAMES[:n_features], map(float, model.feature_importances_)),
                key=lambda item: (-item[1], item[0]),
            ))
            fold["arms"][name] = arm
        report["folds"].append(fold)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    real, field = load_runs(args.dataset_root, args.capture_dir)
    detector, manifest = _load_detector("core_ml/weights", PRODUCTION_DECISION_THRESHOLD)

    def frozen_score(values):
        return detector.tabular_model.predict_batch(np.concatenate([
            np.zeros((len(values), len(ENV_NAMES)), dtype=np.float32), values[:, :20],
        ], axis=1))

    report = run_experiment(real, field, frozen_score, args.artifact_dir)
    report["frozen_bundle_id"] = manifest["bundle_id"]
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    (Path(args.artifact_dir) / "experiment.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
