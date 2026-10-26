"""Turn the touch gestures in live telemetry into weakly labelled training samples.

Only geometry and timing are kept (no page content, IP or key data). Labels are
hints, not ground truth: ``automation`` when the session was convicted by an
automation rule or every contact is the CDP default, ``human_candidate`` for a
phone/tablet session with no automation evidence at all, otherwise
``unlabeled``. Training must treat ``human_candidate`` as noisy.
"""

import hashlib
import re

from core_ml.features.touch import analyze_touch, gesture_features, sanitize_gestures

_MOBILE_UA = re.compile(r"iphone|ipad|ipod|android|mobile", re.IGNORECASE)


def device_family(user_agent: str, platform: str = "") -> str:
    text = f"{user_agent} {platform}".lower()
    if "iphone" in text or "ipad" in text or "ipod" in text:
        return "ios"
    if "android" in text:
        return "android"
    return "other"


def label_hint(analysis: dict, touch_report: dict, *, mobile: bool) -> str:
    breakdown = analysis.get("breakdown") if isinstance(analysis.get("breakdown"), dict) else {}
    automation = breakdown.get("automation_evidence") if isinstance(breakdown.get("automation_evidence"), dict) else {}
    if (analysis.get("verdict") == "BOT" and breakdown.get("automation_rule")) \
            or "SYNTHETIC_CONTACT" in touch_report["research_flags"]:
        return "automation"
    clean = (
        mobile
        and analysis.get("verdict") != "BOT"
        and not breakdown.get("automation_rule")
        # One stray family is common on real phones; two or a cloud IP are not clean.
        and not automation.get("markers")
        and int(automation.get("family_count") or 0) <= 1
        and "NETWORK" not in (automation.get("families") or {})
        and not touch_report["research_flags"]
    )
    return "human_candidate" if clean else "unlabeled"


def build_touch_samples(data: dict, analysis: dict) -> list:
    """One document per gesture; the id is stable across heartbeats that resend it."""
    mouse = data.get("mouse") if isinstance(data.get("mouse"), dict) else {}
    touch = mouse.get("touch") if isinstance(mouse.get("touch"), dict) else None
    gestures = sanitize_gestures(touch)
    if not gestures:
        return []
    fingerprint = data.get("fingerprint") if isinstance(data.get("fingerprint"), dict) else {}
    user_agent = str(fingerprint.get("userAgent") or data.get("_server_user_agent") or "")[:512]
    mobile = bool(_MOBILE_UA.search(user_agent))
    report = analyze_touch(touch)
    label = label_hint(analysis if isinstance(analysis, dict) else {}, report, mobile=mobile)
    collector = data.get("collector") if isinstance(data.get("collector"), dict) else {}
    page = str(collector.get("pageInstanceId") or "")
    viewport = touch.get("viewport") if isinstance(touch.get("viewport"), list) else None
    breakdown = (analysis or {}).get("breakdown") or {}
    samples = []
    for gesture in gestures:
        key = f"{data.get('sessionId')}|{page}|{gesture['t0']}|{gesture['points'][0][1]}|{gesture['points'][0][2]}"
        samples.append({
            "_id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:32],
            "sessionId": data.get("sessionId"),
            "visitorId": data.get("visitorId"),
            "page_instance_id": page or None,
            "t0": gesture["t0"],
            "points": gesture["points"],
            "features": gesture_features(gesture["points"]),
            "viewport": viewport[:2] if viewport else None,
            "dpr": touch.get("dpr") if isinstance(touch.get("dpr"), (int, float)) else None,
            "device": device_family(user_agent, str(fingerprint.get("platform") or "")),
            "mobile_ua": mobile,
            "collector_version": collector.get("sdkVersion"),
            "label_hint": label,
            "verdict": (analysis or {}).get("verdict"),
            "automation_rule": breakdown.get("automation_rule"),
            "touch_flags": report["research_flags"],
            "policy_version": (analysis or {}).get("policy_version"),
        })
    return samples
