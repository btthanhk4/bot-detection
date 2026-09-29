"""Load labeled browser captures without treating correlated snapshots as sessions."""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from core_ml.features.mouse_features import sanitize_mouse_records


@dataclass(frozen=True)
class BotCapture:
    capture_id: str
    family: str
    snapshots: tuple[dict, ...]
    observed_headers: bool = False

    @property
    def sent_snapshots(self) -> tuple[dict, ...]:
        return self.snapshots[:-1]

    @property
    def final_payload(self) -> dict:
        return self.sent_snapshots[-1]

    @property
    def probe_payload(self) -> dict:
        return self.snapshots[-1]


def load_bot_captures(directory: str) -> list[BotCapture]:
    """One file is one browser run; the runner supplies the BOT label."""
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Capture directory does not exist: {root}")
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise ValueError(f"No capture JSON files in {root}")

    captures = []
    ids = set()
    session_ids = set()
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get("schema") != "bot-mouse-capture-v1":
            raise ValueError(f"Unsupported capture schema in {path}")
        capture_id = data.get("captureId")
        family = data.get("family")
        if (data.get("label") != "BOT" or not isinstance(capture_id, str)
                or not capture_id or capture_id in ids or not isinstance(family, str)
                or not family):
            raise ValueError(f"Invalid label, family, or duplicate capture ID in {path}")
        ids.add(capture_id)
        raw_snapshots = data.get("snapshots")
        if not isinstance(raw_snapshots, list) or len(raw_snapshots) < 2:
            raise ValueError(f"Missing sent snapshots or final probe in {path}")
        if (not all(isinstance(payload, dict) for payload in raw_snapshots)
                or not all(isinstance(payload.get("sessionId"), str) and payload["sessionId"]
                           for payload in raw_snapshots)
                or len({payload["sessionId"] for payload in raw_snapshots}) != 1):
            raise ValueError(f"Capture snapshots must belong to one session in {path}")
        session_id = raw_snapshots[0]["sessionId"]
        if session_id in session_ids:
            raise ValueError(f"Duplicate session ID across captures in {path}")
        session_ids.add(session_id)
        if raw_snapshots[-1].get("action") != "test-probe":
            raise ValueError(f"Final capture snapshot must be a test-probe in {path}")
        agents = data.get("serverUserAgents")
        if agents is not None and (
            not isinstance(agents, list) or len(agents) != len(raw_snapshots)
            or any(agent is not None and not isinstance(agent, str) for agent in agents)
        ):
            raise ValueError(f"Invalid observed User-Agent list in {path}")
        snapshots = []
        for index, payload in enumerate(raw_snapshots):
            if not isinstance(payload, dict) or not isinstance(payload.get("mouse"), dict):
                raise ValueError(f"Invalid telemetry payload in {path}")
            records = payload["mouse"].get("records")
            if not isinstance(records, list) or len(records) > 100:
                raise ValueError(f"Invalid collector window in {path}")
            valid = sanitize_mouse_records(records, max_records=100)
            if len(valid) != len(records):
                raise ValueError(f"Invalid mouse records in {path}")
            cleaned = {key: value for key, value in payload.items() if key != "_server_user_agent"}
            cleaned["mouse"] = {"records": valid}
            if agents is not None and agents[index]:
                cleaned["_server_user_agent"] = agents[index][:512]
            snapshots.append(cleaned)
        captures.append(BotCapture(
            capture_id, family, tuple(snapshots),
            agents is not None and all(bool(agent) for agent in agents),
        ))
    return captures


def capture_training_windows(capture: BotCapture) -> list[list]:
    """Deduplicate collector snapshots within a run before augmentation."""
    windows = {}
    for payload in capture.sent_snapshots:
        records = payload["mouse"]["records"]
        if sum(r["type"] == "move" and r.get("source") != "touch" for r in records) < 25:
            continue
        signature = json.dumps(records, sort_keys=True, separators=(",", ":"))
        windows[signature] = records
    return list(windows.values())


def evaluate_bot_captures(detector, captures: list[BotCapture]) -> dict:
    """Report one outcome per run and per family, including interim HUMAN verdicts."""
    families = {}
    for capture in captures:
        predictions = [detector.predict(payload) for payload in capture.sent_snapshots]
        verdicts = [prediction["verdict"] for prediction in predictions]
        probe_verdict = detector.predict(capture.probe_payload)["verdict"]
        family = families.setdefault(capture.family, {
            "runs": 0, "final_bot": 0, "final_human": 0, "final_suspect": 0,
            "ever_human": 0, "ever_bot": 0, "probe_bot": 0, "probe_human": 0,
            "final_suspect_reasons": Counter(),
        })
        family["runs"] += 1
        family["final_bot"] += verdicts[-1] == "BOT"
        family["final_human"] += verdicts[-1] == "HUMAN"
        family["final_suspect"] += verdicts[-1] == "SUSPECT"
        if verdicts[-1] == "SUSPECT":
            codes = predictions[-1].get("breakdown", {}).get("suspect_reason_codes") or ["UNSPECIFIED"]
            family["final_suspect_reasons"].update(set(codes))
        family["ever_human"] += "HUMAN" in verdicts
        family["ever_bot"] += "BOT" in verdicts
        family["probe_bot"] += probe_verdict == "BOT"
        family["probe_human"] += probe_verdict == "HUMAN"
    return {
        "runs": len(captures),
        "runs_without_transport_ua": sum(not capture.observed_headers for capture in captures),
        "families": {
            name: {**counts, "final_suspect_reasons": dict(sorted(counts["final_suspect_reasons"].items()))}
            for name, counts in sorted(families.items())
        },
    }
