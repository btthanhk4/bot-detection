"""Export immutable research snapshots and an UNKNOWN-label template from MongoDB."""

import argparse
import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient


EXPORT_SCHEMA = "datacat-research-export-v1"
LABEL_FIELDS = (
    "run_id", "study_id", "site_id", "label",
    "label_source", "participant_id", "scenario_family", "config_block_id", "split",
    "task_id", "motion_generator_id", "template_id", "seed", "runner_hash", "driver",
    "label_confirmed_by", "label_timestamp",
    "first_received_at", "last_received_at", "snapshots",
)


def utc_milliseconds(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone, for example 2026-10-19T00:00:00Z")
    return int(parsed.timestamp() * 1000)


def _reject_constant(value):
    raise ValueError(f"Invalid non-finite JSON value: {value}")


def _read_json(value):
    return json.loads(value, parse_constant=_reject_constant)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_row(doc, *, include_client_ip=False):
    """Fail on inconsistent raw data; missing analysis remains missing."""
    payload_json = doc["payload_json"]
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if digest != doc["payload_sha256"]:
        raise ValueError("Capture raw payload checksum mismatch")
    payload = _read_json(payload_json)
    if not isinstance(payload, dict) or payload.get("sessionId") != doc["sessionId"]:
        raise ValueError("Capture session does not match its payload")
    if payload.get("visitorId") != doc["visitorId"]:
        raise ValueError("Capture visitor does not match its payload")
    meta = payload.get("collector") or {}
    if not isinstance(meta, dict) or any(meta.get(key) != doc.get(field) for key, field in (
        ("studyId", "study_id"), ("siteId", "site_id"), ("pageInstanceId", "page_instance_id"),
    )):
        raise ValueError("Capture study/site/page does not match its raw payload")
    if doc.get("identity_kind") == "payload_sha256" and doc["event_id"] != digest:
        raise ValueError("Capture identity checksum mismatch")
    analysis = _read_json(doc["analysis_json"]) if doc.get("analysis_json") is not None else None
    if analysis is not None and not isinstance(analysis, dict):
        raise ValueError("Capture analysis must be an object or absent")
    row = {"schema": EXPORT_SCHEMA, **{key: doc.get(key) for key in (
        "event_id", "identity_kind", "payload_sha256", "payload_json", "sessionId", "visitorId",
        "study_id", "site_id", "page_instance_id", "received_at", "expires_at_ms",
        "server_user_agent", "capture_bundle_id", "capture_policy_version",
    )}, "analysis": analysis}
    if include_client_ip:
        row["client_ip"] = doc.get("client_ip")
    # Also reject infinities parsed from JSON exponents such as 1e999.
    json.dumps(payload, allow_nan=False)
    json.dumps(row, allow_nan=False)
    return row


def export_captures(collection, output_dir, *, study_id, site_id, since_ms, until_ms,
                    include_client_ip=False, labels_collection=None):
    if (not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value)
                for value in (study_id, site_id)) or since_ms >= until_ms):
        raise ValueError("Require study/site IDs and a nonempty half-open time range")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    query = {"study_id": study_id, "site_id": site_id,
             "received_at": {"$gte": since_ms, "$lt": until_ms}}
    cursor = collection.find(query, {"_id": 0}).sort([("received_at", 1), ("event_id", 1)]).batch_size(200)
    partial = output_dir / "snapshots.jsonl.partial"
    seen, groups, annotations = set(), {}, {}
    count = missing_analysis = 0
    try:
        with partial.open("x", encoding="utf-8", newline="\n") as stream:
            for doc in cursor:
                row = capture_row(doc, include_client_ip=include_client_ip)
                if (row["study_id"] != study_id or row["site_id"] != site_id
                        or not isinstance(row["received_at"], int) or isinstance(row["received_at"], bool)
                        or not since_ms <= row["received_at"] < until_ms):
                    raise ValueError("Database cursor returned a capture outside the requested scope")
                if not isinstance(row["event_id"], str) or not row["event_id"] or row["event_id"] in seen:
                    raise ValueError("Missing or duplicate capture ID in export")
                seen.add(row["event_id"])
                key = (row["sessionId"], row["page_instance_id"])
                run_id = hashlib.sha256(json.dumps([study_id, site_id, *key]).encode()).hexdigest()
                row["run_id"] = run_id
                if labels_collection is not None and row["sessionId"] not in annotations:
                    annotations[row["sessionId"]] = labels_collection.find_one({"_id": row["sessionId"]}) or {}
                run = groups.setdefault(key, {
                    "run_id": run_id,
                    "study_id": study_id, "site_id": site_id,
                    "label": "UNKNOWN", "label_source": "unassigned",
                    "first_received_at": row["received_at"], "last_received_at": row["received_at"],
                    "snapshots": 0,
                })
                run["first_received_at"] = min(run["first_received_at"], row["received_at"])
                run["last_received_at"] = max(run["last_received_at"], row["received_at"])
                run["snapshots"] += 1
                run["_session_id"] = row["sessionId"]
                count += 1
                missing_analysis += row["analysis"] is None
                stream.write(json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
        if count == 0:
            raise ValueError("No captures matched; verify capture mode, study/site IDs and time range")
        snapshots = output_dir / "snapshots.jsonl"
        partial.rename(snapshots)
        labels = output_dir / "labels-template.csv"
        with labels.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=LABEL_FIELDS)
            writer.writeheader()
            writer.writerows({key: value for key, value in run.items() if not key.startswith("_")}
                             for run in groups.values())
        files = [snapshots, labels]
        if labels_collection is not None:
            manual = output_dir / "manual-labels.jsonl"
            with manual.open("x", encoding="utf-8", newline="\n") as stream:
                for run in groups.values():
                    metadata = annotations[run["_session_id"]]
                    annotation = metadata.get("manual_label") or {}
                    item = {"run_id": run["run_id"], "sessionId": run["_session_id"],
                            "traffic_number": metadata.get("traffic_number"),
                            "revision": metadata.get("revision", 0),
                            "annotation": annotation or None}
                    stream.write(json.dumps(item, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
            files.append(manual)
        manifest = {
            "schema": EXPORT_SCHEMA, "exported_at": datetime.now(timezone.utc).isoformat(),
            "scope": query, "consistency": "cursor_observation_not_transaction_snapshot",
            "snapshots": count, "runs": len(groups), "without_analysis": missing_analysis,
            "labels": "UNKNOWN_until_independently_attested", "includes_client_ip": include_client_ip,
            "manual_labels_included": labels_collection is not None,
            "files": {p.name: {"sha256": _hash(p), "bytes": p.stat().st_size} for p in files},
        }
        with (output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        return manifest
    finally:
        cursor.close()


def verify_export(directory):
    directory = Path(directory)
    manifest = _read_json((directory / "manifest.json").read_text(encoding="utf-8"))
    expected_files = {"snapshots.jsonl", "labels-template.csv"}
    if manifest.get("manual_labels_included"):
        expected_files.add("manual-labels.jsonl")
    if manifest.get("schema") != EXPORT_SCHEMA or set(manifest.get("files", {})) != expected_files:
        raise ValueError("Unsupported export manifest")
    for name, expected in manifest["files"].items():
        path = directory / name
        if path.stat().st_size != expected["bytes"] or _hash(path) != expected["sha256"]:
            raise ValueError(f"Export file checksum mismatch: {name}")
    seen, runs = set(), {}
    with (directory / "snapshots.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = _read_json(line)
            if row.get("schema") != EXPORT_SCHEMA or row["event_id"] in seen:
                raise ValueError("Invalid or duplicate exported snapshot")
            seen.add(row["event_id"])
            if row["run_id"] in runs and runs[row["run_id"]] != row["sessionId"]:
                raise ValueError("Run contains conflicting sessions")
            runs[row["run_id"]] = row["sessionId"]
            if hashlib.sha256(row["payload_json"].encode()).hexdigest() != row["payload_sha256"]:
                raise ValueError("Export raw payload checksum mismatch")
    if len(seen) != manifest["snapshots"]:
        raise ValueError("Export snapshot count mismatch")
    with (directory / "labels-template.csv").open(encoding="utf-8", newline="") as stream:
        labels = list(csv.DictReader(stream))
    if (len(labels) != manifest["runs"] or sum(int(row["snapshots"]) for row in labels) != len(seen)
            or any(row["label"] != "UNKNOWN" for row in labels)):
        raise ValueError("Export label-template/count mismatch")
    if manifest.get("manual_labels_included"):
        observed = set()
        with (directory / "manual-labels.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                item = _read_json(line)
                if item["run_id"] in observed or runs.get(item["run_id"]) != item["sessionId"]:
                    raise ValueError("Manual label does not match an exported run")
                observed.add(item["run_id"])
                annotation = item.get("annotation")
                if annotation is not None and (
                    annotation.get("label") not in {"BOT", "HUMAN", "UNKNOWN"}
                    or type(annotation.get("confirmed")) is not bool
                    or annotation.get("revision") != item.get("revision")
                ):
                    raise ValueError("Invalid manual label")
        if observed != set(runs):
            raise ValueError("Missing manual label records")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="Verify an existing export without connecting to MongoDB")
    parser.add_argument("--study-id")
    parser.add_argument("--site-id")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-client-ip", action="store_true")
    parser.add_argument("--include-manual-labels", action="store_true")
    parser.add_argument("--labeled-only", action="store_true", help="Read retained dataset snapshots instead of TTL captures")
    args = parser.parse_args()
    if args.verify:
        manifest = verify_export(args.verify)
    else:
        if not all((args.study_id, args.site_id, args.since, args.until, args.output)):
            parser.error("Export requires --study-id, --site-id, --since, --until and --output")
        uri = os.environ.get("MONGO_URI")
        if not uri:
            parser.error("Set MONGO_URI in the operator environment; credentials must not appear in CLI arguments")
        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            db = client[os.environ.get("MONGO_DB", "bot_detection")]
            collection = db["labeled_captures" if args.labeled_only else "telemetry_captures"]
            manifest = export_captures(
                collection, args.output, study_id=args.study_id, site_id=args.site_id,
                since_ms=utc_milliseconds(args.since), until_ms=utc_milliseconds(args.until),
                include_client_ip=args.include_client_ip,
                labels_collection=db["research_sessions"] if args.include_manual_labels or args.labeled_only else None,
            )
    print(json.dumps({"snapshots": manifest["snapshots"], "runs": manifest["runs"],
                      "without_analysis": manifest["without_analysis"], "verified": bool(args.verify)}))


if __name__ == "__main__":
    main()
