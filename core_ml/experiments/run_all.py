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
import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import torch
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, confusion_matrix, roc_curve
from sklearn.model_selection import train_test_split

from core_ml.dataset.loader import (
    generate_synthetic_telemetry,
    load_real_dataset,
    records_to_chunks,
)
from core_ml.features.env_features import extract_env_vector, FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import compute_statistical_features, extract_sequential_chunks
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

MOUSE_STAT_FEATURES = [
    "mean_speed", "std_speed", "max_speed", "mean_accel", "std_accel",
    "straightness", "pause_ratio", "direction_changes_x", "direction_changes_y",
    "jerk_mean", "angular_entropy",
    "curvature_mean", "curvature_std", "time_regularity",
    "velocity_autocorrelation", "accel_zero_crossing_rate", "movement_efficiency",
]

RESULTS = {}


def build_full_vector(fp, bd, records):
    env_vec = extract_env_vector(fp, bd)
    m_stats = compute_statistical_features(records)
    mouse_vec = np.array([m_stats[k] for k in MOUSE_STAT_FEATURES], dtype=np.float32)
    return np.concatenate([env_vec, mouse_vec])


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


def prepare_data():
    """Prepare common dataset for all experiments."""
    print("  Preparing data...")
    real_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Tuần 3", "repos", "web_bot_detection_dataset")
    
    all_telemetries = []
    all_labels = []
    all_records = []  # raw records for per-session analysis

    # Real data
    real_sessions = []
    if os.path.isdir(real_root):
        for scenario in ["humans_and_moderate_bots", "humans_and_advanced_bots"]:
            sessions = load_real_dataset(real_root, scenario=scenario)
            real_sessions.extend(sessions)

    for records, label in real_sessions:
        chunks = records_to_chunks(records, chunk_size=24, stride=12)
        if len(chunks) > 10:
            chunks = random.sample(chunks, 10)
        t = {
            "fingerprint": {}, "botd": {"heuristicScore": 0.0, "detectors": {}, "reasons": []},
            "mouse": {"records": records, "chunks": chunks},
        }
        all_telemetries.append(t)
        all_labels.append(label)
        all_records.append(records)

    # Synthetic
    for _ in range(200):
        t = generate_synthetic_telemetry(is_bot=False)
        all_telemetries.append(t)
        all_labels.append(0)
        all_records.append(t["mouse"]["records"])

    for _ in range(200):
        level = random.choice(["naive", "moderate", "advanced"])
        t = generate_synthetic_telemetry(is_bot=True, bot_level=level)
        all_telemetries.append(t)
        all_labels.append(1)
        all_records.append(t["mouse"]["records"])

    # Build feature matrices
    X_list = []
    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURES
    for t in all_telemetries:
        vec = build_full_vector(t.get("fingerprint", {}), t.get("botd", {}), t["mouse"]["records"])
        X_list.append(vec)

    X = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    y = np.array(all_labels, dtype=int)

    return X, y, feature_names, all_records, all_telemetries


def load_real_by_scenario(real_root, scenario):
    """Load real data for a specific scenario only."""
    sessions = load_real_dataset(real_root, scenario=scenario)
    X_list, y_list = [], []
    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURES
    for records, label in sessions:
        fp = {}
        bd = {"heuristicScore": 0.0, "detectors": {}, "reasons": []}
        vec = build_full_vector(fp, bd, records)
        X_list.append(vec)
        y_list.append(label)
    if not X_list:
        return np.empty((0, 43)), np.array([])
    X = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    return X, np.array(y_list, dtype=int)


