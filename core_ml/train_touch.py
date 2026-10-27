"""Train the touch shadow model: human swipes against synthetic swipe generators.

Humans: BrainRun (Papamichail et al., 2019, CC0, Zenodo 2598135): Android and
iOS phones playing cognitive games (short flicks, no per-point times);
Touchalytics (Frank et al., 2013, 41 people reading Wikipedia and comparing
images on Android, per-point times): the scrolling a shop visitor does; plus,
with ``--live``, swipes stored by the live site (``label_hint ==
"human_candidate"``, exported from ``/api/v1/touch-samples/export``). Each
source is held out in turn to measure how often unseen humans are flagged.

Bots: every synthetic swipe copies the start, end, duration and point count of
a real human swipe, so the model can only learn how the path is drawn, not how
long or how far it goes. Four generators, from naive to humanised:

* ``linear``       CDP ``Input.dispatchTouchEvent`` / Playwright: straight, equal steps.
* ``linear_noise`` the same with pixel jitter and uneven steps.
* ``bezier_ease``  ghost-cursor style: a curved Bezier path with ease-in-out timing.
* ``lognormal``    BeCAPTCHA-style: a curved path with a sigma-lognormal speed profile,
                   the kinematics of a real hand movement.

Evaluation is generator-agnostic (each generator held out in turn; humans split
by device) because a deployed model meets bots it was not trained on.

    python -m core_ml.train_touch --brainrun <gestures.bson> [--touchalytics data.csv] [--live export.json ...]
"""

import argparse
import hashlib
import json
import math
import os
import random
from collections import defaultdict

import numpy as np

from core_ml.features.touch import MODEL_FEATURES, feature_vector, gesture_features

GENERATORS = ("linear", "linear_noise", "bezier_ease", "lognormal")
FRAME_MS = 1000.0 / 60.0
# The collector keeps the first 48 points of a gesture; train on what it sends.
MAX_POINTS = 48
# Touchalytics phones (Nexus One/S, Galaxy S, Droid Incredible) are hdpi.
TOUCHALYTICS_PX_PER_CSS = 1.5


def brainrun_points(doc):
    """BrainRun keeps one sample per move event and only the start/stop times."""
    data = doc.get("data") or []
    if not data:
        return None
    first = data[0]
    pts = [(float(first["x0"]), float(first["y0"]))] + [(float(d["moveX"]), float(d["moveY"])) for d in data]
    duration = float(doc.get("t_stop") or 0) - float(doc.get("t_start") or 0)
    if not 0 < duration < 5000 or not all(math.isfinite(v) for p in pts for v in p):
        return None
    step = duration / (len(pts) - 1) if len(pts) > 1 else 0.0
    return [[round(i * step, 1), x, y, None, None, None] for i, (x, y) in enumerate(pts)][:MAX_POINTS]


def load_brainrun(path, *, max_per_device=150, max_swipes=40000, seed=7):
    import bson

    rng = random.Random(seed)
    by_device = defaultdict(list)
    with open(path, "rb") as handle:
        for doc in bson.decode_file_iter(handle):
            if doc.get("type") != "swipe":
                continue
            device = doc.get("device_id")
            bucket = by_device[device]
            if len(bucket) >= max_per_device * 3:
                continue
            points = brainrun_points(doc)
            if points and len(points) >= 3 and gesture_features(points)["kind"] == "swipe":
                bucket.append(points)
    swipes, groups = [], []
    for device, bucket in by_device.items():
        rng.shuffle(bucket)
        for points in bucket[:max_per_device]:
            swipes.append(points)
            groups.append(f"brainrun:{device}")
    order = list(range(len(swipes)))
    rng.shuffle(order)
    order = order[:max_swipes]
    return [swipes[i] for i in order], [groups[i] for i in order]


