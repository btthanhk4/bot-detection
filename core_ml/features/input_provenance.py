"""Evidence that pointer input was synthesised rather than produced by a hand.

Commercial detectors (Castle, cside, Arkose/HUMAN press-and-hold) and
Choudhary et al. (arXiv:2607.26935) report that browser automation reveals
itself less through the *shape* of a path than through how input events are
produced. Two signals here are physical and device-independent:

* Press duration. A finger needs tens of milliseconds to press and release a
  button; Playwright/Puppeteer/Selenium default clicks dispatch mousedown and
  mouseup back to back (measured 0-0.3 ms on the live site, 2026-10-25).
* Click position. Automation clicks the exact centre of the target's
  bounding box; human clicks scatter around it.

Either signal alone has human look-alikes (touchpad tap-to-click releases
instantly; a careful user can hit a centre by chance), so the release rule
requires both, repeated. Coalesced-sample counts are reported for research only:
browsers expose them in secure contexts only, and there is no human baseline yet.

Policy 15 adds two device-level signals measured on 2026-10-26 (Playwright,
Patchright, Puppeteer against Edge/Chrome 155-156):

* Typing. ``keyboard.type`` holds each key 1-20 ms by default; with a ``delay``
  every key is held and spaced alike (keydown-interval CV 0.07). In the CMU
  keystroke benchmark (51 people, 20,400 typings of one password, the most
  rhythmic human typing there is) no typing has a median hold under 33 ms and
  none has an interval CV under 0.139. Virtual keyboards (key "Unidentified",
  coarse pointers) are excluded: they report press and release together.
* Pressure. The Pointer Events spec requires a pressed mouse to report
  pressure 0.5; Puppeteer's CDP clicks report 0. Checked on Chromium only.
"""

import math
import statistics

SYNTHETIC_CLICK_RULE = "synthetic_click_v1"
SYNTHETIC_TYPING_RULE = "synthetic_typing_v1"
SYNTHETIC_POINTER_RULE = "synthetic_pointer_v1"
INPUT_PROVENANCE_VERSION = "input_provenance_v2"

MAX_KEYSTROKES = 60
BURST_GAP_MS = 1500.0
TYPING_FAST_MIN_KEYS = 8
TYPING_FAST_MEDIAN_HOLD_MS = 20.0
TYPING_RHYTHM_MIN_KEYS = 11
TYPING_RHYTHM_MAX_CV = 0.10
ZERO_PRESSURE_MIN_PRESSES = 2

MAX_CLICK_EVENTS = 30
MIN_TARGET_PX = 16
MAX_TARGET_PX = 4000
CENTRE_TOLERANCE_PX = 1.0
INSTANT_RELEASE_MS = 5.0
RULE_MIN_CENTRED_CLICKS = 3
RULE_MIN_INSTANT_RELEASES = 2


