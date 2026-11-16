"""Policy 41 evaluation. Replay matching as production sees it: original and replay are each cut into collector 1.17
exports (300 new moves + 100 of context) at DIFFERENT offsets; signatures are taken per export.
Usage: python -m core_ml.evaluate_replay <dataset_root>"""
import sys
from collections import defaultdict

import numpy as np

import core_ml.features.trajectory_signature as ts
from core_ml.dataset.loader import load_real_dataset
from core_ml.train import deduplicate_real_sessions

root = sys.argv[1]
ss = deduplicate_real_sessions([s for sc in ("humans_and_moderate_bots", "humans_and_advanced_bots")
                                for s in load_real_dataset(root, scenario=sc, include_phase2=True, with_metadata=True)])
humans = [[{"time": float(r["time"]), "type": "move", "x": float(r["x"]), "y": float(r["y"])} for r in s.records
           if r.get("type", "move") == "move"][:3000] for s in ss if not s.label]
rng = np.random.default_rng(9)


def exported(moves, first):
    out, cut, prev = set(), first, 0
    while prev < len(moves):
        start = max(0, prev - 100)
        out |= {h for h in ts.signatures(moves[start:cut]) if h[0] in "01"}
        prev, cut = cut, cut + 300
    return out


def replay(m, kind):
    if kind == "exact":
        return m
    if kind == "speed1.5":
        return [{**r, "time": r["time"] / 1.5} for r in m]
    if kind == "resample":
        out = []
        for a, b in zip(m, m[1:]):
            out += [a, {**a, "x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2, "time": (a["time"] + b["time"]) / 2}]
        return out[::3]
    if kind.startswith("jitter"):
        s = float(kind[6:])
        return [{**r, "x": r["x"] + rng.normal(0, s / 1366), "y": r["y"] + rng.normal(0, s / 768)} for r in m]


for seg, turns, smooth, still in [(ts.SIGNATURE_SEGMENTS, ts.MIN_TURNS, ts.SMOOTHING, ts.STILL_MS)]:
    sig = [exported(h, 300) for h in humans]
    owners = defaultdict(set)
    for i, s in enumerate(sig):
        for h in s:
            owners[h].add(i)
    best = []
    for i, s in enumerate(sig):
        per = defaultdict(int)
        for h in s:
            for j in owners[h]:
                if j != i:
                    per[j] += 1
        best.append(max(per.values()) if per else 0)
    line = (f"seg={seg} turns>={turns} smooth={smooth} still={still} | sampled/session med {int(np.median([len(s) for s in sig]))} "
            f"| humans max one-session overlap {max(best)} p99 {np.quantile(best, .99):.0f}")
    for kind in ("exact", "speed1.5", "resample", "jitter0.5", "jitter1"):
        hits = [len(exported(replay(humans[i][:1500], kind), 217) & sig[i]) for i in range(40)]
        line += (f" | {kind} med {int(np.median(hits))} >=4 {np.mean([h >= 4 for h in hits]):.2f}"
                 f" >=8 {np.mean([h >= 8 for h in hits]):.2f}")
    print(line, flush=True)
