"""Replay held-out mouse sessions against a frozen bundle without retraining."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import torch

from core_ml.collector_windows import rolling_windows
from core_ml.dataset.loader import load_real_dataset
from core_ml.evaluate import _load_detector
from core_ml.features.mouse_features import prefix_through_moves
from core_ml.train import assign_real_session_splits, deduplicate_real_sessions, records_signature


DESKTOP_FINGERPRINT = {
    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "hardwareConcurrency": 8,
    "deviceMemory": 8,
    "maxTouchPoints": 0,
    "screenResolution": "1920x1080",
    "colorDepth": 24,
    "pixelRatio": 1,
    "pluginsLength": 5,
    "fontsCount": 10,
    "audioHash": "35.12345",
    "canvasHash": "browser-probe",
}


def evaluate_robustness(dataset_root: str, weights_dir: str, *, split="val", checkpoints=100,
                        desktop_fingerprint=False, threshold=0.96,
                        heuristic_score=0.0, webdriver=False, suspect_threshold=0.45,
                        lstm_p75_min_mean=0.70, full_replay=False):
    if split not in ("val", "test"):
        raise ValueError("Robustness evaluation requires a held-out val or test split")
    if not math.isfinite(heuristic_score) or not 0.0 <= heuristic_score <= 1.0:
        raise ValueError("heuristic_score must be between zero and one")
    if not math.isfinite(suspect_threshold) or not 0.0 <= suspect_threshold <= threshold:
        raise ValueError("suspect_threshold must be between zero and the BOT threshold")
    if not math.isfinite(lstm_p75_min_mean) or not 0.0 <= lstm_p75_min_mean <= 1.0:
        raise ValueError("lstm_p75_min_mean must be between zero and one")
    sessions = deduplicate_real_sessions([
        session
        for scenario in ("humans_and_moderate_bots", "humans_and_advanced_bots")
        for session in load_real_dataset(
            dataset_root, scenario=scenario, include_phase2=True, with_metadata=True,
        )
    ])
    selected = [
        session for session, assignment in zip(sessions, assign_real_session_splits(sessions))
        if assignment == split
    ]
    detector, manifest = _load_detector(weights_dir, threshold)
    policy_version = str(manifest.get("training", {}).get("decision_policy_version", ""))
    if policy_version == "9" and lstm_p75_min_mean != 0.70:
        raise ValueError("lstm_p75_min_mean is a legacy-only setting and does not affect policy v9")
    detector.suspect_threshold = suspect_threshold
    if policy_version != "9" and hasattr(detector, "lstm_model"):
        detector.lstm_model.p75_min_weighted_mean = lstm_p75_min_mean
    training_hashes = set(
        manifest.get("training", {}).get("dataset", {})
        .get("trajectory_hashes_by_split", {}).get("train", [])
    )
    if training_hashes & {records_signature(session.records) for session in selected}:
        raise ValueError("Evaluation split overlaps model training trajectories")

    if full_replay:
        phase2_ids = {session.session_id for session in selected if session.source == "phase2"}
        replay_by_id = {}
        if phase2_ids:
            for scenario in ("humans_and_moderate_bots", "humans_and_advanced_bots"):
                for session in load_real_dataset(
                    dataset_root, scenario=scenario, include_phase2=True,
                    with_metadata=True, replay_session_ids=phase2_ids,
                ):
                    if session.session_id in phase2_ids and session.replay_records:
                        replay_by_id[session.session_id] = session.replay_records
        for session in selected:
            if session.source == "phase2" and session.session_id not in replay_by_id:
                raise ValueError(f"Missing full replay records for {session.session_id}")
            session.replay_records = replay_by_id.get(session.session_id)

    rolling = {"human": Counter(), "bot": Counter()}
    transitions = {"human": Counter(), "bot": Counter()}
    timing = {str(factor): {"human": Counter(), "bot": Counter()}
              for factor in (0.5, 1.0, 2.0)}
    human_ever_bot = bot_ever_human = human_ever_suspect = 0
    human_bot_details = []
    bot_human_details = []
    bot_gate_counts = {rule: {"human": Counter(), "bot": Counter()} for rule in (
        "risk_96", "tabular_95", "both_90", "both_95",
    )}
    fingerprint = DESKTOP_FINGERPRINT if desktop_fingerprint else {}
    botd = {"heuristicScore": heuristic_score, "detectors": {"webdriver": webdriver}}
    for session in selected:
        label = "bot" if session.label else "human"
        verdicts = []
        for window in rolling_windows(session.replay_records or session.records, checkpoints=checkpoints):
            decision = detector.predict({
                "mouse": {"records": window}, "fingerprint": fingerprint, "botd": botd,
            })
            verdict = decision["verdict"]
            rolling[label][verdict] += 1
            verdicts.append(verdict)
            if verdict == "BOT":
                breakdown = decision.get("breakdown") or {}
                risk = decision.get("risk_score", 0)
                lstm = breakdown.get("behavioral_lstm_score", 0)
                tabular = breakdown.get("tabular_score", 0)
                gates = {
                    "risk_96": risk >= 0.96,
                    "tabular_95": tabular >= 0.95,
                    "both_90": min(lstm, tabular) >= 0.90,
                    "both_95": min(lstm, tabular) >= 0.95,
                }
                for rule, passed in gates.items():
                    bot_gate_counts[rule][label]["retained" if passed else "downgraded"] += 1
            if label == "human" and verdict == "BOT":
                human_bot_details.append({
                    "session_id": session.session_id,
                    "source": session.source,
                    "last_window_time": window[-1]["time"],
                    "risk": decision["risk_score"],
                    "lstm": decision["breakdown"]["behavioral_lstm_score"],
                    "tabular": decision["breakdown"]["tabular_score"],
                })
            if label == "bot" and verdict == "HUMAN":
                bot_human_details.append({
                    "session_id": session.session_id,
                    "source": session.source,
                    "last_window_time": window[-1]["time"],
                    "risk": decision.get("risk_score"),
                    "lstm": (decision.get("breakdown") or {}).get("behavioral_lstm_score"),
                    "tabular": (decision.get("breakdown") or {}).get("tabular_score"),
                })
        if label == "human":
            human_ever_bot += "BOT" in verdicts
            human_ever_suspect += "SUSPECT" in verdicts
        else:
            bot_ever_human += "HUMAN" in verdicts
        transitions[label].update(
            f"{previous}->{current}"
            for previous, current in zip(verdicts, verdicts[1:])
            if previous != current
        )

        early = prefix_through_moves(session.early_records or session.records, 100)
        for factor in (0.5, 1.0, 2.0):
            scaled = [{**record, "time": record["time"] * factor} for record in early]
            verdict = detector.predict({
                "mouse": {"records": scaled}, "fingerprint": fingerprint, "botd": botd,
            })["verdict"]
            timing[str(factor)][label][verdict] += 1

    return {
        "bundle_id": manifest["bundle_id"],
        "split": split,
        "checkpoints_per_session": checkpoints,
        "threshold": threshold,
        "suspect_threshold": suspect_threshold,
        "decision_policy_version": policy_version,
        "legacy_lstm_p75_min_mean": lstm_p75_min_mean if policy_version != "9" else None,
        "full_replay": full_replay,
        "desktop_fingerprint": desktop_fingerprint,
        "heuristic_score": heuristic_score,
        "webdriver": webdriver,
        "session_counts": dict(Counter("bot" if s.label else "human" for s in selected)),
        "rolling_windows": {label: dict(counts) for label, counts in rolling.items()},
        "verdict_transitions": {label: dict(counts) for label, counts in transitions.items()},
        "human_sessions_ever_bot": human_ever_bot,
        "human_bot_details": human_bot_details,
        "bot_human_details": bot_human_details,
        "bot_gate_counts": {
            rule: {label: dict(counts) for label, counts in labels.items()}
            for rule, labels in bot_gate_counts.items()
        },
        "human_sessions_ever_suspect": human_ever_suspect,
        "bot_sessions_ever_human": bot_ever_human,
        "timing_first_100_moves": {
            factor: {label: dict(counts) for label, counts in labels.items()}
            for factor, labels in timing.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--weights-dir", required=True)
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument("--checkpoints", type=int, default=100)
    parser.add_argument("--threshold", type=float, default=0.96)
    parser.add_argument("--suspect-threshold", type=float, default=0.45)
    parser.add_argument("--desktop-fingerprint", action="store_true")
    parser.add_argument("--heuristic-score", type=float, default=0.0)
    parser.add_argument("--webdriver", action="store_true")
    parser.add_argument("--lstm-p75-min-mean", type=float, default=0.70)
    parser.add_argument("--full-replay", dest="full_replay", action="store_true")
    parser.add_argument("--retained-replay", dest="full_replay", action="store_false")
    parser.set_defaults(full_replay=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    torch.set_num_threads(1)
    report = evaluate_robustness(
        args.dataset_root, args.weights_dir, split=args.split, checkpoints=args.checkpoints,
        desktop_fingerprint=args.desktop_fingerprint, threshold=args.threshold,
        heuristic_score=args.heuristic_score, webdriver=args.webdriver,
        suspect_threshold=args.suspect_threshold,
        lstm_p75_min_mean=args.lstm_p75_min_mean, full_replay=args.full_replay,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
