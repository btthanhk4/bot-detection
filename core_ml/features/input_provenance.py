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

Policy 22 re-measured the typing rule on the Aalto 136M keystrokes (168,593 people
typing 15 sentences in a browser; CHI 2018), cut into the collector's 60-key pieces.
The policy 15 thresholds convicted 4,097 of them on rhythm alone (skilled typists keep
an 11-key interval CV under 0.10) and 303 on hold alone (some keyboards and drivers
report key-up with key-down). Scripts give themselves away only by combinations:

* ``TYPING_METRONOME``: interval CV and hold CV both under 0.02 in an 11-key window.
  ``type(text, {delay})`` of Playwright, Puppeteer and patchright holds and spaces
  every key by the delay (0.004-0.009); the most regular person is at 0.027.
* ``TYPING_INSTANT_HOLD``: median hold and median interval both under 12 ms in an
  8-key window, faster than any hand (scripts without a delay: 0.3-1.9 ms). In Aalto
  153 participants do this, all with 8 keys inside 0-12 ms: auto-typers on a typing
  test or logging artefacts, not typing.
* ``TYPING_INSTANT_METRONOME``: median hold under 12 ms with an 11-key interval CV
  under 0.05, as Selenium typing one key per fixed sleep does (0.017). Of the 182
  people with instant holds, the steadiest has 0.090.
