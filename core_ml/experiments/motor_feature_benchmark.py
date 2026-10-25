"""Compare mouse-feature families on DELBOT circle drawings, holding out bot families.

The DELBOT-Mouse sample set records humans and OS-level cursor bots (pynput,
pyHM, NaturalMouseMotion) with the same browser recorder on the same task, so
a feature cannot win by detecting a different instrument. GAN trajectories
never went through a browser; their coordinates are rounded to whole pixels
and they are reported as a separate, weaker family.

Each file is one drawing. Drawings are not people: several files come from the
same person/device, so this is a feature-ranking experiment, not an estimate
of production accuracy. Offline only; it never writes a model bundle.

    python -m core_ml.experiments.motor_feature_benchmark \
        --delbot-dir "../Tuần 3/repos/DELBOT-Mouse/python" --output docs/MOTOR_FEATURE_BENCHMARK.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

from core_ml.features.motor_features import extract_motor_features
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES, compute_statistical_features

HUMAN_SOURCES = ("circles_human_pc1", "circles_human_pc2", "circles_human_pc2_pad",
                 "circles_human_vm", "circles_human_fast")
BOT_FAMILIES = {
    "pynput": "circles_bot_pynput",
    "pyhm": "circles_bot_pyhm",
    "naturalmousemotion": "circles_bot_naturalmousemotion",
    "gan": "circles_bot_gan",
}
FEATURE_SETS = {
    "current20": ("base",),
    "kinematic": ("kinematic",),
    "neuromotor": ("neuromotor",),
    "timing": ("timing",),
    "current20+kinematic": ("base", "kinematic"),
    "current20+neuromotor": ("base", "neuromotor"),
    "current20+timing": ("base", "timing"),
    "current20+neuromotor+timing": ("base", "neuromotor", "timing"),
    "all": ("base", "kinematic", "neuromotor", "timing"),
    # Split the timing family: click approach vs. how move events are produced.
    "current20+click_gap": ("base", "tim_click_gap_px"),
    "current20+event_timing": ("base", "tim_event_rate", "tim_dt_p50", "tim_dt_cv", "tim_dt_entropy",
                               "tim_dt_mode_share", "tim_zero_step_frac", "tim_teleport_frac",
                               "tim_max_step_ratio", "tim_micro_jitter_frac"),
}
TARGET_FPR = 0.01


def load_drawing(path: Path, round_coordinates: bool):
    records, clicks = [], []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) != 4:
            continue
        try:
            t, x, y = float(parts[0]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        if round_coordinates:
            x, y = round(x), round(y)
        kind = parts[1]
        if kind == "Move":
            records.append({"time": t, "x": x, "y": y, "type": "move"})
        elif kind == "Pressed":
            records.append({"time": t, "x": x, "y": y, "type": "down"})
        elif kind == "Released":
            records.append({"time": t, "x": x, "y": y, "type": "click"})
            clicks.append((t, x, y))
    return records, clicks


def featurize(records, clicks):
    row = {}
    stats = compute_statistical_features(records)
    for name in STATISTICAL_FEATURE_NAMES:
        row["base_" + name] = float(stats.get(name, 0.0))
    row.update(extract_motor_features(records, clicks))
    return row


def load_dataset(root: Path):
    samples = []
    for source in HUMAN_SOURCES:
        for path in sorted((root / source).glob("*.txt")):
            records, clicks = load_drawing(path, round_coordinates=False)
            samples.append({"label": 0, "group": source, "row": featurize(records, clicks)})
    for family, folder in BOT_FAMILIES.items():
        for path in sorted((root / folder).glob("*.txt")):
            records, clicks = load_drawing(path, round_coordinates=(family == "gan"))
            samples.append({"label": 1, "group": family, "row": featurize(records, clicks)})
    return samples


def columns_for(feature_set, names):
    prefixes = {"base": "base_", "kinematic": "kin_", "neuromotor": "neu_", "timing": "tim_"}
    parts = FEATURE_SETS[feature_set]
    wanted = tuple(prefixes[f] for f in parts if f in prefixes)
    explicit = {f for f in parts if f not in prefixes}
    return [name for name in names if name.startswith(wanted) or name in explicit]


def matrix(samples, columns):
    return np.array([[s["row"].get(c, np.nan) for c in columns] for s in samples], dtype=np.float32)


def split_humans(samples, seed):
    rng = np.random.default_rng(seed)
    parts = {"train": [], "val": [], "test": []}
    for source in HUMAN_SOURCES:
        group = [s for s in samples if s["label"] == 0 and s["group"] == source]
        order = rng.permutation(len(group))
        n_train, n_val = int(0.6 * len(group)), int(0.2 * len(group))
        parts["train"] += [group[i] for i in order[:n_train]]
        parts["val"] += [group[i] for i in order[n_train:n_train + n_val]]
        parts["test"] += [group[i] for i in order[n_train + n_val:]]
    return parts


def run(samples, seeds=(0, 1, 2), gan_cap=400):
    names = sorted({k for s in samples for k in s["row"]})
    results = {}
    for feature_set in FEATURE_SETS:
        columns = columns_for(feature_set, names)
        per_family = {}
        for held_out in BOT_FAMILIES:
            aucs, recalls, fprs = [], [], []
            for seed in seeds:
                rng = np.random.default_rng(seed + 100)
                humans = split_humans(samples, seed)
                train_bots = []
                for family in BOT_FAMILIES:
                    if family == held_out:
                        continue
                    group = [s for s in samples if s["group"] == family]
                    if family == "gan" and len(group) > gan_cap:
                        group = [group[i] for i in rng.choice(len(group), gan_cap, replace=False)]
                    train_bots += group
                train = humans["train"] + train_bots
                y = np.array([s["label"] for s in train])
                weights = np.where(y == 1, (y == 0).sum() / max((y == 1).sum(), 1), 1.0)
                model = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.9,
                                      colsample_bytree=0.8, random_state=seed, n_jobs=1, eval_metric="logloss")
                model.fit(matrix(train, columns), y, sample_weight=weights)
                val_scores = model.predict_proba(matrix(humans["val"], columns))[:, 1]
                threshold = float(np.quantile(val_scores, 1 - TARGET_FPR))
                test = humans["test"] + [s for s in samples if s["group"] == held_out]
                y_test = np.array([s["label"] for s in test])
                scores = model.predict_proba(matrix(test, columns))[:, 1]
                aucs.append(roc_auc_score(y_test, scores))
                recalls.append(float(np.mean(scores[y_test == 1] > threshold)))
                fprs.append(float(np.mean(scores[y_test == 0] > threshold)))
            per_family[held_out] = {
                "auc_mean": round(float(np.mean(aucs)), 4), "auc_min": round(float(np.min(aucs)), 4),
                "recall_at_val_fpr1_mean": round(float(np.mean(recalls)), 4),
                "test_human_fpr_mean": round(float(np.mean(fprs)), 4),
            }
        os_families = ("pynput", "pyhm", "naturalmousemotion")
        results[feature_set] = {
            "n_features": len(columns),
            "held_out": per_family,
            "os_bots_mean_auc": round(float(np.mean([per_family[f]["auc_mean"] for f in os_families])), 4),
            "os_bots_mean_recall": round(float(np.mean([per_family[f]["recall_at_val_fpr1_mean"] for f in os_families])), 4),
            "worst_os_recall": round(float(min(per_family[f]["recall_at_val_fpr1_mean"] for f in os_families)), 4),
        }
    return results


def feature_importance(samples, seed=0):
    names = sorted({k for s in samples for k in s["row"]})
    y = np.array([s["label"] for s in samples])
    model = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=seed, n_jobs=1)
    model.fit(matrix(samples, names), y)
    gains = model.get_booster().get_score(importance_type="gain")
    ranked = sorted(((names[int(k[1:])], v) for k, v in gains.items()), key=lambda item: -item[1])
    return [{"feature": n, "gain": round(float(v), 3)} for n, v in ranked[:25]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delbot-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    samples = load_dataset(Path(args.delbot_dir))
    counts = {}
    for s in samples:
        counts[s["group"]] = counts.get(s["group"], 0) + 1
    report = {
        "dataset": "DELBOT-Mouse circle drawings (MIT); one sample = one drawing, not one person",
        "counts": counts,
        "protocol": "leave-one-bot-family-out; humans split 60/20/20 per source; threshold = 99th "
                    "percentile of validation-human scores; 3 seeds",
        "results": run(samples),
        "importance_all_features": feature_importance(samples),
    }
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, res in report["results"].items():
        print(f"{name:32s} n={res['n_features']:3d} osAUC={res['os_bots_mean_auc']:.4f} "
              f"osRecall@FPR1={res['os_bots_mean_recall']:.3f} worst={res['worst_os_recall']:.3f} "
              f"gan={res['held_out']['gan']['recall_at_val_fpr1_mean']:.3f}")


if __name__ == "__main__":
    main()