def load_touchalytics(path, *, max_per_user=400, seed=7):
    """Strokes are touch-down .. touch-up rows; times are absolute ms."""
    import csv

    rng = random.Random(seed)
    by_user, open_strokes = defaultdict(list), {}
    with open(path, newline="") as handle:
        for row in csv.reader(handle):
            key = (row[0], row[1], row[2])
            action = int(row[4])
            point = [int(row[3]), float(row[6]) / TOUCHALYTICS_PX_PER_CSS, float(row[7]) / TOUCHALYTICS_PX_PER_CSS,
                     None, None, None]
            if action == 0:
                open_strokes[key] = [point]
            elif key in open_strokes:
                open_strokes[key].append(point)
                if action == 1:
                    stroke = open_strokes.pop(key)
                    start = stroke[0][0]
                    points = [[p[0] - start] + p[1:] for p in stroke][:MAX_POINTS]
                    ordered = all(points[i][0] >= points[i - 1][0] for i in range(1, len(points)))
                    if ordered and len(points) >= 3 and gesture_features(points)["kind"] == "swipe":
                        by_user[row[1]].append(points)
    swipes, groups = [], []
    for user, bucket in by_user.items():
        rng.shuffle(bucket)
        swipes += bucket[:max_per_user]
        groups += [f"touchalytics:{user}"] * len(bucket[:max_per_user])
    return swipes, groups


def load_live(paths):
    swipes, groups = [], []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            page = json.load(handle)
        for sample in page.get("samples", page if isinstance(page, list) else []):
            if sample.get("label_hint") != "human_candidate":
                continue
            points = (sample.get("points") or [])[:MAX_POINTS]
            if len(points) >= 3 and gesture_features(points)["kind"] == "swipe":
                swipes.append(points)
                groups.append(f"live:{sample.get('visitorId') or sample.get('sessionId')}")
    return swipes, groups


def _bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _controls(rng, start, end, spread):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    c1 = (start[0] + dx / 3 + nx * rng.gauss(0, spread) * length, start[1] + dy / 3 + ny * rng.gauss(0, spread) * length)
    c2 = (start[0] + 2 * dx / 3 + nx * rng.gauss(0, spread) * length, start[1] + 2 * dy / 3 + ny * rng.gauss(0, spread) * length)
    return c1, c2


def _lognormal_progress(n, rng):
    """Cumulative distance of a sigma-lognormal speed profile sampled at n frames."""
    mu, sigma = rng.uniform(-1.6, -0.9), rng.uniform(0.25, 0.55)
    ts = [(i + 0.5) / n for i in range(n)]
    speed = [math.exp(-((math.log(t) - mu) ** 2) / (2 * sigma * sigma)) / (t * sigma) for t in ts]
    total = sum(speed)
    out, acc = [0.0], 0.0
    for v in speed:
        acc += v / total
        out.append(acc)
    return out[:n] + [1.0]


def synthesize(kind, template, rng):
    """A bot swipe with the template's start, end, duration and point count."""
    n = len(template)
    start, end = (template[0][1], template[0][2]), (template[-1][1], template[-1][2])
    duration = template[-1][0]
    if kind == "linear":
        progress = [i / (n - 1) for i in range(n)]
        xy = [(start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t) for t in progress]
    elif kind == "linear_noise":
        cuts = sorted(rng.uniform(0, 1) * 0.3 + (i / (n - 1)) * 0.7 for i in range(1, n - 1))
        progress = [0.0] + cuts + [1.0]
        sigma = rng.uniform(0.3, 2.0)
        xy = [(start[0] + (end[0] - start[0]) * t + rng.gauss(0, sigma),
               start[1] + (end[1] - start[1]) * t + rng.gauss(0, sigma)) for t in progress]
        xy[0], xy[-1] = start, end
    elif kind == "bezier_ease":
        c1, c2 = _controls(rng, start, end, rng.uniform(0.02, 0.2))
        progress = [i / (n - 1) for i in range(n)]
        eased = [2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2 for t in progress]
        sigma = rng.uniform(0.0, 1.0)
        xy = [_bezier(start, c1, c2, end, t) for t in eased]
        xy = [(x + rng.gauss(0, sigma), y + rng.gauss(0, sigma)) for x, y in xy]
    elif kind == "lognormal":
        c1, c2 = _controls(rng, start, end, rng.uniform(0.02, 0.15))
        xy = [_bezier(start, c1, c2, end, t) for t in _lognormal_progress(n - 1, rng)]
        sigma = rng.uniform(0.0, 0.8)
        xy = [(x + rng.gauss(0, sigma), y + rng.gauss(0, sigma)) for x, y in xy]
    else:
        raise ValueError(kind)
    step = duration / (n - 1)
    return [[round(i * step, 1), round(x, 1), round(y, 1), None, None, None] for i, (x, y) in enumerate(xy)]


