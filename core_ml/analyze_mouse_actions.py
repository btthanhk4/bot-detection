"""Offline, per-action mouse measurements from a retained collector window."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import fmean, pstdev

from core_ml.features.interaction_features import (
    LOCAL_MOVE_MAX_GAP_MS, MAX_SCROLL_EVENTS, sanitize_scroll_events,
)
from core_ml.features.mouse_features import MAX_MOUSE_RECORDS, sanitize_mouse_records


ANALYSIS_VERSION = "mouse_actions_v1"
MAX_INPUT_EVENTS = 10_000
EVENT_TYPES = {"move", "down", "up", "click"}


def _finite(value):
    return value if value is not None and math.isfinite(value) else None


def _divide(value, denominator):
    return _finite(value / denominator) if denominator > 0 else None


def _clean_records(raw):
    """Retain input indices and discontinuities that a numeric sanitizer drops."""
    raw = raw if isinstance(raw, list) else []
    valid, rejected, continuity = [], 0, 0
    offset = max(0, len(raw) - MAX_INPUT_EVENTS)
    for index, record in enumerate(raw[offset:], offset):
        allowed = (
            isinstance(record, dict)
            and isinstance(record.get("type", "move"), str)
            and record.get("type", "move") in EVENT_TYPES
            and record.get("source") in (None, "mouse", "touch")
            and not any(isinstance(record.get(key), bool) for key in ("x", "y", "time", "t"))
        )
        cleaned = sanitize_mouse_records([record], max_records=1) if allowed else []
        if not cleaned:
            rejected += 1
            continuity += 1
            continue
        valid.append({**cleaned[0], "input_index": index, "continuity": continuity})
    ordered = sorted(valid, key=lambda row: row["time"])
    retained = ordered[-MAX_MOUSE_RECORDS:]
    return retained, {
        "input_events": len(raw), "inspected_events": len(raw) - offset,
        "uninspected_events": offset, "invalid_events": rejected,
        "valid_events_outside_window": len(ordered) - len(retained),
        "input_reordered": [row["input_index"] for row in ordered] != [row["input_index"] for row in valid],
    }


def _kinematics(previous, current, previous_velocity, previous_acceleration):
    dt_ms = current["time"] - previous["time"]
    dt = dt_ms / 1000
    dx, dy = current["x"] - previous["x"], current["y"] - previous["y"]
    velocity = (_divide(dx, dt), _divide(dy, dt))
    if None in velocity:
        return None, None, None
    speed = _finite(math.hypot(*velocity))
    if speed is None:
        return None, None, None
    values = {"dx": dx, "dy": dy, "distance": math.hypot(dx, dy),
              "velocity_x": velocity[0], "velocity_y": velocity[1], "speed": speed}
    acceleration = None
    if previous_velocity is not None:
        ax = _divide(velocity[0] - previous_velocity[0], dt)
        ay = _divide(velocity[1] - previous_velocity[1], dt)
        if ax is not None and ay is not None and _finite(math.hypot(ax, ay)) is not None:
            acceleration = (ax, ay)
            values.update(acceleration_x=ax, acceleration_y=ay, acceleration=math.hypot(ax, ay))
            values["tangential_acceleration"] = _divide(speed - math.hypot(*previous_velocity), dt)
        if math.hypot(*previous_velocity) > 0 and speed > 0:
            # Normalize first so products cannot overflow at very small intervals.
            a = tuple(value / math.hypot(*previous_velocity) for value in previous_velocity)
            b = tuple(value / speed for value in velocity)
            values["turn_radians"] = math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
            values["curvature"] = _divide(abs(values["turn_radians"]), values["distance"])
    if acceleration is not None and previous_acceleration is not None:
        jx = _divide(acceleration[0] - previous_acceleration[0], dt)
        jy = _divide(acceleration[1] - previous_acceleration[1], dt)
        if jx is not None and jy is not None:
            values["jerk"] = _finite(math.hypot(jx, jy))
    return values, velocity, acceleration


def _movement(events):
    timeline, strokes = [], []
    previous = previous_velocity = previous_acceleration = None
    previous_event = None
    for index, event in enumerate(events):
        row = {key: event[key] for key in ("time", "x", "y", "type", "input_index")}
        row.update(id=index, source=event.get("source") or "unspecified", stroke_id=None,
                   previous_move_id=None, move_interval_ms=None, flags=[])
        row.update(dict.fromkeys(("dx", "dy", "distance", "velocity_x", "velocity_y", "speed",
                                  "acceleration_x", "acceleration_y", "acceleration",
                                  "tangential_acceleration", "jerk", "turn_radians", "curvature")))
        interrupted = previous_event is not None and (
            event["continuity"] != previous_event["continuity"]
            or event["input_index"] < previous_event["input_index"]
        )
        if interrupted:
            previous = previous_velocity = previous_acceleration = None
            row["flags"].append("input_discontinuity")
        if row["source"] == "touch" or row["type"] != "move":
            previous = previous_velocity = previous_acceleration = None
            if row["source"] == "touch":
                row["flags"].append("touch_not_mouse")
        else:
            if previous is not None and previous["source"] != row["source"]:
                previous = previous_velocity = previous_acceleration = None
                row["flags"].append("source_boundary")
            if previous is not None:
                dt_ms = row["time"] - previous["time"]
                row["move_interval_ms"] = dt_ms
                if not 0 < dt_ms <= LOCAL_MOVE_MAX_GAP_MS:
                    row["flags"].append("duplicate_timestamp" if dt_ms == 0 else "gap_boundary")
                    previous = previous_velocity = previous_acceleration = None
            if previous is not None:
                values, velocity, acceleration = _kinematics(previous, row, previous_velocity, previous_acceleration)
                if values is None:
                    previous = previous_velocity = previous_acceleration = None
                    row["flags"].append("unresolvable_derivative")
                else:
                    row.update(values)
                    row.update(previous_move_id=previous["id"], stroke_id=previous["stroke_id"])
                    previous_velocity, previous_acceleration = velocity, acceleration
            if previous is None:
                row["stroke_id"] = len(strokes)
                strokes.append([])
            strokes[row["stroke_id"]].append(row)
            previous = row
        timeline.append(row)
        previous_event = event
    summaries = []
    for stroke in strokes:
        speeds = [row["speed"] for row in stroke if row["speed"] is not None]
        distance = sum(row["distance"] or 0 for row in stroke)
        displacement = math.hypot(stroke[-1]["x"] - stroke[0]["x"], stroke[-1]["y"] - stroke[0]["y"])
        scaled = [value / max(speeds) for value in speeds] if speeds and max(speeds) > 0 else []
        summaries.append({
            "id": stroke[0]["stroke_id"], "event_ids": [row["id"] for row in stroke],
            "duration_ms": stroke[-1]["time"] - stroke[0]["time"],
            "path_length": distance, "displacement": displacement,
            "straightness": min(1.0, displacement / distance) if distance > 0 else None,
            "mean_speed": fmean(scaled) * max(speeds) if scaled else (0.0 if speeds else None),
            "speed_cv": pstdev(scaled) / fmean(scaled) if len(scaled) >= 2 else None,
            "absolute_turn_radians": sum(abs(row["turn_radians"] or 0) for row in stroke),
        })
    return timeline, summaries


def _presses_and_clicks(events, timeline):
    presses, clicks = [], []
    pending = last_move = last_click = previous_event = None
    blocked = False
    for event, row in zip(events, timeline):
        interrupted = previous_event is not None and (
            event["continuity"] != previous_event["continuity"]
            or event.get("source") != previous_event.get("source")
            or event["input_index"] < previous_event["input_index"]
        )
        if interrupted:
            if pending is not None:
                pending["status"] = "interrupted"
            pending = last_move = last_click = None
            blocked = False
        previous_event = event
        if event.get("source") == "touch":
            continue
        if row["type"] == "move":
            last_move = row
            if pending is not None:
                pending["move_event_ids"].append(row["id"])
        elif row["type"] == "down":
            if pending is not None:
                pending["status"] = "ambiguous_overlap"
                blocked = True
            pending = {"down_id": row["id"], "up_id": None, "duration_ms": None,
                       "status": "ambiguous_overlap" if blocked else "missing_up",
                       "move_event_ids": [], "sampled_path_length": None,
                       "displacement": None}
            presses.append(pending)
        elif row["type"] == "up":
            if pending is not None and not blocked:
                down = timeline[pending["down_id"]]
                path = [down, *[timeline[i] for i in pending["move_event_ids"]], row]
                pending.update(up_id=row["id"], status="paired",
                               duration_ms=row["time"] - down["time"],
                               displacement=math.hypot(row["x"] - down["x"], row["y"] - down["y"]),
                               sampled_path_length=sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                                                       for a, b in zip(path, path[1:])))
            else:
                presses.append({"down_id": None, "up_id": row["id"], "duration_ms": None,
                                "status": "ambiguous_overlap" if blocked else "missing_down",
                                "move_event_ids": [], "sampled_path_length": None, "displacement": None})
            pending = None
        elif row["type"] == "click":
            clicks.append({
                "event_id": row["id"],
                "since_last_move_ms": row["time"] - last_move["time"] if last_move else None,
                "since_last_click_ms": row["time"] - last_click["time"] if last_click else None,
            })
            last_click = row
    return presses, clicks


def _wheel(mouse):
    raw = mouse.get("scrollEvents")
    raw = raw if isinstance(raw, list) else []
    inspected = raw[-MAX_INPUT_EVENTS:]
    cleaned = sanitize_scroll_events(inspected, max_events=0)
    rows, previous = [], None
    for event in cleaned[-MAX_SCROLL_EVENTS:]:
        dt = event["time"] - previous["time"] if previous else None
        rows.append({**event, "interval_ms": dt,
                     "vertical_reversal": (event["deltaY"] * previous["deltaY"] < 0)
                     if previous and dt is not None and 0 < dt <= LOCAL_MOVE_MAX_GAP_MS else None})
        previous = event
    return rows, {
        "input_events": len(raw), "uninspected_events": len(raw) - len(inspected),
        "invalid_events": len(inspected) - len(cleaned),
        "valid_events_outside_window": max(0, len(cleaned) - MAX_SCROLL_EVENTS),
        "delta_units": "unknown_deltaMode_not_collected",
    }


def analyze_mouse_actions(mouse):
    """Recompute measurements from coordinates/time, never client speed or labels."""
    mouse = mouse if isinstance(mouse, dict) else {}
    raw = mouse.get("records") or mouse.get("trajectory")
    events, quality = _clean_records(raw)
    timeline, strokes = _movement(events)
    presses, clicks = _presses_and_clicks(events, timeline)
    wheel, wheel_quality = _wheel(mouse)
    normalized = bool(events) and all(0 <= row[axis] <= 1 for row in events for axis in ("x", "y"))
    return {
        "analysis_version": ANALYSIS_VERSION, "mode": "measurement_only",
        "scope": "retained_collector_window", "used_for_classification": False,
        "units": {"time": "ms", "distance": "input_coordinate_units",
                  "speed": "input_coordinate_units/s", "acceleration": "input_coordinate_units/s^2",
                  "jerk": "input_coordinate_units/s^3", "turn": "radians",
                  "coordinate_space": "within_unit_square" if normalized else "unknown",
                  "pixel_geometry_available": False},
        "segmentation": {"max_move_gap_ms": LOCAL_MOVE_MAX_GAP_MS,
                         "derivatives": "backward_differences_at_endpoints"},
        "coverage": {**quality, "retained_events": len(events),
                     "first_time_ms": events[0]["time"] if events else None,
                     "last_time_ms": events[-1]["time"] if events else None,
                     "complete_session": False, "wheel": wheel_quality},
        "counts": {"event_types": dict(Counter(row["type"] for row in timeline)),
                   "touch_events": sum(row["source"] == "touch" for row in timeline),
                   "strokes": len(strokes), "paired_presses": sum(p["status"] == "paired" for p in presses),
                   "clicks": len(clicks), "wheel_events": len(wheel),
                   "speeds_available": sum(row["speed"] is not None for row in timeline),
                   "accelerations_available": sum(row["acceleration"] is not None for row in timeline),
                   "jerks_available": sum(row["jerk"] is not None for row in timeline)},
        "events": timeline, "strokes": strokes, "presses": presses, "clicks": clicks, "wheel": wheel,
    }


def analyze_document(document, snapshot_index=None):
    """Choose one real send; overlapping windows must never be concatenated."""
    if not isinstance(document, dict):
        raise ValueError("Expected a mouse object, telemetry payload or capture document")
    if "snapshots" in document:
        snapshots = document["snapshots"]
        if not isinstance(snapshots, list) or not snapshots or not all(isinstance(p, dict) for p in snapshots):
            raise ValueError("Capture snapshots must be a nonempty list of objects")
        available = [i for i, payload in enumerate(snapshots) if payload.get("action") != "test-probe"]
        if not available:
            raise ValueError("No sent snapshot: only test probes were supplied")
        index = available[-1] if snapshot_index is None else snapshot_index
        if type(index) is not int or index not in available:
            raise ValueError("snapshot-index must select a sent snapshot, not a test probe")
        payload = snapshots[index]
        selection = {"kind": "capture", "snapshot_index": index, "sent_snapshots": len(available)}
    else:
        if snapshot_index is not None:
            raise ValueError("snapshot-index requires a capture document")
        payload, selection = document, {"kind": "telemetry" if "mouse" in document else "mouse"}
    report = analyze_mouse_actions(payload.get("mouse") if "mouse" in payload else payload)
    report["selection"] = selection
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--snapshot-index", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must not overwrite the input capture")
    report = analyze_document(json.loads(args.input.read_text(encoding="utf-8-sig")), args.snapshot_index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "counts": report["counts"], "coverage": report["coverage"]}))


if __name__ == "__main__":
    main()
