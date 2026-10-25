"""Read explicitly attested dataset runs without leaking labels into features."""

import json
from pathlib import Path

from core_ml.dataset.export_captures import verify_export
from core_ml.features.mouse_features import sanitize_mouse_records, records_to_chunks


def load_manual_training_runs(directory, *, allow_weak_labels=False):
    """Return grouped training candidates, not an automatic train/test split.

    Provider/commercial assertions stay weak by default. Every run retains its
    grouping key so callers can split BEFORE extracting overlapping windows.
    """
    directory = Path(directory)
    manifest = verify_export(directory)
    if not manifest.get("manual_labels_included"):
        raise ValueError("Export has no manual attestations")
    eligible = {}
    with (directory / "manual-labels.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            annotation = item.get("annotation") or {}
            if annotation.get("label") not in {"BOT", "HUMAN"} or annotation.get("confirmed") is not True:
                continue
            source = annotation.get("source")
            if source in {"provider_claim", "commercial_tool"} and not allow_weak_labels:
                continue
            if source not in {"manual_review", "controlled_bot", "known_human", "provider_claim", "commercial_tool"}:
                raise ValueError("Unrecognized label source")
            if ((source == "controlled_bot" and annotation["label"] != "BOT")
                    or (source == "known_human" and annotation["label"] != "HUMAN")):
                raise ValueError("Label conflicts with source")
            if not all(isinstance(annotation.get(key), str) and annotation[key].strip()
                       for key in ("group_id", "reviewer", "notes")):
                raise ValueError("Attestation is missing provenance/grouping")
            eligible[item["run_id"]] = {
                "run_id": item["run_id"], "label": int(annotation["label"] == "BOT"),
                "group_id": annotation["group_id"], "source": source,
                "label_revision": item["revision"], "payloads": [],
            }
    with (directory / "snapshots.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["run_id"] in eligible:
                # Only the original collector fields enter a candidate sample.
                eligible[row["run_id"]]["payloads"].append(json.loads(row["payload_json"]))
    if not eligible:
        raise ValueError("No confirmed eligible BOT/HUMAN runs; model predictions are not labels")
    return list(eligible.values())


def manual_training_samples(directory, train_groups):
    """Select declared train groups only; never concatenate snapshot trajectories."""
    runs = load_manual_training_runs(directory)
    train_groups = set(train_groups)
    if not train_groups or not train_groups <= {run["group_id"] for run in runs}:
        raise ValueError("Declare existing manual train groups explicitly; other groups stay unused")
    samples = []
    for run in runs:
        if run["group_id"] not in train_groups:
            continue
        windows = {}
        for payload in run["payloads"]:
            raw = (payload.get("mouse") or {}).get("records") or []
            records = sanitize_mouse_records(raw, max_records=100)
            if len(records) != len(raw):
                raise ValueError("Manual training snapshots must use valid collector windows")
            desktop = [point for point in records if point.get("source") != "touch"]
            if sum(point["type"] == "move" for point in desktop) < 25 or not records_to_chunks(desktop):
                continue
            windows[json.dumps(desktop, sort_keys=True, separators=(",", ":"))] = desktop
        if windows:
            samples.append({**run, "windows": list(windows.values())})
    if not samples:
        raise ValueError("Selected manual groups have no usable desktop mouse windows; labels alone cannot train mouse models")
    return samples