"""

import math
import statistics

SYNTHETIC_CLICK_RULE = "synthetic_click_v1"
SYNTHETIC_TYPING_RULE = "synthetic_typing_v1"
SYNTHETIC_POINTER_RULE = "synthetic_pointer_v1"
INPUT_PROVENANCE_VERSION = "input_provenance_v3"

MAX_KEYSTROKES = 60
BURST_GAP_MS = 1500.0
TYPING_FAST_MIN_KEYS = 8
# 12 ms (policy 16, was 20): rapid-trigger keyboards release earlier than the
# CMU keyboards (human floor 30.2 ms); scripts measured at 1.4-3.5 ms.
TYPING_FAST_MEDIAN_HOLD_MS = 12.0
# Policy 22: an instant hold convicts only with keys also this close together.
TYPING_FAST_MEDIAN_INTERVAL_MS = 12.0
TYPING_RHYTHM_MIN_KEYS = 11
# Policy 22: interval and hold CV both below this (was interval CV < 0.10 alone).
TYPING_RHYTHM_MAX_CV = 0.02
TYPING_INSTANT_RHYTHM_MAX_CV = 0.05
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
    # Display frame interval measured by collector >= 1.8 over requestAnimationFrame.
    frame_ms = _number(raw.get("frameMs"), 1, 1000)
    frames = _number(raw.get("frames"), 0, 10**6)
    return {
        "pointer_moves": int(moves),
        "coalesced_mean": round(total / moves, 3),
        "coalesced_max": int(maximum or 0),
        "coalesced_multi_share": round((multi or 0) / moves, 3),
        "secure_context": raw.get("secureContext") is True,
        "frame_ms": frame_ms,
        "frames": int(frames or 0),
    }


# Key kinds sent by the collector: c = ASCII character, n = non-ASCII character
# (collector >= 1.6; older ones sent these as c), b = Backspace/Delete
# (>= 1.6; older: o), o = other key, u = virtual keyboard (dropped).
KEY_KINDS = ("c", "n", "b", "o")
# Vietnamese Telex/VNI input methods (Unikey, EVKey) replace typed letters by
# injecting Backspace and accented letters with ~0 ms holds. A burst with an
# instant Backspace is an input method at work, not a script, and is not judged.
# Scripts typing accented text send no Backspace and are still judged.
INJECTED_HOLD_MS = 10.0


def sanitize_keystrokes(raw):
    """Keep well-formed physical-keyboard strokes (timing and kind only) in time order."""
    if not isinstance(raw, list):
        return []
    clean = []
    for stroke in raw[-MAX_KEYSTROKES:]:
        if not isinstance(stroke, dict) or stroke.get("k") not in KEY_KINDS:
            continue
        at = _number(stroke.get("t"), 0, 10**9)
        if at is None:
            continue
        hold = stroke.get("h")
        clean.append({"t": at, "k": stroke["k"], "h": _number(hold, 0, 5000) if hold is not None else None})
    return sorted(clean, key=lambda stroke: stroke["t"])


def _letter_runs(burst):
    """Consecutive character keys (ASCII or accented); any other key ends the run."""
    runs, current = [], []
    for stroke in burst:
        if stroke["k"] in ("c", "n"):
            current.append(stroke)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _input_method_injection(burst):
    return any(
        stroke["k"] == "b" and stroke["h"] is not None and stroke["h"] < INJECTED_HOLD_MS
        for stroke in burst
    )


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


def _rounded(value, digits):
    return None if value is None else round(value, digits)


def _cv(values):
    mean = sum(values) / len(values)
    return statistics.pstdev(values) / mean if mean > 0 else None


def analyze_typing(keyboard) -> dict:
    keyboard = keyboard if isinstance(keyboard, dict) else {}
    strokes = sanitize_keystrokes(keyboard.get("keystrokes"))
    coarse = keyboard.get("coarsePointer") is True
    # The quickest 8-key window by its slower of median hold and median interval.
    fastest, lowest_interval_cv, lowest_rhythm_cv, lowest_instant_cv = None, None, None, None
    input_method_bursts = 0

    def lowest(current, value):
        return value if current is None or (value is not None and value < current) else current

    # Sliding windows over runs of consecutive character keys: one typed field can
    # sit next to a pause, a correction or a different field.
    for burst in _bursts(strokes):
        if _input_method_injection(burst):
            input_method_bursts += 1
            continue
        for run in _letter_runs(burst):
            for start in range(len(run) - TYPING_FAST_MIN_KEYS + 1):
                window = run[start:start + TYPING_FAST_MIN_KEYS]
                holds = [s["h"] for s in window if s["h"] is not None]
                if len(holds) < len(window):
                    continue
                hold = statistics.median(holds)
                interval = statistics.median([b["t"] - a["t"] for a, b in zip(window, window[1:])])
                if fastest is None or max(hold, interval) < max(fastest):
                    fastest = (hold, interval)
            for start in range(len(run) - TYPING_RHYTHM_MIN_KEYS + 1):
                window = run[start:start + TYPING_RHYTHM_MIN_KEYS]
                interval_cv = _cv([b["t"] - a["t"] for a, b in zip(window, window[1:])])
                if interval_cv is None:
                    continue
                lowest_interval_cv = lowest(lowest_interval_cv, interval_cv)
                holds = [s["h"] for s in window if s["h"] is not None]
                if len(holds) < len(window):
                    continue
                hold_cv = _cv(holds)
                if hold_cv is not None:
                    lowest_rhythm_cv = lowest(lowest_rhythm_cv, max(interval_cv, hold_cv))
                if statistics.median(holds) < TYPING_FAST_MEDIAN_HOLD_MS:
                    lowest_instant_cv = lowest(lowest_instant_cv, interval_cv)
    codes = []
    if not coarse and fastest is not None and (
            fastest[0] < TYPING_FAST_MEDIAN_HOLD_MS and fastest[1] < TYPING_FAST_MEDIAN_INTERVAL_MS):
        codes.append("TYPING_INSTANT_HOLD")
    if not coarse and lowest_rhythm_cv is not None and lowest_rhythm_cv < TYPING_RHYTHM_MAX_CV:
        codes.append("TYPING_METRONOME")
    if not coarse and lowest_instant_cv is not None and lowest_instant_cv < TYPING_INSTANT_RHYTHM_MAX_CV:
        codes.append("TYPING_INSTANT_METRONOME")
    bulk = _number(keyboard.get("bulkInserts"), 0, 10**6)
    if bulk:
        codes.append("BULK_TEXT_INSERT")  # reported only; autofill and dictation look alike
    return {
        "keystrokes": len(strokes),
        "coarse_pointer": coarse,
        "input_method_bursts": input_method_bursts,
        "fastest_median_hold_ms": _rounded(fastest and fastest[0], 1),
        "fastest_median_interval_ms": _rounded(fastest and fastest[1], 1),
        "lowest_interval_cv": _rounded(lowest_interval_cv, 3),
        "lowest_rhythm_cv": _rounded(lowest_rhythm_cv, 3),
        "lowest_instant_interval_cv": _rounded(lowest_instant_cv, 3),
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
    typing_fired = bool({"TYPING_INSTANT_HOLD", "TYPING_METRONOME", "TYPING_INSTANT_METRONOME"} & set(typing["codes"]))
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
