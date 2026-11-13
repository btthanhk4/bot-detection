"""Page presence, first-touch reaction, device motion and Client Hints of a phone (collector 1.16.0).

Policy 33 reads three of these:

- ``NOT_VIEWED``: the page ran in a prerender or a background tab and was never shown;
  a session nobody saw is not a visit and is never called human.
- ``INSTANT_TOUCH``: the first finger landed less than 120 ms after the page appeared.
  Visual reaction to a new page takes a few hundred milliseconds (simple visual reaction
  time is ~200-250 ms in adults), an injected tap does not wait.
- ``CH_EMULATOR``: an Android user agent whose Client Hints report an x86 CPU or an SDK
  emulator model (``sdk_gphone…``, ``Android SDK built for x86``).

Motion is summarised only and stays research evidence: whether a phone held in a hand
(tilted, trembling; zkSENSE, BeCAPTCHA) can stand in for touches needs a validated
baseline first. ``STILL_DEVICE`` (no tremor at all) and ``NO_MOTION`` are reported, not used.
"""

import math
import re

PRESENCE_VERSION = "presence_v1"
INSTANT_TOUCH_MS = 120
NOT_VIEWED_MS = 500
STILL_SD = 0.005
HELD_MIN_SD = 0.02
_SDK_MODEL = re.compile(r"sdk_gphone|android sdk built|emulator|generic_x86|vbox86|goldfish|ranchu", re.I)


def _num(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and low <= value <= high else None


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else None


def sanitize_presence(raw) -> dict:
    """Bounded copy of ``mouse.presence``; anything malformed becomes None."""
    raw = raw if isinstance(raw, dict) else {}
    motion = raw.get("motion") if isinstance(raw.get("motion"), dict) else {}
    status = motion.get("status") if motion.get("status") in ("ok", "no_events", "unsupported", "permission_gated") else None
    return {
        "reported": bool(raw),
        "prerendered": raw.get("prerendered") if isinstance(raw.get("prerendered"), bool) else None,
        "initial_visibility": _text(raw.get("initialVisibility"), 16),
        "first_visible_ms": _num(raw.get("firstVisibleMs"), 0, 86_400_000),
        "visible_ms": _num(raw.get("visibleMs"), 0, 86_400_000),
        "hidden_count": _num(raw.get("hiddenCount"), 0, 100_000),
        "first_touch_ms": _num(raw.get("firstTouchMs"), 0, 86_400_000),
        "scrolls": _num(raw.get("scrolls"), 0, 10_000_000),
        "max_scroll_ratio": _num(raw.get("maxScrollRatio"), 0, 1),
        "motion": {
            "status": status,
            "events": _num(motion.get("events"), 0, 100_000),
            "interval_ms": _num(motion.get("intervalMs"), 0, 60_000),
            "gravity": _num(motion.get("gravity"), 0, 100),
            "tilt_deg": _num(motion.get("tiltDeg"), 0, 90),
            "linear_sd": _num(motion.get("linearSd"), 0, 1000),
            "gravity_sd": _num(motion.get("gravitySd"), 0, 1000),
            "rotation_mean": _num(motion.get("rotationMean"), 0, 100_000),
            "rotation_sd": _num(motion.get("rotationSd"), 0, 100_000),
        },
    }


def client_hints(payload: dict) -> dict:
    """High-entropy Client Hints of the page (model, CPU architecture), when sent."""
    botd = payload.get("botd") if isinstance(payload.get("botd"), dict) else {}
    profile = botd.get("profile") if isinstance(botd.get("profile"), dict) else {}
    main = profile.get("main") if isinstance(profile.get("main"), dict) else {}
    hints = main.get("clientHints") if isinstance(main.get("clientHints"), dict) else {}
    return {
        "model": _text(hints.get("model"), 64),
        "architecture": _text(hints.get("architecture"), 16),
        "platform_version": _text(hints.get("platformVersion"), 32),
        "mobile": hints.get("mobile") if isinstance(hints.get("mobile"), bool) else None,
    }


def analyze_presence(payload: dict, *, android: bool) -> dict:
    """Presence summary and the codes policy 33 reads (and the research-only ones)."""
    payload = payload if isinstance(payload, dict) else {}
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    presence = sanitize_presence(mouse.get("presence"))
    hints = client_hints(payload)
    codes, research = [], []
    if presence["reported"]:
        never_shown = presence["first_visible_ms"] is None
        if never_shown or (presence["visible_ms"] is not None and presence["visible_ms"] < NOT_VIEWED_MS
                           and presence["initial_visibility"] != "visible"):
            codes.append("NOT_VIEWED")
        if presence["first_touch_ms"] is not None and presence["first_touch_ms"] < INSTANT_TOUCH_MS:
            codes.append("INSTANT_TOUCH")
        motion = presence["motion"]
        if motion["status"] == "ok" and motion["linear_sd"] is not None and motion["gravity_sd"] is not None:
            if motion["linear_sd"] < STILL_SD and motion["gravity_sd"] < STILL_SD:
                research.append("STILL_DEVICE")
            elif motion["linear_sd"] >= HELD_MIN_SD and motion["tilt_deg"] is not None and 10 <= motion["tilt_deg"] <= 85:
                research.append("HELD_IN_HAND")
        elif motion["status"] == "no_events" and android and (presence["visible_ms"] or 0) >= 3000:
            research.append("NO_MOTION")
    if android and ((hints["architecture"] or "").lower().startswith("x86") or _SDK_MODEL.search(hints["model"] or "")):
        codes.append("CH_EMULATOR")
    if android and hints["model"] == "" and hints["mobile"] is False:
        research.append("CH_DESKTOP_HINTS")
    return {"analysis_version": PRESENCE_VERSION, **presence, "client_hints": hints,
            "codes": codes, "research_flags": research}
