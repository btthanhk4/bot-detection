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
"""

import math

SYNTHETIC_CLICK_RULE = "synthetic_click_v1"
INPUT_PROVENANCE_VERSION = "input_provenance_v1"

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


def analyze_input_provenance(mouse) -> dict:
    """Return click/press evidence and whether the synthetic-click rule fires."""
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
    return {
        "analysis_version": INPUT_PROVENANCE_VERSION,
        "clicks_measured": len(measured),
        "clicks_centred": len(centred),
        "clicks_timed": len(timed),
        "instant_releases": len(instant),
        "median_hold_ms": holds[len(holds) // 2] if holds else None,
        "evidence_codes": codes,
        "synthetic_click_rule": SYNTHETIC_CLICK_RULE if rule_fired else None,
        "pointer_stats": _pointer_stats(mouse.get("pointerStats")),
    }
