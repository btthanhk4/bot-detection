"""
Comprehensive Experiment Suite for Bot Detection Thesis
========================================================
Runs all 9 priority experiments from scope analysis:
  E1: Baseline Comparison (rule-based vs ML)
  E2: Concept Drift (train moderate → test advanced)
  E3: Feature Ablation Study
  E4: Class Imbalance Robustness
  E5: Early Detection (minimum mouse points)
  E6: Inference Latency Benchmark
  E7: FPR/ROC Threshold Analysis
  E8: Short Session Analysis
  E9: Power User Stress Test
"""

import os
import sys
import time
import random
import json
import hashlib
import argparse
import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import torch
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, roc_curve
from sklearn.model_selection import train_test_split

from core_ml.dataset.loader import (
    generate_synthetic_telemetry,
    load_real_dataset,
    records_to_chunks,
)
from core_ml.features.env_features import extract_env_vector, FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import (
    compute_statistical_features,
    extract_mouse_stat_vector,
    STATISTICAL_FEATURE_NAMES,
)
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.train import deduplicate_real_sessions, assign_real_session_splits

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

MOUSE_STAT_FEATURES = list(STATISTICAL_FEATURE_NAMES)

RESULTS = {}


def records_signature(records):
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_full_vector(fp, bd, records):
    env_vec = extract_env_vector(fp, bd)
    mouse_vec = extract_mouse_stat_vector(records)
    return np.concatenate([env_vec, mouse_vec])


def truncate_moves(records, max_points):
    """Return the first valid mouse-move records without mutating the session."""
    return [record for record in records if isinstance(record, dict) and record.get("type") == "move"][:max_points]