# ============================================================
# EXPERIMENT 1: Baseline Comparison
# ============================================================
def experiment_baseline(X, y, feature_names):
    print("\n" + "=" * 60)
    print("  E1: BASELINE COMPARISON (Rule-based vs ML)")
    print("=" * 60)

    idx_train, idx_test = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=SEED)
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
    print(f"  [ML] XGBoost (43 features):          AUC={ml_metrics['roc_auc']:.4f} | F1={ml_metrics['f1']:.4f}")

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
def experiment_concept_drift():
    print("\n" + "=" * 60)
    print("  E2: CONCEPT DRIFT (Train moderate → Test advanced)")
    print("=" * 60)

    real_root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Tuần 3", "repos", "web_bot_detection_dataset")
    if not os.path.isdir(real_root):
        print("  Real dataset not found. Skipping.")
        return

    X_mod, y_mod = load_real_by_scenario(real_root, "humans_and_moderate_bots")
    X_adv, y_adv = load_real_by_scenario(real_root, "humans_and_advanced_bots")

    if len(y_mod) == 0 or len(y_adv) == 0:
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
def experiment_feature_ablation(X, y, feature_names):
    print("\n" + "=" * 60)
    print("  E3: FEATURE ABLATION STUDY")
    print("=" * 60)

    idx_train, idx_test = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=SEED)

    # Define feature groups
    env_names = list(ENV_FEATURE_NAMES)
    mouse_stat_names = MOUSE_STAT_FEATURES
    new_v2_features = ["curvature_mean", "curvature_std", "time_regularity",
                       "velocity_autocorrelation", "accel_zero_crossing_rate", "movement_efficiency"]

    groups = {
        "All features (43)": list(range(len(feature_names))),
        "Only Environment/Fingerprint (26)": [i for i, n in enumerate(feature_names) if n in env_names],
        "Only Mouse Dynamics (17)": [i for i, n in enumerate(feature_names) if n in mouse_stat_names],
        "Without v2 features (37)": [i for i, n in enumerate(feature_names) if n not in new_v2_features],
        "Only v2 new features (6)": [i for i, n in enumerate(feature_names) if n in new_v2_features],
        "Without BotD heuristics (remove top env)": [i for i, n in enumerate(feature_names) if n not in ["heuristic_score", "flagged_count", "flag_webdriver", "flag_virtualGpu"]],
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
def experiment_class_imbalance(X, y, feature_names):
    print("\n" + "=" * 60)
    print("  E4: CLASS IMBALANCE ROBUSTNESS")
    print("=" * 60)

    idx_human = np.where(y == 0)[0]
    idx_bot = np.where(y == 1)[0]

    # Fixed test set
    n_test = min(40, len(idx_human) // 3, len(idx_bot) // 3)
    test_h = np.random.choice(idx_human, n_test, replace=False)
    test_b = np.random.choice(idx_bot, n_test, replace=False)
    test_idx = np.concatenate([test_h, test_b])
    train_pool_h = np.setdiff1d(idx_human, test_h)
    train_pool_b = np.setdiff1d(idx_bot, test_b)

    ratios = [("1:1", 1.0), ("1:3", 3.0), ("1:5", 5.0), ("1:10", 10.0)]
    imbalance_results = {}

    for ratio_name, ratio in ratios:
        n_h = min(len(train_pool_h), 150)
        n_b = max(1, int(n_h / ratio))
        n_b = min(n_b, len(train_pool_b))

        tr_h = np.random.choice(train_pool_h, n_h, replace=False)
        tr_b = np.random.choice(train_pool_b, n_b, replace=n_b > len(train_pool_b))
        tr_idx = np.concatenate([tr_h, tr_b])

        model = TabularBotClassifier(
            n_estimators=200, max_depth=5,
            scale_pos_weight=n_h / max(1, n_b)
        )
        model.fit(X[tr_idx], y[tr_idx], feature_names=feature_names)
        proba = model.predict_batch(X[test_idx])
        metrics = eval_metrics(y[test_idx], proba)
        imbalance_results[ratio_name] = {**metrics, "train_human": int(n_h), "train_bot": int(n_b)}
        print(f"  [H:B={ratio_name}] Train={n_h}H+{n_b}B → AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | Recall={metrics['recall']:.4f} | FPR={metrics['fpr']:.4f}")

    RESULTS["E4_class_imbalance"] = imbalance_results


# ============================================================
# EXPERIMENT 5: Early Detection (Minimum Mouse Points)
# ============================================================
def experiment_early_detection(all_records, y, feature_names):
    print("\n" + "=" * 60)
    print("  E5: EARLY DETECTION (Minimum Mouse Points Required)")
    print("=" * 60)

    thresholds = [5, 10, 15, 20, 30, 50, 100]
    early_results = {}

    for max_pts in thresholds:
        X_list = []
        y_valid = []
        for records, label in zip(all_records, y):
            # Truncate records to first max_pts move events
            moves = [r for r in records if r.get("type") == "move"][:max_pts]
            if len(moves) < 3:
                continue
            # Rebuild stats from truncated records
            fp = {}
            bd = {"heuristicScore": 0.0, "detectors": {}, "reasons": []}
            vec = build_full_vector(fp, bd, moves)
            X_list.append(vec)
            y_valid.append(label)

        if len(y_valid) < 20:
            continue

        X_trunc = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
        y_trunc = np.array(y_valid, dtype=int)

        idx_tr, idx_te = train_test_split(np.arange(len(y_trunc)), test_size=0.3, stratify=y_trunc, random_state=SEED)
        model = TabularBotClassifier(n_estimators=150, max_depth=5)
        model.fit(X_trunc[idx_tr], y_trunc[idx_tr], feature_names=feature_names)
        proba = model.predict_batch(X_trunc[idx_te])
        metrics = eval_metrics(y_trunc[idx_te], proba)
        early_results[f"{max_pts}_points"] = {**metrics, "n_samples": len(y_valid)}
        print(f"  [{max_pts:3d} pts] n={len(y_valid):3d} → AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | Recall={metrics['recall']:.4f}")

    RESULTS["E5_early_detection"] = early_results


# ============================================================
# EXPERIMENT 6: Inference Latency
# ============================================================
def experiment_inference_latency(X, model_trained):
    print("\n" + "=" * 60)
    print("  E6: INFERENCE LATENCY BENCHMARK")
    print("=" * 60)

    # XGBoost single sample
    times_xgb = []
    for i in range(min(100, len(X))):
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
        for _ in range(100):
            start = time.perf_counter()
            lstm(dummy_chunk)
            elapsed = (time.perf_counter() - start) * 1000
            times_lstm.append(elapsed)

    latency_results = {
        "xgboost_ms": {"mean": round(np.mean(times_xgb), 3), "p50": round(np.median(times_xgb), 3), "p95": round(np.percentile(times_xgb, 95), 3), "p99": round(np.percentile(times_xgb, 99), 3)},
        "lstm_ms": {"mean": round(np.mean(times_lstm), 3), "p50": round(np.median(times_lstm), 3), "p95": round(np.percentile(times_lstm, 95), 3), "p99": round(np.percentile(times_lstm, 99), 3)},
    }

    print(f"  XGBoost: mean={latency_results['xgboost_ms']['mean']:.3f}ms | p95={latency_results['xgboost_ms']['p95']:.3f}ms | p99={latency_results['xgboost_ms']['p99']:.3f}ms")
    print(f"  BiLSTM:  mean={latency_results['lstm_ms']['mean']:.3f}ms | p95={latency_results['lstm_ms']['p95']:.3f}ms | p99={latency_results['lstm_ms']['p99']:.3f}ms")

    RESULTS["E6_inference_latency"] = latency_results


# ============================================================
# EXPERIMENT 7: FPR/ROC Threshold Analysis
# ============================================================
def experiment_roc_analysis(X, y, feature_names):
    print("\n" + "=" * 60)
    print("  E7: FPR/ROC THRESHOLD ANALYSIS")
    print("=" * 60)

    idx_tr, idx_te = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=SEED)
    model = TabularBotClassifier(n_estimators=300, max_depth=6)
    model.fit(X[idx_tr], y[idx_tr], feature_names=feature_names)
    proba = model.predict_batch(X[idx_te])

    thresholds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    roc_results = {}
    print(f"  {'Threshold':>10s} | {'FPR':>6s} | {'TPR':>6s} | {'Precision':>9s} | {'F1':>6s}")
    print(f"  {'-'*10} | {'-'*6} | {'-'*6} | {'-'*9} | {'-'*6}")

    for t in thresholds:
        m = eval_metrics(y[idx_te], proba, threshold=t)
        tpr = m['recall']
        print(f"  {t:>10.1f} | {m['fpr']:>6.4f} | {tpr:>6.4f} | {m['precision']:>9.4f} | {m['f1']:>6.4f}")
        roc_results[str(t)] = m

    # Full ROC curve data
    try:
        fpr_curve, tpr_curve, thres_curve = roc_curve(y[idx_te], proba)
        auc_val = roc_auc_score(y[idx_te], proba)
        print(f"\n  Overall AUC-ROC: {auc_val:.4f}")
        roc_results["auc"] = round(auc_val, 4)
    except Exception:
        pass

    RESULTS["E7_roc_analysis"] = roc_results


# ============================================================
# EXPERIMENT 8: Short Session Analysis
# ============================================================
def experiment_short_sessions(all_records, y, feature_names):
    print("\n" + "=" * 60)
    print("  E8: SHORT SESSION ANALYSIS")
    print("=" * 60)

    # Group sessions by length
    lengths = [len([r for r in rec if r.get("type") == "move"]) for rec in all_records]
    
    bins = [(0, 10, "Very short (<10)"), (10, 25, "Short (10-25)"), (25, 50, "Medium (25-50)"), (50, float('inf'), "Long (50+)")]
    
    # Train on all data
    X_list = []
    for rec in all_records:
        vec = build_full_vector({}, {"heuristicScore": 0.0, "detectors": {}, "reasons": []}, rec)
        X_list.append(vec)
    X_all = np.nan_to_num(np.array(X_list, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
    
    idx_tr, idx_te = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=SEED)
    model = TabularBotClassifier(n_estimators=200, max_depth=5)
    model.fit(X_all[idx_tr], y[idx_tr], feature_names=feature_names)

    short_results = {}
    for lo, hi, label in bins:
        mask = [(i in idx_te) and (lo <= lengths[i] < hi) for i in range(len(y))]
        test_in_bin = np.where(mask)[0]
        if len(test_in_bin) < 5:
            print(f"  [{label:20s}] n={len(test_in_bin):3d} — too few samples")
            continue
        proba = model.predict_batch(X_all[test_in_bin])
        metrics = eval_metrics(y[test_in_bin], proba)
        short_results[label] = {**metrics, "n_samples": len(test_in_bin)}
        print(f"  [{label:20s}] n={len(test_in_bin):3d} → AUC={metrics['roc_auc']:.4f} | F1={metrics['f1']:.4f} | FPR={metrics['fpr']:.4f}")

    RESULTS["E8_short_sessions"] = short_results


# ============================================================
# EXPERIMENT 9: Power User Stress Test
# ============================================================
def experiment_power_user(all_records, y, feature_names):
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
    idx_tr, idx_te = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=SEED)
    model = TabularBotClassifier(n_estimators=200, max_depth=5)
    model.fit(X_all[idx_tr], y[idx_tr], feature_names=feature_names)

    # Find "power user" humans in test set: high straightness OR high speed
    power_users = []
    normal_humans = []
    for i in idx_te:
        if y[i] == 0:  # human
            s = stats_list[i]
            if s["straightness"] > 0.85 or s["mean_speed"] > np.percentile([st["mean_speed"] for st in stats_list], 90):
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
def main():
    print("=" * 60)
    print("  BOT DETECTION — COMPREHENSIVE EXPERIMENT SUITE")
    print("=" * 60)

    X, y, feature_names, all_records, all_telemetries = prepare_data()
    print(f"  Dataset: {len(y)} samples ({sum(y==0)} Human, {sum(y==1)} Bot), {len(feature_names)} features")

    # Run all experiments
    model, idx_train, idx_test = experiment_baseline(X, y, feature_names)
    experiment_concept_drift()
    experiment_feature_ablation(X, y, feature_names)
    experiment_class_imbalance(X, y, feature_names)
    experiment_early_detection(all_records, y, feature_names)
    experiment_inference_latency(X, model)
    experiment_roc_analysis(X, y, feature_names)
    experiment_short_sessions(all_records, y, feature_names)
    experiment_power_user(all_records, y, feature_names)

    # Save all results to JSON
    results_path = os.path.join(os.path.dirname(__file__), "..", "experiment_results.json")
    # Convert numpy types to native Python for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj
    import json as json2
    class NpEncoder(json2.JSONEncoder):
        def default(self, obj):
            return convert(obj)
    with open(results_path, "w", encoding="utf-8") as f:
        json2.dump(RESULTS, f, indent=2, ensure_ascii=False, cls=NpEncoder)
    print(f"\n  Results saved to: {results_path}")

    print("\n" + "=" * 60)
    print("  ALL EXPERIMENTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
