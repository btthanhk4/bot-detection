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

Policy 35, from 1,361 phone sessions of 13-14 Nov 2026 (collector 1.16.1) checked against the
Fingerprint flags stored with each label:

- ``SYNTHETIC_MOTION``: a phone lying perfectly level (mean tilt at most 0.2 degrees) whose
  accelerometer nevertheless jitters (linear acceleration SD of 0.03 m/s^2 or more), over 100+
  events. Emulated sensors start from the ideal gravity vector (0, 0, 9.81) and add noise
  (Petsas et al., EuroSec 2014: emulators betray themselves by ideal sensor values). A real
  phone on a table is tilted by its camera bump and calibration offset: the 1,165 other phones
  reporting motion ranged from 0.6 degrees up, none below. 59 sessions showed it, on dozens of
  claimed models, all at 9.79-9.82 m/s^2 and 60 Hz; Fingerprint flagged 47 of the 52 it had
  checked (tampering, anti-detect browser), yet 13 had been HUMAN. It withholds HUMAN.
  Policy 39: a real low-end phone does read perfectly level. A Redmi (220333QAG) lying on a desk
  in a controlled test (16 Nov 2026) reported tilt 0.0 at 9.80 m/s^2, linear SD 0.13-0.34, and
  escaped only by having 84 events. Its gravity channel did not move (SD 0.0) and it has no
  gyroscope; the emulator adds the same noise to both channels (gravity SD 0.068-0.077 in every
  one of its sessions, and all 583 emulated_phone BOT verdicts of 13-16 Nov had 0.03 or more).
  The gravity channel must now jitter too (SD 0.03 or more).
- ``sensor_signature``: the gravity magnitude and tilt of a phone lying still. Calibration
  offsets differ from one physical device to the next (SensorID, IEEE S&P 2019), so the same
  values on three different claimed models are one device, or one emulator template, behind
  spoofed identities. The API counts the models (``SHARED_SENSOR_SIGNATURE``, see
  ``core_ml.features.server_context``).