def to_json_safe(value):
    """Recursively convert numpy values and non-finite floats to strict JSON values."""
    if isinstance(value, dict):
        return {key: to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


def eval_metrics(y_true, y_proba, threshold=0.5):
    y_pred = (y_proba >= threshold).astype(int)
    try:
        auc = roc_auc_score(y_true, y_proba)
    except ValueError:
        auc = 0.0
    return {
        "roc_auc": round(auc, 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "accuracy": round(np.mean(y_true == y_pred), 4),
        "fpr": round(np.sum((y_pred == 1) & (y_true == 0)) / max(1, np.sum(y_true == 0)), 4),
    }


def prepare_data(dataset_root=None):
    """Prepare common dataset for all experiments."""
    print("  Preparing data...")
    real_root = dataset_root or os.getenv("BOT_DATASET_ROOT", "")
    
    all_telemetries = []
    all_labels = []
    all_records = []  # raw records for per-session analysis
    all_splits = []

    # Real data (Phase 1 + Phase 2 with deduplication)
    real_sessions = []
    if os.path.isdir(real_root):
        for scenario in ["humans_and_moderate_bots", "humans_and_advanced_bots"]:
            sessions = load_real_dataset(real_root, scenario=scenario,
                                          include_phase2=True, with_metadata=True)
            real_sessions.extend(sessions)
        real_sessions = deduplicate_real_sessions(real_sessions)

    real_splits = assign_real_session_splits(real_sessions)
    for session, split in zip(real_sessions, real_splits):
        records, label = session.records, session.label
        chunks = records_to_chunks(records, chunk_size=24, stride=12)
        if len(chunks) > 10:
            chunks = random.sample(chunks, 10)
        t = {
            "fingerprint": {}, "botd": {"heuristicScore": 0.0, "detectors": {}, "reasons": []},
            "mouse": {"records": records, "chunks": chunks},
            "early_records": session.early_records,
        }
        all_telemetries.append(t)
        all_labels.append(label)
        all_records.append(records)
        all_splits.append(split)

    # Synthetic (reduced count since real data is now larger)
    for _ in range(150):
        t = generate_synthetic_telemetry(is_bot=False)
        all_telemetries.append(t)
        all_labels.append(0)
        all_records.append(t["mouse"]["records"])
        all_splits.append("train")

    for _ in range(150):
        level = random.choice(["naive", "moderate", "advanced"])
        t = generate_synthetic_telemetry(is_bot=True, bot_level=level)
        all_telemetries.append(t)
        all_labels.append(1)
        all_records.append(t["mouse"]["records"])
        all_splits.append("train")

    # Build feature matrices
    X_list = []
    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURES
    for t in all_telemetries:
        vec = build_full_vector(t.get("fingerprint", {}), t.get("botd", {}), t["mouse"]["records"])
        X_list.append(vec)

    X = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    y = np.array(all_labels, dtype=int)

    return X, y, feature_names, all_records, all_telemetries, np.asarray(all_splits)


def get_experiment_indices(y, splits):
    """Return one shared leakage-safe split for every comparable experiment."""
    y = np.asarray(y)
    split_array = np.asarray(splits)
    if y.ndim != 1 or split_array.ndim != 1 or len(y) != len(split_array):
        raise ValueError("Labels and split metadata must be one-dimensional and aligned")
    if len(np.unique(y)) != 2:
        raise ValueError("Experiments require both human and bot labels")
    idx_test = np.flatnonzero(split_array == "test")
    idx_train = np.flatnonzero(split_array != "test")
    if len(idx_test):
        if len(np.unique(y[idx_train])) != 2 or len(np.unique(y[idx_test])) != 2:
            raise ValueError("Official test split and its training pool must both contain both labels")
        return idx_train, idx_test
    return train_test_split(
        np.arange(len(y)), test_size=0.30, stratify=y, random_state=SEED
    )


def get_fit_validation_indices(y, splits, idx_train):
    """Use a valid published validation split or derive one from shared training data."""
    y = np.asarray(y)
    split_array = np.asarray(splits)
    idx_train = np.asarray(idx_train, dtype=int)
    if len(y) != len(split_array):
        raise ValueError("Labels and split metadata must be aligned")

    shared_train = set(idx_train.tolist())
    idx_fit = np.asarray(
        [index for index in np.flatnonzero(split_array == "train") if index in shared_train],
        dtype=int,
    )
    idx_val = np.asarray(
        [index for index in np.flatnonzero(split_array == "val") if index in shared_train],
        dtype=int,
    )
    published_split_is_usable = (
        len(idx_fit) > 0
        and len(idx_val) > 0
        and len(np.unique(y[idx_fit])) == 2
        and len(np.unique(y[idx_val])) == 2
    )
    if published_split_is_usable:
        return idx_fit, idx_val

    try:
        return train_test_split(
            idx_train, test_size=0.20, stratify=y[idx_train], random_state=SEED
        )
    except ValueError as exc:
        raise ValueError(
            "Shared training data is too small or imbalanced for a validation split"
        ) from exc


def load_real_by_scenario(real_root, scenario, include_phase2=True):
    """Load real data for a specific scenario only."""
    sessions = load_real_dataset(real_root, scenario=scenario, include_phase2=include_phase2)
    X_list, y_list = [], []
    for records, label in sessions:
        fp = {}
        bd = {"heuristicScore": 0.0, "detectors": {}, "reasons": []}
        vec = build_full_vector(fp, bd, records)
        X_list.append(vec)
        y_list.append(label)
    if not X_list:
        return np.empty((0, 50)), np.array([])
    X = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    return X, np.array(y_list, dtype=int)


def sessions_to_xy(sessions):
    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURES
    vectors = [
        build_full_vector({}, {"heuristicScore": 0.0, "detectors": {}, "reasons": []}, records)
        for records, _ in sessions
    ]
    if not vectors:
        return np.empty((0, len(feature_names))), np.array([], dtype=int)
    return (
        np.nan_to_num(np.array(vectors, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0),
        np.array([label for _, label in sessions], dtype=int),
    )


# ============================================================
# EXPERIMENT 1: Baseline Comparison
# ============================================================
def experiment_baseline(X, y, feature_names, idx_train, idx_test):
    print("\n" + "=" * 60)
    print("  E1: BASELINE COMPARISON (Rule-based vs ML)")
    print("=" * 60)

    X_train, X_test = X[idx_train], X[idx_test]
    y_train, y_test = y[idx_train], y[idx_test]

    # Baseline 1: Simple threshold on heuristic_score (feature index 0)
    h_scores = X_test[:, 0]  # heuristic_score
    baseline_heuristic = eval_metrics(y_test, h_scores)
    print(f"  [Baseline] Heuristic Score Only:     AUC={baseline_heuristic['roc_auc']:.4f} | F1={baseline_heuristic['f1']:.4f}")

    # Baseline 2: Rule-based (heuristic + straightness + time_regularity)
    straightness_idx = feature_names.index("straightness") if "straightness" in feature_names else -1
    time_reg_idx = feature_names.index("time_regularity") if "time_regularity" in feature_names else -1
    
    rule_scores = np.zeros(len(y_test))
    for i in range(len(y_test)):
        score = h_scores[i] * 0.4
        if straightness_idx >= 0:
            score += max(0, X_test[i, straightness_idx] - 0.9) * 3.0
        if time_reg_idx >= 0:
            score += max(0, 0.3 - X_test[i, time_reg_idx]) * 2.0
        rule_scores[i] = min(1.0, score)
    baseline_rules = eval_metrics(y_test, rule_scores)
    print(f"  [Baseline] Multi-rule Threshold:     AUC={baseline_rules['roc_auc']:.4f} | F1={baseline_rules['f1']:.4f}")

    # ML: XGBoost
    model = TabularBotClassifier(n_estimators=300, max_depth=6,
                                  scale_pos_weight=sum(y_train == 0) / max(1, sum(y_train == 1)))
    model.fit(X_train, y_train, feature_names=feature_names)
    ml_proba = model.predict_batch(X_test)
    ml_metrics = eval_metrics(y_test, ml_proba)
    print(f"  [ML] XGBoost ({len(feature_names)} features):          AUC={ml_metrics['roc_auc']:.4f} | F1={ml_metrics['f1']:.4f}")

    improvement = (ml_metrics['roc_auc'] - baseline_rules['roc_auc']) / max(0.001, baseline_rules['roc_auc']) * 100
    print(f"\n  → ML improves over best baseline by {improvement:.1f}% AUC")

    RESULTS["E1_baseline"] = {
        "heuristic_only": baseline_heuristic,
        "multi_rule": baseline_rules,
        "xgboost_ml": ml_metrics,
        "improvement_pct": round(improvement, 1),
    }
    return model, idx_train, idx_test


# ============================================================
# EXPERIMENT 2: Concept Drift
# ============================================================
def experiment_concept_drift(dataset_root=None):
    print("\n" + "=" * 60)
    print("  E2: CONCEPT DRIFT (Train moderate → Test advanced)")
    print("=" * 60)

    real_root = dataset_root or os.getenv("BOT_DATASET_ROOT", "")
    if not os.path.isdir(real_root):
        print("  Real dataset not found. Skipping.")
        return

    moderate = load_real_dataset(real_root, scenario="humans_and_moderate_bots", include_phase2=True)
    advanced = load_real_dataset(real_root, scenario="humans_and_advanced_bots", include_phase2=True)

    # Source scenarios reuse human sessions. Partition unique humans so no
    # trajectory can occur in both the moderate training and advanced test set.
    humans, moderate_bots, advanced_bots = {}, {}, {}
    for records, label in moderate:
        (humans if label == 0 else moderate_bots)[records_signature(records)] = (records, label)
    for records, label in advanced:
        (humans if label == 0 else advanced_bots)[records_signature(records)] = (records, label)
    human_sessions = list(humans.values())
    random.Random(SEED).shuffle(human_sessions)
    split_at = max(1, len(human_sessions) // 2)
    X_mod, y_mod = sessions_to_xy(human_sessions[:split_at] + list(moderate_bots.values()))
    X_adv, y_adv = sessions_to_xy(human_sessions[split_at:] + list(advanced_bots.values()))

    if set(y_mod.tolist()) != {0, 1} or set(y_adv.tolist()) != {0, 1}:
        print("  Insufficient data. Skipping.")
        return

    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURES

    # Scenario A: Train on moderate, test on advanced
    model_a = TabularBotClassifier(n_estimators=200, max_depth=5)
    model_a.fit(X_mod, y_mod, feature_names=feature_names)
    proba_a = model_a.predict_batch(X_adv)
    metrics_a = eval_metrics(y_adv, proba_a)
    print(f"  [A] Train=Moderate → Test=Advanced:  AUC={metrics_a['roc_auc']:.4f} | F1={metrics_a['f1']:.4f} | Recall={metrics_a['recall']:.4f}")

    # Scenario B: Train on advanced, test on moderate
    model_b = TabularBotClassifier(n_estimators=200, max_depth=5)
    model_b.fit(X_adv, y_adv, feature_names=feature_names)
    proba_b = model_b.predict_batch(X_mod)
    metrics_b = eval_metrics(y_mod, proba_b)
    print(f"  [B] Train=Advanced → Test=Moderate:  AUC={metrics_b['roc_auc']:.4f} | F1={metrics_b['f1']:.4f} | Recall={metrics_b['recall']:.4f}")

    # Scenario C: Train on both, cross-validate
    X_both = np.vstack([X_mod, X_adv])
    y_both = np.concatenate([y_mod, y_adv])
    idx_tr, idx_te = train_test_split(np.arange(len(y_both)), test_size=0.3, stratify=y_both, random_state=SEED)
    model_c = TabularBotClassifier(n_estimators=200, max_depth=5)
    model_c.fit(X_both[idx_tr], y_both[idx_tr], feature_names=feature_names)
    proba_c = model_c.predict_batch(X_both[idx_te])
    metrics_c = eval_metrics(y_both[idx_te], proba_c)
    print(f"  [C] Train=Both → Test=Both (split):  AUC={metrics_c['roc_auc']:.4f} | F1={metrics_c['f1']:.4f} | Recall={metrics_c['recall']:.4f}")

    drift_drop = metrics_a['roc_auc'] - metrics_c['roc_auc']
    print(f"\n  → Concept drift impact: {drift_drop:+.4f} AUC (negative = performance drops on unseen bot type)")

    RESULTS["E2_concept_drift"] = {
        "train_moderate_test_advanced": metrics_a,
        "train_advanced_test_moderate": metrics_b,
        "train_both_test_both": metrics_c,
    }


# ============================================================
# EXPERIMENT 3: Feature Ablation
# ============================================================
def experiment_feature_ablation(X, y, feature_names, idx_train, idx_test):
    print("\n" + "=" * 60)
    print("  E3: FEATURE ABLATION STUDY")
    print("=" * 60)

    # Define feature groups
    env_names = list(ENV_FEATURE_NAMES)
    mouse_stat_names = MOUSE_STAT_FEATURES
    new_v2_features = ["curvature_mean", "curvature_std", "time_regularity",
                       "velocity_autocorrelation", "accel_zero_crossing_rate", "movement_efficiency"]

    groups = {
        f"All features ({len(feature_names)})": list(range(len(feature_names))),
        f"Only Environment/Fingerprint ({len(env_names)})": [i for i, n in enumerate(feature_names) if n in env_names],
        f"Only Mouse Dynamics ({len(mouse_stat_names)})": [i for i, n in enumerate(feature_names) if n in mouse_stat_names],
        f"Without v2 features ({len(feature_names) - len(new_v2_features)})": [i for i, n in enumerate(feature_names) if n not in new_v2_features],
        f"Only v2 new features ({len(new_v2_features)})": [i for i, n in enumerate(feature_names) if n in new_v2_features],
        "Without BotD heuristics (remove top env)": [i for i, n in enumerate(feature_names) if n not in ["heuristic_score", "flagged_count", "flag_webdriver", "flag_virtual_gpu"]],
    }

    ablation_results = {}
    for group_name, indices in groups.items():
        if not indices:
            continue
        X_sub = X[:, indices]
        model = TabularBotClassifier(n_estimators=200, max_depth=5)
        model.fit(X_sub[idx_train], y[idx_train])
        proba = model.predict_batch(X_sub[idx_test])
        metrics = eval_metrics(y[idx_test], proba)
        ablation_results[group_name] = metrics
        print(f"  [{len(indices):2d}F] {group_name:45s} AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f}")

    RESULTS["E3_feature_ablation"] = ablation_results


# ============================================================
# EXPERIMENT 4: Class Imbalance
# ============================================================
def experiment_class_imbalance(X, y, feature_names, idx_train, idx_test):
    print("\n" + "=" * 60)
    print("  E4: CLASS IMBALANCE ROBUSTNESS")
    print("=" * 60)

    idx_human = idx_train[y[idx_train] == 0]
    idx_bot = idx_train[y[idx_train] == 1]

    # Fixed test set
    test_human = idx_test[y[idx_test] == 0]
    test_bot = idx_test[y[idx_test] == 1]
    n_test = min(40, len(test_human), len(test_bot))
    rng = np.random.default_rng(SEED)
    test_h = rng.choice(test_human, n_test, replace=False)
    test_b = rng.choice(test_bot, n_test, replace=False)
    test_idx = np.concatenate([test_h, test_b])
    train_pool_h = idx_human
    train_pool_b = idx_bot

    ratios = [("1:1", 1.0), ("1:3", 3.0), ("1:5", 5.0), ("1:10", 10.0)]
    imbalance_results = {}

    for ratio_name, ratio in ratios:
        n_h = min(len(train_pool_h), 150)
        n_b = max(1, int(n_h / ratio))
        n_b = min(n_b, len(train_pool_b))

        tr_h = rng.choice(train_pool_h, n_h, replace=False)
        tr_b = rng.choice(train_pool_b, n_b, replace=n_b > len(train_pool_b))
        tr_idx = np.concatenate([tr_h, tr_b])

        model = TabularBotClassifier(
            n_estimators=200, max_depth=5,
            scale_pos_weight=n_h / max(1, n_b)
        )
        model.fit(X[tr_idx], y[tr_idx], feature_names=feature_names)
        proba = model.predict_batch(X[test_idx])
        metrics = eval_metrics(y[test_idx], proba)
        result_key = f"B:H={ratio_name}"
        imbalance_results[result_key] = {**metrics, "train_human": int(n_h), "train_bot": int(n_b)}
        print(f"  [{result_key}] Train={n_h}H+{n_b}B → AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | Recall={metrics['recall']:.4f} | FPR={metrics['fpr']:.4f}")

    RESULTS["E4_class_imbalance"] = imbalance_results


# ============================================================
# EXPERIMENT 5: Early Detection (Minimum Mouse Points)
# ============================================================
def experiment_early_detection(all_records, y, feature_names, idx_train, idx_test):
    print("\n" + "=" * 60)
    print("  E5: EARLY DETECTION (Minimum Mouse Points Required)")
    print("=" * 60)

    thresholds = [5, 10, 15, 20, 30, 50, 100]
    early_results = {}

    for max_pts in thresholds:
        X_list = []
        y_valid = []
        original_indices = []
        for original_idx, (records, label) in enumerate(zip(all_records, y)):
            # Truncate records to first max_pts move events
            moves = truncate_moves(records, max_pts)
            if len(moves) < 3:
                continue
            # Rebuild stats from truncated records
            fp = {}
            bd = {"heuristicScore": 0.0, "detectors": {}, "reasons": []}
            vec = build_full_vector(fp, bd, moves)
            X_list.append(vec)
            y_valid.append(label)
            original_indices.append(original_idx)

        if len(y_valid) < 20:
            continue

        X_trunc = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
        y_trunc = np.array(y_valid, dtype=int)

        train_set, test_set = set(idx_train.tolist()), set(idx_test.tolist())
        idx_tr = np.array([i for i, original in enumerate(original_indices) if original in train_set])
        idx_te = np.array([i for i, original in enumerate(original_indices) if original in test_set])
        if not len(idx_tr) or not len(idx_te) or len(np.unique(y_trunc[idx_te])) < 2:
            continue
        model = TabularBotClassifier(n_estimators=150, max_depth=5)
        model.fit(X_trunc[idx_tr], y_trunc[idx_tr], feature_names=feature_names)
        proba = model.predict_batch(X_trunc[idx_te])
        metrics = eval_metrics(y_trunc[idx_te], proba)
        early_results[f"{max_pts}_points"] = {
            **metrics,
            "n_train": len(idx_tr),
            "n_test": len(idx_te),
        }
        print(f"  [{max_pts:3d} pts] train={len(idx_tr):3d} test={len(idx_te):3d} → AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | Recall={metrics['recall']:.4f}")

    RESULTS["E5_early_detection"] = early_results


# ============================================================
# EXPERIMENT 6: Inference Latency
# ============================================================
def experiment_inference_latency(X, model_trained, iterations=100, warmup_runs=10):
    print("\n" + "=" * 60)
    print("  E6: INFERENCE LATENCY BENCHMARK")
    print("=" * 60)

    X = np.asarray(X)
    iterations = int(iterations)
    warmup_runs = int(warmup_runs)
    if X.ndim != 2 or len(X) == 0:
        raise ValueError("Latency benchmark requires a non-empty 2D feature matrix")
    if iterations <= 0 or warmup_runs < 0:
        raise ValueError("Latency benchmark iterations must be positive and warmup non-negative")

    sample_count = min(iterations, len(X))
    for i in range(warmup_runs):
        model_trained.predict_proba(X[i % len(X)])

    # XGBoost single sample
    times_xgb = []
    for i in range(sample_count):
        start = time.perf_counter()
        model_trained.predict_proba(X[i])
        elapsed = (time.perf_counter() - start) * 1000
        times_xgb.append(elapsed)

    # LSTM single chunk
    lstm = MouseTrajectoryLSTM(input_dim=8, hidden_dim=64)
    dummy_chunk = torch.randn(1, 24, 8)
    times_lstm = []
    lstm.eval()
    with torch.no_grad():
        for _ in range(warmup_runs):
            lstm(dummy_chunk)
        for _ in range(iterations):
            start = time.perf_counter()
            lstm(dummy_chunk)
            elapsed = (time.perf_counter() - start) * 1000
            times_lstm.append(elapsed)

    latency_results = {
        "iterations": {"xgboost": sample_count, "lstm": iterations, "warmup": warmup_runs},
        "xgboost_ms": {"mean": round(np.mean(times_xgb), 3), "p50": round(np.median(times_xgb), 3), "p95": round(np.percentile(times_xgb, 95), 3), "p99": round(np.percentile(times_xgb, 99), 3)},
        "lstm_ms": {"mean": round(np.mean(times_lstm), 3), "p50": round(np.median(times_lstm), 3), "p95": round(np.percentile(times_lstm, 95), 3), "p99": round(np.percentile(times_lstm, 99), 3)},
    }

    print(f"  XGBoost: mean={latency_results['xgboost_ms']['mean']:.3f}ms | p95={latency_results['xgboost_ms']['p95']:.3f}ms | p99={latency_results['xgboost_ms']['p99']:.3f}ms")
    print(f"  BiLSTM:  mean={latency_results['lstm_ms']['mean']:.3f}ms | p95={latency_results['lstm_ms']['p95']:.3f}ms | p99={latency_results['lstm_ms']['p99']:.3f}ms")

    RESULTS["E6_inference_latency"] = latency_results


# ============================================================
# EXPERIMENT 7: FPR/ROC Threshold Analysis
# ============================================================
def experiment_roc_analysis(X, y, feature_names, idx_tr, idx_val, idx_te):
    print("\n" + "=" * 60)
    print("  E7: FPR/ROC THRESHOLD ANALYSIS")
    print("=" * 60)

    model = TabularBotClassifier(n_estimators=300, max_depth=6)
    model.fit(X[idx_tr], y[idx_tr], feature_names=feature_names)
    val_proba = model.predict_batch(X[idx_val])

    thresholds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    validation_results = {}
    print(f"  {'Threshold':>10s} | {'FPR':>6s} | {'TPR':>6s} | {'Precision':>9s} | {'F1':>6s}")
    print(f"  {'-'*10} | {'-'*6} | {'-'*6} | {'-'*9} | {'-'*6}")

    for t in thresholds:
        m = eval_metrics(y[idx_val], val_proba, threshold=t)
        tpr = m['recall']
        print(f"  {t:>10.1f} | {m['fpr']:>6.4f} | {tpr:>6.4f} | {m['precision']:>9.4f} | {m['f1']:>6.4f}")
        validation_results[str(t)] = m

    selected_threshold = max(
        thresholds,
        key=lambda threshold: (validation_results[str(threshold)]["f1"], -threshold),
    )
    test_proba = model.predict_batch(X[idx_te])
    test_metrics = eval_metrics(y[idx_te], test_proba, threshold=selected_threshold)
    print(f"\n  Selected on validation: {selected_threshold:.1f}")
    print(f"  Independent test: AUC={test_metrics['roc_auc']:.4f} | F1={test_metrics['f1']:.4f} | FPR={test_metrics['fpr']:.4f}")

    # Full test ROC curve is threshold-independent.
    try:
        fpr_curve, tpr_curve, thres_curve = roc_curve(y[idx_te], test_proba)
        test_metrics["roc_curve"] = {
            "fpr": fpr_curve.tolist(),
            "tpr": tpr_curve.tolist(),
            "thresholds": thres_curve.tolist(),
        }
    except ValueError:
        pass

    RESULTS["E7_roc_analysis"] = {
        "validation_thresholds": validation_results,
        "selected_threshold": selected_threshold,
        "independent_test": test_metrics,
    }


# ============================================================
# EXPERIMENT 8: Short Session Analysis
# ============================================================
def experiment_short_sessions(all_records, y, feature_names, idx_tr, idx_te):
    print("\n" + "=" * 60)
    print("  E8: SHORT SESSION ANALYSIS")
    print("=" * 60)

    # Train once on complete sessions, then shorten only the independent test set.
    X_list = []
    for rec in all_records:
        vec = build_full_vector({}, {"heuristicScore": 0.0, "detectors": {}, "reasons": []}, rec)
        X_list.append(vec)
    X_all = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    
    model = TabularBotClassifier(n_estimators=200, max_depth=5)
    model.fit(X_all[idx_tr], y[idx_tr], feature_names=feature_names)

    short_results = {}
    for max_points in [5, 10, 15, 24, 50, 100]:
        truncated_vectors = [
            build_full_vector(
                {},
                {"heuristicScore": 0.0, "detectors": {}, "reasons": []},
                truncate_moves(all_records[index], max_points),
            )
            for index in idx_te
        ]
        X_test = np.nan_to_num(
            np.asarray(truncated_vectors, dtype=np.float32),
            nan=0.0,
            posinf=100.0,
            neginf=-100.0,
        )
        proba = model.predict_batch(X_test)
        metrics = eval_metrics(y[idx_te], proba)
        key = f"first_{max_points}_points"
        short_results[key] = {**metrics, "n_samples": len(idx_te)}
        print(
            f"  [{max_points:3d} pts] n={len(idx_te):3d} → "
            f"AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | FPR={metrics['fpr']:.4f}"
        )

    RESULTS["E8_short_sessions"] = short_results


# ============================================================
# EXPERIMENT 9: Power User Stress Test
# ============================================================
def experiment_power_user(all_records, y, feature_names, idx_tr, idx_te):
    print("\n" + "=" * 60)
    print("  E9: POWER USER STRESS TEST")
    print("=" * 60)

    # Find human sessions with high straightness or high speed
    X_list = []
    stats_list = []
    for rec in all_records:
        stats = compute_statistical_features(rec)
        stats_list.append(stats)
        vec = build_full_vector({}, {"heuristicScore": 0.0, "detectors": {}, "reasons": []}, rec)
        X_list.append(vec)

    X_all = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    
    # Train model on all data
    model = TabularBotClassifier(n_estimators=200, max_depth=5)
    model.fit(X_all[idx_tr], y[idx_tr], feature_names=feature_names)

    # Find "power user" humans in test set: high straightness OR high speed
    train_human_speeds = [stats_list[i]["mean_speed"] for i in idx_tr if y[i] == 0]
    high_speed_threshold = np.percentile(train_human_speeds, 90) if train_human_speeds else float("inf")
    power_users = []
    normal_humans = []
    for i in idx_te:
        if y[i] == 0:  # human
            s = stats_list[i]
            if s["straightness"] > 0.85 or s["mean_speed"] > high_speed_threshold:
                power_users.append(i)
            else:
                normal_humans.append(i)

    print(f"  Power users in test set: {len(power_users)} | Normal humans: {len(normal_humans)}")

    power_results = {}
    if power_users:
        proba_power = model.predict_batch(X_all[power_users])
        fp_count = np.sum(proba_power >= 0.5)
        power_results["power_users"] = {
            "n": len(power_users),
            "false_positive_count": int(fp_count),
            "false_positive_rate": round(fp_count / len(power_users), 4),
            "mean_bot_proba": round(np.mean(proba_power), 4),
            "max_bot_proba": round(np.max(proba_power), 4),
        }
        print(f"  Power users: FP={fp_count}/{len(power_users)} ({fp_count/len(power_users)*100:.1f}%) | Mean P(bot)={np.mean(proba_power):.4f} | Max P(bot)={np.max(proba_power):.4f}")

    if normal_humans:
        proba_normal = model.predict_batch(X_all[normal_humans])
        fp_count_n = np.sum(proba_normal >= 0.5)
        power_results["normal_humans"] = {
            "n": len(normal_humans),
            "false_positive_count": int(fp_count_n),
            "false_positive_rate": round(fp_count_n / len(normal_humans), 4),
            "mean_bot_proba": round(np.mean(proba_normal), 4),
        }
        print(f"  Normal humans: FP={fp_count_n}/{len(normal_humans)} ({fp_count_n/len(normal_humans)*100:.1f}%) | Mean P(bot)={np.mean(proba_normal):.4f}")

    RESULTS["E9_power_user"] = power_results


# ============================================================
# MAIN
# ============================================================
def main(dataset_root=None):
    print("=" * 60)
    print("  BOT DETECTION — COMPREHENSIVE EXPERIMENT SUITE")
    print("=" * 60)

    RESULTS.clear()
    X, y, feature_names, all_records, all_telemetries, splits = prepare_data(dataset_root=dataset_root)
    print(f"  Dataset: {len(y)} samples ({sum(y==0)} Human, {sum(y==1)} Bot), {len(feature_names)} features")
    idx_train, idx_test = get_experiment_indices(y, splits)
    idx_fit, idx_val = get_fit_validation_indices(y, splits, idx_train)
    print(f"  Shared split: train={len(idx_train)} | independent test={len(idx_test)}")
    RESULTS["metadata"] = {
        "seed": SEED,
        "samples": len(y),
        "features": len(feature_names),
        "shared_train": len(idx_train),
        "independent_test": len(idx_test),
        "test_human": int(np.sum(y[idx_test] == 0)),
        "test_bot": int(np.sum(y[idx_test] == 1)),
    }

    # Run all experiments
    model, _, _ = experiment_baseline(X, y, feature_names, idx_train, idx_test)
    experiment_concept_drift(dataset_root=dataset_root)
    experiment_feature_ablation(X, y, feature_names, idx_train, idx_test)
    experiment_class_imbalance(X, y, feature_names, idx_train, idx_test)
    early_records = [
        telemetry.get("early_records") or records
        for telemetry, records in zip(all_telemetries, all_records)
    ]
    experiment_early_detection(early_records, y, feature_names, idx_train, idx_test)
    experiment_inference_latency(X, model)
    experiment_roc_analysis(X, y, feature_names, idx_fit, idx_val, idx_test)
    experiment_short_sessions(all_records, y, feature_names, idx_train, idx_test)
    experiment_power_user(all_records, y, feature_names, idx_train, idx_test)

    # Save all results to JSON
    results_path = os.path.join(os.path.dirname(__file__), "..", "experiment_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(to_json_safe(RESULTS), f, indent=2, ensure_ascii=False, allow_nan=False)
    print(f"\n  Results saved to: {results_path}")

    print("\n" + "=" * 60)
    print("  ALL EXPERIMENTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run bot detection experiments")
    parser.add_argument("--dataset-root", default=os.getenv("BOT_DATASET_ROOT", ""))
    args = parser.parse_args()
    main(dataset_root=args.dataset_root)
