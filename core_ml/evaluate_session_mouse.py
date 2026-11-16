"""Offline A/B on held-out benchmark sessions through the real code path.

cur: policy 39, every snapshot judged on its collector window (last 100 records), final verdict = the
     last snapshot's, BOT locked by two BOT snapshots.
p40: collector 1.17 exports (moves since the previous snapshot + 100 moves of context, moveBase) and
     the API's session store emulated: each snapshot gets the session's stored scores (_session_mouse).

Coordinates are normalised once per session (as the collector does by viewport), the same for both.
Usage: python -m core_ml.evaluate_session_mouse <dataset_root> <split> <every_moves> <out.json>
"""
import json
import sys
from collections import Counter

import torch

from core_ml.collector_windows import export_window
from core_ml.dataset.loader import load_real_dataset
from core_ml.evaluate import _load_detector
from core_ml.train import assign_real_session_splits, deduplicate_real_sessions

torch.set_num_threads(2)
root, split, every, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
det, manifest = _load_detector("core_ml/weights", 0.96)
print("bundle", manifest["bundle_id"], flush=True)
sessions = deduplicate_real_sessions([
    s for sc in ("humans_and_moderate_bots", "humans_and_advanced_bots")
    for s in load_real_dataset(root, scenario=sc, include_phase2=True, with_metadata=True)])
sel = [s for s, a in zip(sessions, assign_real_session_splits(sessions)) if a == split]
ids = {s.session_id for s in sel if s.source == "phase2"}
replay = {}
for sc in ("humans_and_moderate_bots", "humans_and_advanced_bots"):
    for s in load_real_dataset(root, scenario=sc, include_phase2=True, with_metadata=True, replay_session_ids=ids):
        if s.session_id in ids and s.replay_records:
            replay[s.session_id] = s.replay_records
print("sessions", len(sel), Counter("bot" if s.label else "human" for s in sel), flush=True)
BOTD = {"heuristicScore": 0.0, "detectors": {}}


def normalise(records):
    xs = [abs(float(r.get("x", 0))) for r in records]
    ys = [abs(float(r.get("y", 0))) for r in records]
    sw = max(1920.0, max(xs)) if max(xs) > 1.0 else 1.0
    sh = max(1080.0, max(ys)) if max(ys) > 1.0 else 1.0
    return [{"time": float(r["time"]), "type": r.get("type", "move"), "source": r.get("source", "mouse"),
             "x": float(r["x"]) / sw, "y": float(r["y"]) / sh} for r in records]


def label_of(result):
    return result["verdict"] if result["decision_state"] == "FINAL" else "DEFER"


def final(seq):
    return "BOT" if seq.count("BOT") >= 2 else seq[-1]


tot = {k: {"human": Counter(), "bot": Counter()} for k in ("cur", "p40")}
snaps = {k: {"human": Counter(), "bot": Counter()} for k in ("cur", "p40")}
ever = {k: {"human": Counter(), "bot": Counter()} for k in ("cur_suspect", "p40_suspect", "cur_human", "p40_human")}
rows = []
for s in sel:
    label = "bot" if s.label else "human"
    R = normalise(replay.get(s.session_id) or s.records)
    mv = [i for i, r in enumerate(R) if r["type"] == "move" and r["source"] != "touch"]
    if len(mv) < 25:
        continue
    ends = list(range(24, len(mv), every))
    if ends[-1] != len(mv) - 1:
        ends.append(len(mv) - 1)
    cur, p40 = [], []
    prior = {"chunks": {}, "windows": {}}
    prev_m = 0
    for k in ends:
        e = mv[k]
        cur.append(label_of(det.predict({"mouse": {"records": export_window(R, e)}, "fingerprint": {}, "botd": BOTD})))
        m = k + 1
        base = max(0, prev_m - 100)
        start = mv[base]
        export = R[start:e + 1]
        result = det.predict({
            "sessionId": s.session_id, "collector": {"pageInstanceId": s.session_id},
            "mouse": {"records": export, "moveBase": base, "frameMoves": m, "coordinateFrame": {"id": 0}},
            "fingerprint": {}, "botd": BOTD, "_session_mouse": prior,
        })
        new = result.get("_session_mouse_new") or {}
        prior = {"chunks": {**prior["chunks"], **(new.get("chunks") or {})},
                 "windows": {**prior["windows"], **(new.get("windows") or {})}}
        p40.append(label_of(result))
        prev_m = m
    for name, seq in (("cur", cur), ("p40", p40)):
        tot[name][label][final(seq)] += 1
        snaps[name][label].update(seq)
    ever["cur_suspect"][label]["SUSPECT" in cur] += 1
    ever["p40_suspect"][label]["SUSPECT" in p40] += 1
    ever["cur_human"][label]["HUMAN" in cur] += 1
    ever["p40_human"][label]["HUMAN" in p40] += 1
    rows.append({"id": s.session_id, "label": label, "moves": len(mv), "cur": final(cur), "p40": final(p40),
                 "cur_seq": "".join(v[0] for v in cur), "p40_seq": "".join(v[0] for v in p40)})

for title, table in (("final", tot), ("snapshots", snaps), ("ever", ever)):
    for k, v in table.items():
        print(f"{title:9} {k:12}", {lab: dict(c) for lab, c in v.items()})
json.dump({"final": {k: {lab: dict(c) for lab, c in v.items()} for k, v in tot.items()},
           "snapshots": {k: {lab: dict(c) for lab, c in v.items()} for k, v in snaps.items()},
           "ever": {k: {lab: {str(b): n for b, n in c.items()} for lab, c in v.items()} for k, v in ever.items()},
           "rows": rows}, open(out, "w"), indent=1)
