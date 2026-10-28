"""Policy 21: evidence that withholds a HUMAN verdict from a desktop session.

The mouse models judge how the pointer moves, not where the input comes from.
A genuine Chrome driven over CDP with humanised paths (patchright with Bezier
moves, Gaussian typing and held clicks, or a replayed human recording; measured
2026-10-27) passes them. The checks below keep such a session from a HUMAN
verdict. None of them proves a bot on its own, so the verdict is a final SUSPECT:

* ``FRAME_LOCKED_POINTER``: Windows Chromium on a display of 83 Hz or less, and
  every pointermove carries a single coalesced sample. CDP waits until each
  injected move is handled, so it delivers at most one per frame (patchright and
  Puppeteer 1.000-1.002 samples per move). Mice and touchpads report at 125 Hz or
  more: OS input through SendInput gave 1.85 at 125 Hz and 10.2 at 1000 Hz, and
  three Windows sessions on the live site 1.88-2.29. macOS and X11 coalesce motion
  before Chrome sees it (a Linux user measured 1.02), and on a 120 Hz+ display a
  125 Hz mouse also gives about one sample, so neither is judged.
* ``UNALIGNED_POINTER``: pointermoves arrive far more often than display frames
  (median spacing at most 0.4 of the frame interval the collector measures, 1.8+)
  with about one coalesced sample each. Chromium hands a page real mouse input
  once per frame, so on a 60 Hz display moves are about 16.7 ms apart; CDP moves
  fired every 2 ms without waiting are delivered one by one, 4 ms apart (measured
  2026-10-27; 1.07 samples per move). Chrome's 30 fps battery saver halves the
  frame rate of input too, which keeps the ratio at about one.
* ``POINTER_API_TAMPERED`` (policy 23): the timing APIs were rewritten in the page.
  Three lines of script made ``getCoalescedEvents`` return the event twice, or
  deleted it, and the frame-lock check passed (2026-10-28). Browsers never hand back
  the event itself and always expose the method in a secure Chromium context, and
  collector 1.9 also reports a non-native ``getCoalescedEvents`` or
  ``requestAnimationFrame``. Privacy extensions spoof navigator and canvas, not these.
* ``NON_BROWSER_REQUEST`` (policy 23): the telemetry request itself lacks what a
  Chromium page always sends (Accept-Language; Sec-Fetch-* over HTTPS). A human-looking
  payload posted by a script, without a browser, was judged HUMAN (2026-10-28) and
  arrived without Accept-Language. None of the stored desktop sessions of people
  lacked either header. A forger can add them; this only removes the cheapest forgery.
* ``SUBFRAME_POINTER_BURST``: moves handled within 1 ms of each other at new
  positions. Browsers hand pages one move per frame; firing several CDP moves at
  once to fake coalesced samples produces these (median 0.3 ms). There were none
  in 2,700 move gaps of 27 desktop sessions on the live site.
* ``CLOUD_SOFTWARE_GPU``: a cloud-provider address with a CPU WebGL renderer, the
  machine every scraping farm rents. People on cloud desktops look the same, which
  is why this is not a BOT rule (see ``idle_cloud_browser_v1``).
* ``ENVIRONMENT_EVIDENCE``: a headless, GPU or permission contradiction, or two
  independent families. Fewer than three do not convict (``environment_tampering_v1``);
  no desktop session of a person on the live site had any.

Pointer timing is judged only on collector payloads (``pointerStats`` present): the
training sets were recorded by other tools with other timing.
"""

import re

DESKTOP_RISK_RULE = "desktop_risk_v1"
DESKTOP_RISK_VERSION = "desktop_risk_v1"
RISK_CODES = ("FRAME_LOCKED_POINTER", "UNALIGNED_POINTER", "POINTER_API_TAMPERED", "SUBFRAME_POINTER_BURST",
              "CLOUD_SOFTWARE_GPU", "NON_BROWSER_REQUEST", "ENVIRONMENT_EVIDENCE")
# Same minimum as the mouse models, so a page they judge is judged here too.
FRAME_LOCK_MIN_MOVES = 25
# CDP measured 1.000-1.051 samples with up to 4.8% multi-sample moves (a stalled main
# thread merges two injected moves); Windows people 1.73-2.52 and 72-91%. A Bluetooth
# mouse reporting every 15 ms would give about 1.1 and 11%.
FRAME_LOCK_MAX_COALESCED = 1.10
FRAME_LOCK_MAX_MULTI_SHARE = 0.06
# Frame interval of a display at 83 Hz or less (120/144/240 Hz: 8.3/6.9/4.2 ms).
FRAME_LOCK_MIN_INTERVAL_MS = 12.0
MIN_MOVE_GAPS = 20
MIN_FRAMES = 30
UNALIGNED_MAX_FRAME_RATIO = 0.4
UNALIGNED_MAX_COALESCED = 1.5
BURST_MAX_GAP_MS = 1.0
BURST_MIN_MOVES = 10
BURST_MIN_SHARE = 0.10
_ANCHOR_FAMILIES = ("HEADLESS_ENV", "GPU", "PERMISSION")
# A Direct3D renderer exists only on Windows, whatever the user agent claims.
_WINDOWS_RENDERER = re.compile(r"Direct3D|D3D11|D3D9", re.I)


