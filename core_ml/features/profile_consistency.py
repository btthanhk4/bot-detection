"""Passive profile diagnostics, separate from the released decision policy."""

import re


PROFILE_ANALYSIS_VERSION = "profile_consistency_v1"


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return value[:1024].lower() if isinstance(value, str) else ""


def _os_family(value):
    text = _text(value)
    if "android" in text:
        return "android"
    if any(token in text for token in ("iphone", "ipad", "ipod", "ios")):
        return "ios"
    if "windows" in text or text.startswith("win"):
        return "windows"
    if "mac" in text:
        return "macos"
    if "cros" in text or "chrome os" in text or "chromeos" in text:
        return "chromeos"
    if "linux" in text:
        return "linux"
    return None


def _headless_brands(hints):
    for key in ("brands", "fullVersionList"):
        entries = hints.get(key)
        if isinstance(entries, list) and any(
            _text(_mapping(entry).get("brand")) == "headlesschrome"
            for entry in entries[:8]
        ):
            return True
    return False


def analyze_profile_consistency(payload: dict) -> dict:
    """Report evidence and missing coverage without altering scores or verdicts."""
    payload = _mapping(payload)
    botd = _mapping(payload.get("botd"))
    profile = _mapping(botd.get("profile"))
    if profile.get("schema") != "browser-profile-v1":
        profile = {}
    main = _mapping(profile.get("main"))
    worker = _mapping(profile.get("worker")) if profile.get("workerStatus") == "ok" else {}
    signals = []
    checks = []

    def check(code, available, flagged, strength="inconsistency"):
        checks.append({"code": code, "available": bool(available)})
        if available and flagged:
            signals.append({"code": code, "strength": strength})

    for name, realm in (("PAGE", main), ("WORKER", worker)):
        ua = _text(realm.get("userAgent"))
        hints = _mapping(realm.get("clientHints"))
        check(f"{name}_HEADLESS_UA", bool(ua), bool(re.search(r"headlesschrome/", ua)), "automation")
        check(f"{name}_HEADLESS_CLIENT_HINTS", bool(hints), _headless_brands(hints), "automation")
        os_ua = _os_family(ua)
        os_hints = _os_family(hints.get("platform"))
        check(f"{name}_UA_HINTS_OS_MISMATCH", os_ua and os_hints, os_ua != os_hints)

    main_os = _os_family(main.get("userAgent"))
    worker_os = _os_family(worker.get("userAgent"))
    check("PAGE_WORKER_OS_MISMATCH", main_os and worker_os, main_os != worker_os)
    check("WORKER_WEBDRIVER", type(worker.get("webdriver")) is bool,
          worker.get("webdriver") is True, "automation")
    # CPU counts, locale, exact UA versions and missing APIs can legitimately
    # differ under privacy protection. They are not automation evidence here.
    automation = any(signal["strength"] == "automation" for signal in signals)
    return {
        "analysis_version": PROFILE_ANALYSIS_VERSION,
        "mode": "shadow",
        "signals": signals,
        "checks": checks,
        "available_checks": sum(check["available"] for check in checks),
        "shadow_verdict": "BOT" if automation else "SUSPECT" if signals else None,
        "release_approved": False,
    }
