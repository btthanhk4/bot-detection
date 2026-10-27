"""Policy 18: a phone or tablet with real finger input and a clean environment is HUMAN.

The mouse models cannot judge touch input, so before policy 18 every phone
session stayed "insufficient evidence". Commercial scorers (Cloudflare bot
score, reCAPTCHA v3, DataDome) rate a standard mobile browser with a clean
fingerprint and network as likely human; behaviour only adds to that. This
rule does the same, and additionally requires trusted touch gestures, so a
page loaded by a script that never touches the screen is not called human.

It is a conclusion from the absence of bot evidence, not from a validated
touch-behaviour model: the confidence is lower than for a desktop mouse
verdict and the reason says so. Any automation rule still wins first.
"""

import re

MOBILE_HUMAN_RULE = "mobile_clean_environment_v1"
MOBILE_HUMAN_MIN_GESTURES = 3
# Families an ordinary phone can trip on its own (header quirks of in-app
# browsers, Client Hints gaps). One is tolerated; anchors never are.
_TOLERATED_FAMILIES = {"HTTP", "CLIENT_HINTS", "CONTEXT", "NATIVE_PATCH"}
_EMULATOR_RENDERER = re.compile(r"swiftshader|llvmpipe|softpipe|android emulator|virtualbox|vmware|bluestacks", re.I)
_X86_PLATFORM = re.compile(r"x86|i686|i386|amd64", re.I)


def _mobile_kind(fingerprint: dict) -> str:
    ua = str(fingerprint.get("userAgent") or "")
    lower = ua.lower()
    if any(token in lower for token in ("iphone", "ipad", "ipod")):
        return "ios"
    if "android" in lower:
        return "android"
    touch = fingerprint.get("maxTouchPoints")
    # iPadOS Safari asks for desktop sites with a Mac user agent.
    # A desktop browser with emulated touch keeps a Chromium UA or a non-Apple GPU.
    if ("Macintosh" in ua and "Chrome/" not in ua and str(fingerprint.get("platform") or "") == "MacIntel"
            and "Apple" in str(fingerprint.get("webglRenderer") or "")
            and isinstance(touch, (int, float)) and not isinstance(touch, bool) and touch > 1):
        return "ipad_desktop_mode"
    if "mobile" in lower:
        return "other_mobile"
    return ""


def analyze_mobile_human(payload: dict, automation_evidence: dict, touch_report: dict,
                         client_flags: list) -> dict:
    """Whether the phone-human rule applies, and what is missing when it does not."""
    payload = payload if isinstance(payload, dict) else {}
    fingerprint = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
    kind = _mobile_kind(fingerprint)
    families = automation_evidence.get("families") or {}
    renderer = str(fingerprint.get("webglRenderer") or "")
    platform = str(fingerprint.get("platform") or "")
    gestures = int(touch_report.get("gestures_total") or 0)
    missing = []
    if not kind:
        missing.append("NOT_MOBILE")
    if gestures < MOBILE_HUMAN_MIN_GESTURES:
        missing.append("FEW_GESTURES")
    if touch_report.get("research_flags"):
        missing.append("TOUCH_FLAGS")
    if _EMULATOR_RENDERER.search(renderer) or (kind == "android" and _X86_PLATFORM.search(platform)):
        missing.append("EMULATOR")
    if automation_evidence.get("mobile_emulation"):
        missing.append("PLATFORM_CONTRADICTION")
    if "NETWORK" in families:
        missing.append("CLOUD_IP")
    if automation_evidence.get("markers") or len(families) > 1 or set(families) - _TOLERATED_FAMILIES:
        missing.append("ENVIRONMENT_EVIDENCE")
    if client_flags:
        missing.append("CLIENT_AUTOMATION_SIGNAL")
    return {
        "rule": MOBILE_HUMAN_RULE,
        "device": kind or None,
        "gestures": gestures,
        "minimum_gestures": MOBILE_HUMAN_MIN_GESTURES,
        "eligible": not missing,
        "missing": missing,
    }
