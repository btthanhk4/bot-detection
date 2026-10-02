"""Compare passive profile rules with the frozen model on labeled captures."""

import argparse
import json
from collections import Counter
from pathlib import Path

from core_ml.dataset.field_captures import load_bot_captures, load_human_captures
from core_ml.evaluate import _load_detector
from core_ml.features.profile_consistency import PROFILE_ANALYSIS_VERSION, analyze_profile_consistency
from core_ml.train import PRODUCTION_DECISION_THRESHOLD


def evaluate_profile_captures(detector, captures) -> dict:
    groups = {}
    for capture in captures:
        base_verdicts = []
        candidate_verdicts = []
        profiles = []
        for payload in capture.sent_snapshots:
            baseline = detector.predict(payload)["verdict"]
            profile = analyze_profile_consistency(payload)
            suggestion = profile["shadow_verdict"]
            candidate = baseline
            if baseline != "BOT" and suggestion == "BOT":
                candidate = "BOT"
            elif baseline == "HUMAN" and suggestion == "SUSPECT":
                candidate = "SUSPECT"
            base_verdicts.append(baseline)
            candidate_verdicts.append(candidate)
            profiles.append(profile)
        group = groups.setdefault((capture.label, capture.family), {
            "runs": 0, "runs_with_profile_checks": 0,
            "baseline_final": Counter(), "shadow_final": Counter(),
            "baseline_ever_human": 0, "shadow_ever_human": 0,
            "baseline_ever_bot": 0, "shadow_ever_bot": 0,
            "final_signals": Counter(),
        })
        group["runs"] += 1
        group["runs_with_profile_checks"] += profiles[-1]["available_checks"] > 0
        group["baseline_final"].update([base_verdicts[-1]])
        group["shadow_final"].update([candidate_verdicts[-1]])
        for name, verdicts in (("baseline", base_verdicts), ("shadow", candidate_verdicts)):
            group[f"{name}_ever_human"] += "HUMAN" in verdicts
            group[f"{name}_ever_bot"] += "BOT" in verdicts
        group["final_signals"].update({signal["code"] for signal in profiles[-1]["signals"]})
    return {
        "analysis_version": PROFILE_ANALYSIS_VERSION,
        "mode": "shadow",
        "release_approved": False,
        "runs": len(captures),
        "human_runs": sum(capture.label == "HUMAN" for capture in captures),
        "human_participants": len({capture.participant_id for capture in captures
                                   if capture.label == "HUMAN" and capture.participant_id}),
        "groups": [{
            "label": label, "family": family,
            **{key: dict(sorted(value.items())) if isinstance(value, Counter) else value
               for key, value in group.items()},
        } for (label, family), group in sorted(groups.items())],
    }


def main(capture_dir, weights_dir, human_capture_dir=None):
    captures = load_bot_captures(capture_dir)
    if human_capture_dir:
        captures.extend(load_human_captures(human_capture_dir))
    identities = [capture.capture_id for capture in captures]
    sessions = [capture.final_payload["sessionId"] for capture in captures]
    if len(set(identities)) != len(identities) or len(set(sessions)) != len(sessions):
        raise ValueError("BOT and HUMAN capture sets must not share capture or session IDs")
    detector, manifest = _load_detector(weights_dir, PRODUCTION_DECISION_THRESHOLD)
    report = evaluate_profile_captures(detector, captures)
    report["bundle_id"] = manifest["bundle_id"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--human-capture-dir")
    parser.add_argument("--weights-dir", default="core_ml/weights")
    parser.add_argument("--output", help="Save an aggregate report without raw visitor profiles")
    args = parser.parse_args()
    rendered = json.dumps(main(args.capture_dir, args.weights_dir, args.human_capture_dir),
                          indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
