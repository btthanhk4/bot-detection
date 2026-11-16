"""Policy 40: the mouse models judge the whole session, not its last two seconds.

Until policy 39 every snapshot was judged alone on the collector's export: the last 100 records,
which at a desktop mouse's ~60 events per second is the last 1.5-2.5 s of movement, and the newest
snapshot replaced the verdict. A person's verdict then depended on how fast their last stroke happened
to be: three sessions of one person using the shop alike (16 Nov 2026) scored 0.04, 0.32 and 0.46 on
the BiLSTM, and the last was a final SUSPECT (model disagreement) on a single quick stroke.

The models themselves are unchanged and still see what they were trained on: 24-move LSTM chunks
(stride 12) and 20 statistics over a collector-equivalent window of 100 records
(``core_ml.collector_windows.export_window``). What changes is how many of them a session gets:

- Collector 1.17 exports every move since its last acknowledged snapshot plus 100 moves of context,
  and ``mouse.moveBase``, the index of the first exported move within its coordinate frame. Chunks start
  at frame-global multiples of 12 and windows end at every 50th move, so a resent or overlapping
  snapshot adds nothing twice and arrival order does not matter.
- Older collectors (last 100 records only) contribute their own window and its chunks, keyed by time.
- The API keeps each session's chunk and window scores (``session_mouse``, bounded) and passes them
  back in with the next snapshot. The session's LSTM mean and upper quartile are taken over all its
  chunks and the tabular score is the mean over its windows; the thresholds of policy 39 apply unchanged.

The decision is a hybrid, measured on the held-out benchmark sessions (docs/POLICY40_SESSION_MOUSE.md):
averaging alone let a bot whose behaviour shows in a few windows sink from BOT to SUSPECT. So once a
session holds at least 12 chunks and 2 windows it decides between HUMAN and SUSPECT (and may reach BOT
itself), while a snapshot whose own window reaches BOT keeps its BOT; two such snapshots still lock the
session (policy 24). A single snapshot of an old collector, and every offline replay of single payloads,
gives exactly the decision of policy 39.
"""

import hashlib
import math

import numpy as np

from core_ml.collector_windows import export_window
from core_ml.features.mouse_features import records_to_chunks

SESSION_MOUSE_VERSION = "session_windows_v1"
CHUNK_SIZE = 24
CHUNK_STRIDE = 12
GRID_MOVES = 50
WINDOW_RECORDS = 100
# One extended export the server reads (newest kept); the collector sends at most 600 moves.
MAX_EXPORT_RECORDS = 1200
MAX_SESSION_CHUNKS = 1500
# The session decides once it holds about twice one trained window (6 chunks, 1 window).
MIN_SESSION_CHUNKS = 12
MIN_SESSION_WINDOWS = 2
MAX_SESSION_WINDOWS = 300
MAX_KEY_LENGTH = 64
MAX_FRAME_ID = 1_000_000
MAX_MOVE_BASE = 100_000_000


def _int(value, high):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= high else None


def export_frame(payload: dict) -> tuple:
    """(move base or None, coordinate frame id, page instance hash) of an export."""
    payload = payload if isinstance(payload, dict) else {}
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    frame = mouse.get("coordinateFrame") if isinstance(mouse.get("coordinateFrame"), dict) else {}
    collector = payload.get("collector") if isinstance(payload.get("collector"), dict) else {}
    page = collector.get("pageInstanceId")
    page = hashlib.sha256(page.encode("utf-8", "replace")).hexdigest()[:12] if isinstance(page, str) and page else "nopage"
    return _int(mouse.get("moveBase"), MAX_MOVE_BASE), _int(frame.get("id"), MAX_FRAME_ID) or 0, page


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _rows(records) -> list:
    """Well-formed records only (numeric time and position), so ordering them cannot fail."""
    if not isinstance(records, list):
        return []
    return [record for record in records
            if isinstance(record, dict) and _number(record.get("time")) and record["time"] >= 0
            and _number(record.get("x")) and _number(record.get("y"))]


def _is_mouse_move(record) -> bool:
    return record.get("type") == "move" and record.get("source") != "touch"


def is_extended_export(payload: dict) -> bool:
    """A collector 1.17 export (it declares ``mouse.moveBase``). Anything else, a whole benchmark
    trajectory included, keeps policy 39's reading: its newest 100 valid records."""
    return export_frame(payload)[0] is not None


def collector_window(records) -> list:
    """What collector 1.16 would have sent: the 20 newest other events and the newest mouse moves,
    100 records in all. Every per-snapshot rule and the snapshot's own model scores read this."""
    rows = _rows(records)[-MAX_EXPORT_RECORDS:]
    other = [record for record in rows if not _is_mouse_move(record)][-20:]
    moves = [record for record in rows if _is_mouse_move(record)][-(WINDOW_RECORDS - len(other)):]
    return sorted(moves + other, key=lambda record: record["time"])