"""

import math
import re

PRESENCE_VERSION = "presence_v4"
EMULATED_PHONE_RULE = "emulated_phone_v1"
SENSORLESS_PHONE_RULE = "sensorless_phone_v1"
MOBILE_HELD_RULE = "mobile_held_device_v2"
# Policy 43: an Android phone whose motion sensor fired at most a handful of events, without gravity,
# while the page was visible for 10 s or more (a real accelerometer streams ~60 events a second at 9.8).
SENSORLESS_MAX_EVENTS = 5
SENSORLESS_MAX_GRAVITY = 1.0
SENSORLESS_MIN_VISIBLE_MS = 10_000
# Policy 43: a phone held in a hand: tilted, trembling and turning (gyroscope).
# Policy 44: over 8+ events instead of 30. Collector 1.16-1.17 often reported only the first
# second of a short visit (the script starts late and the last snapshot is lost on an app switch):
# on the replay of 18 Nov 2026, 59 untouched phones held in a hand had 8-29 events; Fingerprint
# flagged none of the 18 it had checked, and 1 of 645 BOT phones showed the pattern.
HELD_MIN_EVENTS = 8
HELD_MIN_ROTATION_SD = 0.1
INSTANT_TOUCH_MS = 120
NOT_VIEWED_MS = 500
STILL_SD = 0.005
HELD_MIN_SD = 0.02
SYNTHETIC_MAX_TILT = 0.2
SYNTHETIC_MIN_NOISE = 0.03
SYNTHETIC_MIN_EVENTS = 100
# A phone lying still enough for its mean gravity and tilt to be its calibration fingerprint.
SIGNATURE_MAX_GRAVITY_SD = 0.06
SIGNATURE_MAX_ROTATION_SD = 0.1
SIGNATURE_MIN_EVENTS = 50
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


def synthetic_motion(motion: dict) -> bool:
    """Policy 35: perfectly level, yet jittering (sanitized motion summary)."""
    return bool(
        motion.get("status") == "ok" and motion.get("tilt_deg") is not None
        and motion["tilt_deg"] <= SYNTHETIC_MAX_TILT
        and (motion.get("linear_sd") or 0) >= SYNTHETIC_MIN_NOISE
        # Policy 39: both channels jitter alike (a real level phone's gravity channel stays still).
        and (motion.get("gravity_sd") or 0) >= SYNTHETIC_MIN_NOISE
        and (motion.get("events") or 0) >= SYNTHETIC_MIN_EVENTS
    )


def sensors_unavailable(presence: dict) -> bool:
    """Policy 43: the motion sensor reported a few events without gravity on a page visible 10 s+."""
    motion = presence.get("motion") or {}
    return bool(
        motion.get("status") == "ok" and (motion.get("events") or 0) <= SENSORLESS_MAX_EVENTS
        and (motion.get("gravity") is None or motion["gravity"] < SENSORLESS_MAX_GRAVITY)
        and (presence.get("visible_ms") or 0) >= SENSORLESS_MIN_VISIBLE_MS
    )


def held_in_hand(motion: dict) -> bool:
    """Policy 43: tilted 10-85 degrees, trembling (linear SD 0.02+) and turning (gyroscope SD above
    0.1): a phone in a person's hand (sanitized motion summary). Policy 44: over 8+ events (was 30).
    An emulated sensor lies level (``SYNTHETIC_MOTION``, tilt at most 0.2) and does not turn."""
    return bool(
        motion.get("status") == "ok" and (motion.get("events") or 0) >= HELD_MIN_EVENTS
        and motion.get("tilt_deg") is not None and 10 <= motion["tilt_deg"] <= 85
        and (motion.get("linear_sd") or 0) >= HELD_MIN_SD
        and (motion.get("rotation_sd") or 0) > HELD_MIN_ROTATION_SD
    )


def sensorless_phone_fires(research_flags, server_codes) -> bool:
    """Policy 43 (``sensorless_phone_v1``): motion sensors that do not stream, and independently an audio
    stack no other phone reported. On the replay of 17 Nov 2026 (3,674 captured sessions), 200 phones;
    Fingerprint flagged 159 of 189 checked (84%) and the other 30 are the same farm: VPN 30/30, one tap
    25-40 s after the page appeared 30/30. Each channel alone stays a SUSPECT at most."""
    return "SENSORS_UNAVAILABLE" in set(research_flags or ()) and "AUDIO_NOVEL" in set(server_codes or ())


def emulated_phone_fires(presence_codes, server_codes, browser_contradictions) -> bool:
    """Policy 36 (``emulated_phone_v1``): emulated motion sensors and, from an independent channel,
    an audio stack never seen on any other phone (noise injection), a time zone of another country
    than the address, or a browser contradiction. On 13-14 Nov 2026, 59 phones; Fingerprint flagged 45
    of the 51 it checked (88%; the BOT rules already deployed on phones: 77%), and the other 6 match
    the flagged ones on all seven motion statistics. None of 352 obvious people (3+ gestures, held in a
    hand, nothing against them) showed even one of the channels."""
    return "SYNTHETIC_MOTION" in set(presence_codes or ()) and bool(
        {"AUDIO_NOVEL", "TIMEZONE_MISMATCH"} & set(server_codes or ()) or browser_contradictions)


def still_signature(motion: dict):
    """(gravity, tilt) of a phone lying still, or None (sanitized motion summary)."""
    if (motion.get("status") != "ok" or motion.get("gravity") is None or motion.get("tilt_deg") is None
            or motion.get("gravity_sd") is None or motion["gravity_sd"] >= SIGNATURE_MAX_GRAVITY_SD
            or (motion.get("events") or 0) < SIGNATURE_MIN_EVENTS
            or (motion.get("rotation_sd") is not None and motion["rotation_sd"] >= SIGNATURE_MAX_ROTATION_SD)):
        return None
    return motion["gravity"], motion["tilt_deg"]


def sensor_signature(payload: dict):
    """Policy 35: (gravity, tilt, claimed model) of a phone lying still, or None."""
    payload = payload if isinstance(payload, dict) else {}
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    signature = still_signature(sanitize_presence(mouse.get("presence"))["motion"])
    model = (client_hints(payload)["model"] or "").strip()
    return (*signature, model) if signature and model else None


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
        if synthetic_motion(motion):
            codes.append("SYNTHETIC_MOTION")
        if motion["status"] == "ok" and motion["linear_sd"] is not None and motion["gravity_sd"] is not None:
            if motion["linear_sd"] < STILL_SD and motion["gravity_sd"] < STILL_SD:
                research.append("STILL_DEVICE")
            elif motion["linear_sd"] >= HELD_MIN_SD and motion["tilt_deg"] is not None and 10 <= motion["tilt_deg"] <= 85:
                research.append("HELD_IN_HAND")
        elif motion["status"] == "no_events" and android and (presence["visible_ms"] or 0) >= 3000:
            research.append("NO_MOTION")
        if android and sensors_unavailable(presence):
            research.append("SENSORS_UNAVAILABLE")
        if held_in_hand(motion):
            research.append("HELD_DEVICE")
    if android and ((hints["architecture"] or "").lower().startswith("x86") or _SDK_MODEL.search(hints["model"] or "")):
        codes.append("CH_EMULATOR")
    if android and hints["model"] == "" and hints["mobile"] is False:
        research.append("CH_DESKTOP_HINTS")
    return {"analysis_version": PRESENCE_VERSION, **presence, "client_hints": hints,
            "codes": codes, "research_flags": research}
