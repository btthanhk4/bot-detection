"""Compare a frozen model with browser-run BOT captures by generator family."""

import argparse
import json

from core_ml.dataset.field_captures import evaluate_bot_captures, load_bot_captures
from core_ml.evaluate import _load_detector
from core_ml.train import PRODUCTION_DECISION_THRESHOLD


def main(capture_dir: str, weights_dir: str) -> dict:
    captures = load_bot_captures(capture_dir)
    detector, manifest = _load_detector(weights_dir, PRODUCTION_DECISION_THRESHOLD)
    report = evaluate_bot_captures(detector, captures)
    report["bundle_id"] = manifest["bundle_id"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--weights-dir", default="core_ml/weights")
    args = parser.parse_args()
    print(json.dumps(main(args.capture_dir, args.weights_dir), indent=2, sort_keys=True))
