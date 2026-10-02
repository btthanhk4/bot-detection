"""Measure interaction coverage on independent runs before training new features."""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

from core_ml.dataset.field_captures import load_bot_captures, load_human_captures
from core_ml.evaluate import _load_detector
from core_ml.features.interaction_features import (
    INTERACTION_FEATURE_NAMES,
    INTERACTION_FEATURE_VERSION,
    extract_interaction_features,
)
from core_ml.train import PRODUCTION_DECISION_THRESHOLD


def evaluate_interaction_captures(detector, captures):
    """Summarize final windows per run; do not inflate counts with repeated sends."""
    if not captures:
        raise ValueError("At least one independently labeled capture is required")
    ids = [capture.capture_id for capture in captures]
    sessions = [capture.final_payload["sessionId"] for capture in captures]
    if len(set(ids)) != len(ids) or len(set(sessions)) != len(sessions):
        raise ValueError("Capture sets must not share capture or session IDs")
    groups = {}
    for capture in captures:
        measurements = [extract_interaction_features(payload.get("mouse"))
                        for payload in capture.sent_snapshots]
        verdicts = [detector.predict(payload)["verdict"] for payload in capture.sent_snapshots]
        group = groups.setdefault((capture.label, capture.family), {
            "runs": 0, "sent_snapshots": 0, "baseline_final": Counter(),
            "baseline_ever_human": 0, "baseline_ever_bot": 0,
            "final_measurements": [],
        })
        group["runs"] += 1
        group["sent_snapshots"] += len(verdicts)
        group["baseline_final"].update([verdicts[-1]])
        group["baseline_ever_human"] += "HUMAN" in verdicts
        group["baseline_ever_bot"] += "BOT" in verdicts
        group["final_measurements"].append(measurements[-1])
    rendered = []
    for (label, family), group in sorted(groups.items()):
        measurements = group.pop("final_measurements")
        features = {}
        for name in INTERACTION_FEATURE_NAMES:
            values = [row["features"][name] for row in measurements
                      if row["features"][name] is not None]
            features[name] = {
                "available_runs": len(values),
                "median": round(median(values), 6) if values else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
        rendered.append({
            "label": label, "family": family,
            **{key: dict(sorted(value.items())) if isinstance(value, Counter) else value
               for key, value in group.items()},
            "features": features,
            "final_count_medians": {
                name: median(row["counts"][name] for row in measurements)
                for name in measurements[0]["counts"]
            },
        })
    return {
        "feature_version": INTERACTION_FEATURE_VERSION,
        "mode": "measurement_only", "release_approved": False,
        "runs": len(captures),
        "human_runs": sum(capture.label == "HUMAN" for capture in captures),
        "human_participants": len({capture.participant_id for capture in captures
                                   if capture.label == "HUMAN" and capture.participant_id}),
        "note": "Final retained windows, not session totals or production accuracy; no classifier fitted",
        "groups": rendered,
    }


def main(capture_dir, weights_dir, human_capture_dir=None):
    captures = load_bot_captures(capture_dir)
    if human_capture_dir:
        captures.extend(load_human_captures(human_capture_dir))
    detector, manifest = _load_detector(weights_dir, PRODUCTION_DECISION_THRESHOLD)
    report = evaluate_interaction_captures(detector, captures)
    report["bundle_id"] = manifest["bundle_id"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--human-capture-dir")
    parser.add_argument("--weights-dir", default="core_ml/weights")
    parser.add_argument("--output", help="Aggregate report only; no raw visitor identifiers")
    args = parser.parse_args()
    rendered = json.dumps(main(args.capture_dir, args.weights_dir, args.human_capture_dir),
                          indent=2, sort_keys=True, allow_nan=False)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