def _matrix(swipes):
    return np.asarray([feature_vector(gesture_features(points)) for points in swipes], dtype=np.float32)


def _metrics(y_true, scores):
    from sklearn.metrics import roc_auc_score, roc_curve

    fpr, tpr, _ = roc_curve(y_true, scores)

    def tpr_at(limit):
        return float(max((t for f, t in zip(fpr, tpr) if f <= limit), default=0.0))

    return {"auc": round(float(roc_auc_score(y_true, scores)), 4),
            "tpr_at_fpr_1pct": round(tpr_at(0.01), 4), "tpr_at_fpr_5pct": round(tpr_at(0.05), 4)}


def _session_metrics(y_true, scores, groups, size=5, seed=3):
    """Mean score over groups of `size` swipes from one device (or one generator)."""
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for label, score, group in zip(y_true, scores, groups):
        buckets[(label, group)].append(score)
    labels, means = [], []
    for (label, _), values in buckets.items():
        rng.shuffle(values)
        for i in range(0, len(values) - size + 1, size):
            labels.append(label)
            means.append(float(np.mean(values[i:i + size])))
    return _metrics(labels, means) if len(set(labels)) == 2 else None


def _five_swipe_means(scores, groups, size=5):
    buckets = defaultdict(list)
    for score, group in zip(scores, groups):
        buckets[group].append(float(score))
    return [float(np.mean(v[i:i + size])) for v in buckets.values() for i in range(0, len(v) - size + 1, size)]