def _move_steps(moves):
    """(gap ms, moved) for consecutive move records, in time order."""
    steps = []
    for previous, current in zip(moves, moves[1:]):
        gap = current["time"] - previous["time"]
        steps.append((gap, (current["x"], current["y"]) != (previous["x"], previous["y"])))
    return steps


def _move_interval(steps):
    gaps = sorted(gap for gap, _ in steps if 0 < gap < 100)
    return gaps[len(gaps) // 2] if len(gaps) >= MIN_MOVE_GAPS else None


def analyze_desktop_risk(payload: dict, automation_evidence: dict, moves: list, pointer_stats, judged: bool) -> dict:
    """Risk codes that keep a desktop session from a HUMAN verdict.

    ``moves`` are the sanitized mouse move records; ``pointer_stats`` is the
    summary from input provenance (None when the collector sent none).
    """
    payload = payload if isinstance(payload, dict) else {}
    fingerprint = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
    ua = str(fingerprint.get("userAgent") or "")
    renderer = str(fingerprint.get("webglRenderer") or "")
    stats = pointer_stats if isinstance(pointer_stats, dict) else None
    judged = bool(judged)
    pointer_judged = bool(judged and stats)
    steps = _move_steps(moves) if pointer_judged else []
    interval = _move_interval(steps)
    chromium = "Chrome/" in ua and "Firefox/" not in ua
    windows = "Windows NT" in ua or bool(_WINDOWS_RENDERER.search(renderer))
    frame_ms = stats.get("frame_ms") if stats and stats.get("frames", 0) >= MIN_FRAMES else None
    # Every secure Chromium page exposes coalesced samples for trusted pointer moves.
    api_judged = bool(
        pointer_judged and chromium and stats.get("secure_context") is True
        and stats.get("pointer_moves", 0) >= FRAME_LOCK_MIN_MOVES
    )
    coalesced = api_judged and stats.get("coalesced_mean", 0) >= 0.95
    # Without a measured frame interval (collector < 1.8) the move spacing stands in for it.
    display_ms = frame_ms if frame_ms is not None else interval
    frame_judged = bool(coalesced and windows and display_ms is not None and display_ms >= FRAME_LOCK_MIN_INTERVAL_MS)
    codes = []
    if (frame_judged and stats["coalesced_mean"] <= FRAME_LOCK_MAX_COALESCED
            and stats.get("coalesced_multi_share", 1) <= FRAME_LOCK_MAX_MULTI_SHARE):
        codes.append("FRAME_LOCKED_POINTER")
    if (coalesced and frame_ms is not None and interval is not None
            and interval <= UNALIGNED_MAX_FRAME_RATIO * frame_ms
            and stats["coalesced_mean"] <= UNALIGNED_MAX_COALESCED):
        codes.append("UNALIGNED_POINTER")
    families = (automation_evidence.get("families") or {}) if judged else {}
    if (api_judged and (stats.get("coalesced_self", 0) > 0 or stats.get("coalesced_mean", 0) < 0.5)) or (
            judged and "signals.inputApiPatched" in families.get("NATIVE_PATCH", [])):
        codes.append("POINTER_API_TAMPERED")
    burst = sum(1 for gap, moved in steps if 0 <= gap <= BURST_MAX_GAP_MS and moved)
    if burst >= BURST_MIN_MOVES and burst >= BURST_MIN_SHARE * len(steps):
        codes.append("SUBFRAME_POINTER_BURST")
    if "server.software_renderer" in families.get("NETWORK", []):
        codes.append("CLOUD_SOFTWARE_GPU")
    if families.get("HTTP"):
        codes.append("NON_BROWSER_REQUEST")
    local = [family for family in families if family != "NETWORK"]
    if any(family in _ANCHOR_FAMILIES for family in local) or len(local) >= 2:
        codes.append("ENVIRONMENT_EVIDENCE")
    return {
        "analysis_version": DESKTOP_RISK_VERSION,
        "judged": judged,
        "pointer_judged": pointer_judged,
        "frame_judged": frame_judged,
        "move_interval_ms": interval,
        "frame_ms": frame_ms,
        "subframe_moves": burst,
        "codes": codes,
    }
