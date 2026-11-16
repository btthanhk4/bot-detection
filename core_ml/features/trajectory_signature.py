"""Policy 41: a mouse trajectory replayed in another session.

A behaviour model cannot tell a recording of a person from the person: replaying a real trajectory
passes the BiLSTM and the tabular model by construction (bot-lab red team, 16 Nov 2026). But nobody
moves a mouse along the same complex path twice. Each trajectory is resampled at equal arc length
(so speed, timing and sampling rate drop out), its direction sequence quantized into eight sectors
(twice, the second grid turned by half a sector, so a direction near a boundary still matches in one
of them), and every run of ``SIGNATURE_SEGMENTS`` segments that turns enough to be specific is hashed.
Position drops out with the directions. Paths start where the hand started (after a jump, a pause or
the pointer standing still), so a replay cut into snapshots at other points still lines up.

Measured on the 109 human sessions of the benchmark, each cut into collector 1.17 exports: no session
shared a single sampled signature with any one other session, while every replay of a session (cut at
other points, at the original speed or 1.5x faster) shared 3 or more with it (median 12-14); a
resampled replay matched in 40% of cases, one with 0.5 px of noise in 40%, with 1 px in 8%. The API
counts, per session, the most signatures it shares with one other page (``api_service.trajectory_store``).
"""

import hashlib
import math

SIGNATURE_VERSION = "arc_directions_v1"
REPLAYED_TRAJECTORY_RULE = "replayed_trajectory_v1"
REPLAY_SUSPECT_OVERLAP = 4   # signatures shared with one other page: withholds HUMAN
REPLAY_BOT_OVERLAP = 8       # convicts
ARC_STEP = 0.01            # resampling step, in normalised viewport units
SIGNATURE_SEGMENTS = 24    # segments per signature (0.24 of the viewport of travel)
MIN_DISTINCT_SECTORS = 4   # a straight or gently curved run says nothing about who drew it
MIN_TURNS = 5
BREAK_JUMP = 0.15          # a jump this long (pointer left and re-entered) ends a path
BREAK_PAUSE_MS = 150       # so does a pause: paths start where the hand started, whatever the snapshot
SMOOTHING = 3              # moving average over recorded points before directions are read
STILL_DISTANCE = 0.002     # a pointer that stays within this ...
STILL_MS = 100             # ... for this long has stopped: a path ends there too
MAX_SIGNATURES = 4000


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _paths(moves):
    """Pointer paths of time-ordered (x, y[, t]) points, split where the pointer jumped or (with
    times) paused. Paths are lists of (x, y)."""
    path, prev, anchor = [], None, None
    for point in moves:
        x, y = point[0], point[1]
        timed = len(point) > 2
        stopped = False
        if timed:
            if anchor is None or math.hypot(x - anchor[0], y - anchor[1]) > STILL_DISTANCE:
                anchor = point
            elif point[2] - anchor[2] >= STILL_MS:
                stopped = True
        if prev is not None and (math.hypot(x - prev[0], y - prev[1]) > BREAK_JUMP
                                 or (timed and point[2] - prev[2] > BREAK_PAUSE_MS) or stopped):
            if len(path) > 1:
                yield path
            path = []
            if stopped:
                anchor = point
        if not stopped:
            path.append((x, y))
        prev = point
    if len(path) > 1:
        yield path


def _smooth(path, width=None):
    width = SMOOTHING if width is None else width
    if width <= 1 or len(path) < width:
        return path
    half = width // 2
    return [(sum(p[0] for p in path[max(0, i - half):i + half + 1]) / len(path[max(0, i - half):i + half + 1]),
             sum(p[1] for p in path[max(0, i - half):i + half + 1]) / len(path[max(0, i - half):i + half + 1]))
            for i in range(len(path))]


def _resample(path, step=None, with_source=False):
    """Points every ``step`` of travel along the path (time plays no part). With ``with_source``,
    each point also carries the index of the recorded point it was interpolated after."""
    step = ARC_STEP if step is None else step
    out = [(*path[0], 0) if with_source else path[0]]
    carry = 0.0
    for index, ((x0, y0), (x1, y1)) in enumerate(zip(path, path[1:])):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= 0:
            continue
        pos = step - carry
        while pos <= seg:
            point = (x0 + (x1 - x0) * pos / seg, y0 + (y1 - y0) * pos / seg)
            out.append((*point, index) if with_source else point)
            pos += step
        carry = seg - (pos - step)
    return out


def _sectors(points, offset):
    return [int(((math.atan2(y1 - y0, x1 - x0) + offset) % (2 * math.pi)) / (math.pi / 4)) % 8
            for (x0, y0), (x1, y1) in zip(points, points[1:])]


def _specific(run) -> bool:
    turns = sum(1 for a, b in zip(run, run[1:]) if a != b)
    return len(set(run)) >= MIN_DISTINCT_SECTORS and turns >= MIN_TURNS


def signatures(records) -> set:
    """Hashes of the specific direction runs of a mouse trajectory (normalised coordinates).

    ``records`` are mouse records in time order; touch records and non-moves are ignored."""
    moves = [(float(r["x"]), float(r["y"]), float(r["time"])) for r in records or []
             if isinstance(r, dict) and r.get("type") == "move" and r.get("source") != "touch"
             and _number(r.get("x")) and _number(r.get("y")) and _number(r.get("time"))]
    found = set()
    for path in _paths(moves):
        points = _resample(_smooth(path))
        if len(points) <= SIGNATURE_SEGMENTS:
            continue
        for grid, offset in (("a", 0.0), ("b", math.pi / 8)):
            sectors = _sectors(points, offset)
            for start in range(0, len(sectors) - SIGNATURE_SEGMENTS + 1):
                run = sectors[start:start + SIGNATURE_SEGMENTS]
                if _specific(run):
                    found.add(hashlib.sha1((grid + "".join(map(str, run))).encode()).hexdigest()[:16])
                    if len(found) >= MAX_SIGNATURES:
                        return found
    return found


def replay_overlap(payload: dict):
    """The API's count of signatures this session shares with one other session (None if not counted)."""
    headers = payload.get("_server_headers") if isinstance(payload, dict) else None
    value = headers.get("replay_overlap") if isinstance(headers, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000 else None