def _fit(x, y, seed):
    import xgboost as xgb

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.08, subsample=0.8, colsample_bytree=0.8,
        min_child_weight=5, eval_metric="logloss", random_state=seed, n_jobs=4,
    )
    model.fit(x, y)
    return model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--brainrun", required=True, help="gestures.bson from Zenodo record 2598135")
    parser.add_argument("--touchalytics", help="data.csv from mariofrank.net/touchalytics")
    parser.add_argument("--live", nargs="*", default=[], help="JSON pages from /api/v1/touch-samples/export")
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "data"))
    parser.add_argument("--max-swipes", type=int, default=40000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)

    humans, groups = load_brainrun(args.brainrun, max_swipes=args.max_swipes, seed=args.seed)
    if args.touchalytics:
        extra, extra_groups = load_touchalytics(args.touchalytics, seed=args.seed)
        humans += extra
        groups += extra_groups
    live, live_groups = load_live(args.live)
    humans += live
    groups += live_groups
    sources = defaultdict(int)
    for group in groups:
        sources[group.split(":", 1)[0]] += 1
    print(f"human swipes: {dict(sources)} from {len(set(groups))} devices/people")

    devices = sorted(set(groups))
    rng.shuffle(devices)
    test_devices = set(devices[: max(1, len(devices) // 5)])
    split = [g in test_devices for g in groups]
    h_train = [s for s, t in zip(humans, split) if not t]
    h_test = [s for s, t in zip(humans, split) if t]
    h_test_groups = [g for g, t in zip(groups, split) if t]
    per_gen_train = max(1, len(h_train) // len(GENERATORS))
    per_gen_test = max(1, len(h_test) // len(GENERATORS))
    bots_train = {k: [synthesize(k, rng.choice(h_train), rng) for _ in range(per_gen_train)] for k in GENERATORS}
    bots_test = {k: [synthesize(k, rng.choice(h_test), rng) for _ in range(per_gen_test)] for k in GENERATORS}
    x_h_train, x_h_test = _matrix(h_train), _matrix(h_test)
    x_b_train = {k: _matrix(v) for k, v in bots_train.items()}
    x_b_test = {k: _matrix(v) for k, v in bots_test.items()}

    report = {"held_out_generator": {}, "all_generators": {}, "held_out_human_source": {}}
    # A human population never seen in training: how many of its swipes look like bots?
    for source in [s for s in sources if len(sources) > 1]:
        keep = [i for i, g in enumerate(groups) if not g.startswith(source + ":")]
        held = [i for i, g in enumerate(groups) if g.startswith(source + ":")]
        train_h = _matrix([humans[i] for i in keep])
        train_b = np.vstack([_matrix([synthesize(k, humans[rng.choice(keep)], rng)
                                      for _ in range(len(keep) // len(GENERATORS))]) for k in GENERATORS])
        model = _fit(np.vstack([train_h, train_b]), np.asarray([0] * len(train_h) + [1] * len(train_b)), args.seed)
        held_scores = model.predict_proba(_matrix([humans[i] for i in held]))[:, 1]
        five = _five_swipe_means(held_scores, [groups[i] for i in held])
        report["held_out_human_source"][source] = {
            "swipes": len(held), "swipe_flagged_at_0_5": round(float(np.mean(held_scores > 0.5)), 4),
            "five_swipe_flagged_at_0_5": round(float(np.mean(np.asarray(five) > 0.5)), 4) if five else None,
        }
        print(f"held out humans {source:13s} {report['held_out_human_source'][source]}")
    for held in GENERATORS:
        seen = [k for k in GENERATORS if k != held]
        # Same bot/human balance as the full model.
        x = np.vstack([x_h_train] + [x_b_train[k][: len(h_train) // len(seen)] for k in seen])
        y = np.asarray([0] * len(x_h_train) + [1] * (len(x) - len(x_h_train)))
        model = _fit(x, y, args.seed)
        scores = model.predict_proba(np.vstack([x_h_test, x_b_test[held]]))[:, 1]
        labels = [0] * len(x_h_test) + [1] * len(x_b_test[held])
        swipe_groups = h_test_groups + [f"bot:{i // 5}" for i in range(len(x_b_test[held]))]
        report["held_out_generator"][held] = {
            "swipe": _metrics(labels, scores), "five_swipes": _session_metrics(labels, scores, swipe_groups),
        }
        print(f"held out {held:13s} {report['held_out_generator'][held]}")

    x = np.vstack([x_h_train] + [x_b_train[k] for k in GENERATORS])
    y = np.asarray([0] * len(x_h_train) + [1] * (len(x) - len(x_h_train)))
    model = _fit(x, y, args.seed)
    for kind in GENERATORS:
        scores = model.predict_proba(np.vstack([x_h_test, x_b_test[kind]]))[:, 1]
        labels = [0] * len(x_h_test) + [1] * len(x_b_test[kind])
        report["all_generators"][kind] = _metrics(labels, scores)
    human_scores = model.predict_proba(x_h_test)[:, 1]
    report["human_test_score_p50_p95_p99"] = [round(float(np.quantile(human_scores, q)), 4) for q in (0.5, 0.95, 0.99)]
    print("trained on all generators:", report["all_generators"])

    # Refit on every human for the shipped model; evaluation above used held-out devices.
    x_all = np.vstack([x_h_train, x_h_test] + [x_b_train[k] for k in GENERATORS] + [x_b_test[k] for k in GENERATORS])
    y_all = np.asarray([0] * (len(x_h_train) + len(x_h_test))
                       + [1] * (len(x_all) - len(x_h_train) - len(x_h_test)))
    final = _fit(x_all, y_all, args.seed)
    os.makedirs(args.out_dir, exist_ok=True)
    model_path = os.path.join(args.out_dir, "touch_shadow_model.json")
    final.get_booster().feature_names = list(MODEL_FEATURES)
    final.get_booster().save_model(model_path)
    with open(model_path, "rb") as handle:
        model_id = hashlib.sha256(handle.read()).hexdigest()[:16]
    meta = {
        "model_id": model_id,
        "features": list(MODEL_FEATURES),
        "generators": list(GENERATORS),
        "human_sources": dict(sources),
        "devices": len(devices),
        "evaluation": report,
        "verdict_effect": "none (shadow only)",
    }
    with open(os.path.join(args.out_dir, "touch_shadow_meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    print(f"saved {model_path} ({model_id})")


if __name__ == "__main__":
    main()

