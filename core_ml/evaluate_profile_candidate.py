"""Replay the opt-in profile policy through the actual ensemble prediction path."""

import argparse
import json
from collections import Counter
from pathlib import Path

from core_ml.collector_windows import export_window
from core_ml.dataset.field_captures import load_bot_captures, load_human_captures
from core_ml.dataset.loader import load_real_dataset
from core_ml.evaluate import _load_detector
from core_ml.features.profile_policy import PROFILE_CANDIDATE_RULE
from core_ml.models.ensemble import DECISION_POLICY_VERSION
from core_ml.train import PRODUCTION_DECISION_THRESHOLD, deduplicate_real_sessions


def _compare_run(detector, snapshots, group):
    if not snapshots:
        raise ValueError("A run must contain sent snapshots")
    base, candidate = [], []
    for snapshot in snapshots:
        before = detector.predict(snapshot)
        after = detector.predict(snapshot, profile_candidate=True)
        base.append(before["verdict"])
        candidate.append(after["verdict"])
        group["sent_snapshots"] += 1
        group["changed_snapshots"] += before["verdict"] != after["verdict"]
        group["transitions"].update([f"{before['verdict']}->{after['verdict']}"])
        group["rule_hits"] += after["breakdown"]["automation_rule"] == PROFILE_CANDIDATE_RULE
        group["profile_covered_snapshots"] += after["breakdown"]["profile_shadow"]["available_checks"] > 0
    group["runs"] += 1
    group["changed_runs"] += base != candidate
    for name, verdicts in (("baseline", base), ("candidate", candidate)):
        group[f"{name}_final"].update([verdicts[-1]])
        group[f"{name}_ever_human"] += "HUMAN" in verdicts
        group[f"{name}_ever_bot"] += "BOT" in verdicts


def _group(groups, key):
    return groups.setdefault(key, {
        "runs": 0, "sent_snapshots": 0, "changed_snapshots": 0, "changed_runs": 0,
        "profile_covered_snapshots": 0, "rule_hits": 0, "transitions": Counter(),
        "baseline_final": Counter(), "candidate_final": Counter(),
        "baseline_ever_human": 0, "candidate_ever_human": 0,
        "baseline_ever_bot": 0, "candidate_ever_bot": 0,
    })


def evaluate_candidate(detector, captures, mouse_sessions=()):
    if not captures:
        raise ValueError("At least one labeled browser capture is required")
    ids, sessions = set(), set()
    for capture in captures:
        if capture.label not in ("HUMAN", "BOT") or not capture.sent_snapshots:
            raise ValueError("Capture needs an independent label and sent snapshots")
        session = capture.final_payload["sessionId"]
        if capture.capture_id in ids or session in sessions:
            raise ValueError("Capture/session IDs must be unique across all inputs")
        ids.add(capture.capture_id)
        sessions.add(session)
    groups = {}
    for capture in captures:
        _compare_run(detector, capture.sent_snapshots,
                     _group(groups, ("browser", capture.label, capture.family)))
    for session in mouse_sessions:
        if not session.records:
            raise ValueError("Mouse controls must contain records")
        window = export_window(session.records, len(session.records) - 1)
        _compare_run(detector, [{"mouse": {"records": window}}],
                     _group(groups, ("mouse_only", "BOT" if session.label else "HUMAN", session.source)))
    return {
        "baseline_policy": DECISION_POLICY_VERSION,
        "candidate_policy": f"{DECISION_POLICY_VERSION}+{PROFILE_CANDIDATE_RULE}",
        "release_approved": False,
        "browser_runs": len(captures),
        "human_browser_runs": sum(c.label == "HUMAN" for c in captures),
        "human_participants": len({c.participant_id for c in captures
                                   if c.label == "HUMAN" and c.participant_id}),
        "note": "No training. Sent snapshots only, excluding final probes. Mouse-only controls "
                "have no browser profile and cannot validate profile false-positive rates.",
        "groups": [
            {"source": source, "label": label, "family": family,
             **{k: dict(sorted(v.items())) if isinstance(v, Counter) else v for k, v in group.items()}}
            for (source, label, family), group in sorted(groups.items())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", action="append", required=True)
    parser.add_argument("--human-capture-dir", action="append", default=[])
    parser.add_argument("--dataset-root", help="Optional mouse-only compatibility controls")
    parser.add_argument("--weights-dir", default="core_ml/weights")
    parser.add_argument("--output", required=True, help="Aggregate output; no raw identities")
    args = parser.parse_args()
    captures = [capture for directory in args.capture_dir for capture in load_bot_captures(directory)]
    captures.extend(capture for directory in args.human_capture_dir
                    for capture in load_human_captures(directory))
    controls = []
    if args.dataset_root:
        for scenario in ("humans_and_moderate_bots", "humans_and_advanced_bots"):
            controls.extend(load_real_dataset(args.dataset_root, scenario=scenario,
                                              include_phase2=True, with_metadata=True))
        controls = deduplicate_real_sessions(controls)
        if not controls:
            raise ValueError("Requested mouse-control dataset is empty")
    detector, manifest = _load_detector(args.weights_dir, PRODUCTION_DECISION_THRESHOLD)
    report = evaluate_candidate(detector, captures, controls)
    report["bundle_id"] = manifest["bundle_id"]
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