def legacy_keys(payload: dict, moves: list, chunk_count: int) -> tuple:
    """Keys of an older collector's own chunks and window (its export is one window), by time.

    ``moves`` are the sanitized mouse moves the snapshot's chunks were built from (stride 12)."""
    _, frame, page = export_frame(payload)
    chunk_keys = [f"{page}:{frame}:t{_time_key(moves, index * CHUNK_STRIDE)}" for index in range(chunk_count)]
    return chunk_keys, f"{page}:{frame}:t{_time_key(moves, len(moves) - 1)}"


def session_pieces(payload: dict, records) -> dict:
    """LSTM chunks and tabular windows a collector 1.17 export adds to its session, under stable keys.

    ``records`` are the export's raw records. Windows follow the collector (touch records count as
    other events); their mouse records are what the tabular model reads. Returns
    {"chunks": [(key, rows)], "windows": [(key, mouse records)]}, empty for older collectors.
    """
    base, frame, page = export_frame(payload)
    rows = _rows(records)[-MAX_EXPORT_RECORDS:]
    positions = [index for index, record in enumerate(rows) if _is_mouse_move(record)]
    chunks, windows = [], []
    if base is None or not positions:
        return {"chunks": chunks, "windows": windows}
    moves = [rows[index] for index in positions]
    # Transition features over the whole export first: a transition's acceleration needs the one
    # before it, so a chunk cut from the middle of an export equals the same chunk of any other.
    transitions = [chunk[0] for chunk in records_to_chunks(moves, 1, 1, max_records=MAX_EXPORT_RECORDS)]
    for start in range((-base) % CHUNK_STRIDE, len(transitions) - CHUNK_SIZE + 1, CHUNK_STRIDE):
        chunks.append((f"{page}:{frame}:m{base + start}", transitions[start:start + CHUNK_SIZE]))
    last = len(positions) - 1
    for local, raw_index in enumerate(positions):
        global_index = base + local
        on_grid = (global_index + 1) % GRID_MOVES == 0 or local == last
        has_context = local >= WINDOW_RECORDS - 1 or (base == 0 and local >= CHUNK_SIZE)
        if on_grid and has_context:
            window = [record for record in export_window(rows, raw_index) if record.get("source") != "touch"]
            windows.append((f"{page}:{frame}:w{global_index}", window))
    return {"chunks": chunks, "windows": windows}


def _time_key(moves, index) -> str:
    if not moves:
        return "0"
    value = moves[max(0, min(index, len(moves) - 1))].get("time")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "0"
    return f"{number:.0f}" if math.isfinite(number) else "0"


def _scores(raw, limit) -> dict:
    """A bounded {key: probability} map read back from storage."""
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key, value in raw.items():
        if len(clean) >= limit:
            break
        if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if math.isfinite(value) and 0.0 <= value <= 1.0:
            clean[key] = value
    return clean


def prior_evidence(payload: dict) -> dict:
    """The session's stored scores the API attached as ``_session_mouse`` (never from the client)."""
    raw = payload.get("_session_mouse") if isinstance(payload, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {"chunks": _scores(raw.get("chunks"), MAX_SESSION_CHUNKS),
            "windows": _scores(raw.get("windows"), MAX_SESSION_WINDOWS)}


def aggregate(prior: dict, chunk_scores: dict, window_scores: dict) -> dict:
    """Session LSTM mean and upper quartile over every chunk, tabular mean over every window.

    The payload's own pieces always count; only those new to the session (and within the bounds)
    are returned for storage.
    """
    chunks = dict(prior.get("chunks") or {})
    windows = dict(prior.get("windows") or {})
    new_chunks = {key: value for key, value in chunk_scores.items() if key not in chunks}
    new_windows = {key: value for key, value in window_scores.items() if key not in windows}
    chunks.update(chunk_scores)
    windows.update(window_scores)
    room_chunks = max(0, MAX_SESSION_CHUNKS - len(prior.get("chunks") or {}))
    room_windows = max(0, MAX_SESSION_WINDOWS - len(prior.get("windows") or {}))
    chunk_values = np.array(list(chunks.values()), dtype=float)
    window_values = np.array(list(windows.values()), dtype=float)
    return {
        "chunks": len(chunk_values),
        "windows": len(window_values),
        "lstm_mean": float(chunk_values.mean()) if len(chunk_values) else None,
        "lstm_p75": float(np.quantile(chunk_values, 0.75)) if len(chunk_values) else None,
        "tabular": float(window_values.mean()) if len(window_values) else None,
        "new": {"chunks": dict(list(new_chunks.items())[:room_chunks]),
                "windows": dict(list(new_windows.items())[:room_windows])},
    }