def _number(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not low <= number <= high:
        return None
    return number


def sanitize_click_events(events):
    """Keep the most recent well-formed click geometry records."""
    if not isinstance(events, list):
        return []
    clean = []
    for event in events[-MAX_CLICK_EVENTS:]:
        if not isinstance(event, dict):
            continue
        ox = _number(event.get("ox"), -MAX_TARGET_PX, MAX_TARGET_PX)
        oy = _number(event.get("oy"), -MAX_TARGET_PX, MAX_TARGET_PX)
        width = _number(event.get("w"), 1, MAX_TARGET_PX)
        height = _number(event.get("h"), 1, MAX_TARGET_PX)
        if None in (ox, oy, width, height):
            continue
        hold = event.get("hold")
        clean.append({
            "ox": ox, "oy": oy, "w": width, "h": height,
            "hold": _number(hold, 0, 10_000) if hold is not None else None,
        })
    return clean


def _pointer_stats(raw):
    if not isinstance(raw, dict):
        return None
    moves = _number(raw.get("pointermove"), 0, 10**9)
    total = _number(raw.get("coalescedTotal"), 0, 10**10)
    maximum = _number(raw.get("coalescedMax"), 0, 10**6)
    multi = _number(raw.get("coalescedMulti"), 0, 10**9)
    if moves is None or moves == 0 or total is None:
        return None
    return {
        "pointer_moves": int(moves),
        "coalesced_mean": round(total / moves, 3),
        "coalesced_max": int(maximum or 0),
        "coalesced_multi_share": round((multi or 0) / moves, 3),
        "secure_context": raw.get("secureContext") is True,
    }


def sanitize_keystrokes(raw):
    """Keep well-formed physical-keyboard strokes (timing only) in time order."""
    if not isinstance(raw, list):
        return []
    clean = []
    for stroke in raw[-MAX_KEYSTROKES:]:
        if not isinstance(stroke, dict) or stroke.get("k") not in ("c", "o"):
            continue
        at = _number(stroke.get("t"), 0, 10**9)
        if at is None:
            continue
        hold = stroke.get("h")
        clean.append({"t": at, "h": _number(hold, 0, 5000) if hold is not None else None})
    return sorted(clean, key=lambda stroke: stroke["t"])


def _bursts(strokes):
    bursts, current = [], []
    for stroke in strokes:
        if current and stroke["t"] - current[-1]["t"] > BURST_GAP_MS:
            bursts.append(current)
            current = []
        current.append(stroke)
    if current:
        bursts.append(current)
    return bursts


def analyze_typing(keyboard) -> dict:
    keyboard = keyboard if isinstance(keyboard, dict) else {}
    strokes = sanitize_keystrokes(keyboard.get("keystrokes"))
    coarse = keyboard.get("coarsePointer") is True
    fastest_median_hold, lowest_interval_cv = None, None
    # Sliding windows: one typed field can sit next to a pause or a different field.
    # CMU benchmark, same windows: lowest 8-key median hold 30.2 ms, lowest 11-key CV 0.139.
    for burst in _bursts(strokes):
        holds = [s["h"] for s in burst if s["h"] is not None]
        for start in range(len(holds) - TYPING_FAST_MIN_KEYS + 1):
            median = statistics.median(holds[start:start + TYPING_FAST_MIN_KEYS])
            fastest_median_hold = median if fastest_median_hold is None else min(fastest_median_hold, median)
        for start in range(len(burst) - TYPING_RHYTHM_MIN_KEYS + 1):
            window = burst[start:start + TYPING_RHYTHM_MIN_KEYS]
            intervals = [b["t"] - a["t"] for a, b in zip(window, window[1:])]
            mean = sum(intervals) / len(intervals)
            if mean > 0:
                cv = statistics.pstdev(intervals) / mean
                lowest_interval_cv = cv if lowest_interval_cv is None else min(lowest_interval_cv, cv)
    codes = []
    if not coarse and fastest_median_hold is not None and fastest_median_hold < TYPING_FAST_MEDIAN_HOLD_MS:
        codes.append("TYPING_INSTANT_HOLD")
    if not coarse and lowest_interval_cv is not None and lowest_interval_cv < TYPING_RHYTHM_MAX_CV:
        codes.append("TYPING_METRONOME")
    bulk = _number(keyboard.get("bulkInserts"), 0, 10**6)
    if bulk:
        codes.append("BULK_TEXT_INSERT")  # reported only; autofill and dictation look alike
    return {
        "keystrokes": len(strokes),
        "coarse_pointer": coarse,
        "fastest_median_hold_ms": None if fastest_median_hold is None else round(fastest_median_hold, 1),
        "lowest_interval_cv": None if lowest_interval_cv is None else round(lowest_interval_cv, 3),
        "bulk_inserts": int(bulk or 0),
        "codes": codes,
    }


def analyze_input_provenance(mouse, user_agent: str = "") -> dict:
    """Return click, typing and press evidence and which synthetic-input rule fires."""
    mouse = mouse if isinstance(mouse, dict) else {}
    clicks = sanitize_click_events(mouse.get("clickEvents"))
    measured = [c for c in clicks if MIN_TARGET_PX <= c["w"] and MIN_TARGET_PX <= c["h"]]
    centred = [
        c for c in measured
        if abs(c["ox"]) <= CENTRE_TOLERANCE_PX and abs(c["oy"]) <= CENTRE_TOLERANCE_PX
    ]
    timed = [c for c in clicks if c["hold"] is not None]
    instant = [c for c in timed if c["hold"] < INSTANT_RELEASE_MS]
    codes = []
    if len(measured) >= RULE_MIN_CENTRED_CLICKS and len(centred) == len(measured):
        codes.append("CLICK_CENTRE_LOCK")
    if len(instant) >= RULE_MIN_INSTANT_RELEASES:
        codes.append("INSTANT_RELEASE")
    centred_instant = [c for c in centred if c["hold"] is not None and c["hold"] < INSTANT_RELEASE_MS]
    rule_fired = (
        "CLICK_CENTRE_LOCK" in codes and "INSTANT_RELEASE" in codes
        and len(centred_instant) >= RULE_MIN_INSTANT_RELEASES
    )
    holds = sorted(c["hold"] for c in timed)
    typing = analyze_typing(mouse.get("keyboard"))
    typing_fired = bool({"TYPING_INSTANT_HOLD", "TYPING_METRONOME"} & set(typing["codes"]))
    stats = mouse.get("pointerStats") if isinstance(mouse.get("pointerStats"), dict) else {}
    zero_pressure = int(_number(stats.get("zeroPressureDowns"), 0, 10**6) or 0)
    chromium = "chrome/" in str(user_agent).lower() and "firefox/" not in str(user_agent).lower()
    pointer_fired = chromium and zero_pressure >= ZERO_PRESSURE_MIN_PRESSES
    if pointer_fired:
        codes.append("ZERO_PRESSURE_PRESS")
    codes += typing["codes"]
    fired = (
        SYNTHETIC_POINTER_RULE if pointer_fired
        else SYNTHETIC_CLICK_RULE if rule_fired
        else SYNTHETIC_TYPING_RULE if typing_fired
        else None
    )
    return {
        "analysis_version": INPUT_PROVENANCE_VERSION,
        "clicks_measured": len(measured),
        "clicks_centred": len(centred),
        "clicks_timed": len(timed),
        "instant_releases": len(instant),
        "median_hold_ms": holds[len(holds) // 2] if holds else None,
        "evidence_codes": codes,
        "synthetic_click_rule": SYNTHETIC_CLICK_RULE if rule_fired else None,
        "synthetic_input_rule": fired,
        "zero_pressure_presses": zero_pressure,
        "typing": typing,
        "pointer_stats": _pointer_stats(mouse.get("pointerStats")),
    }
