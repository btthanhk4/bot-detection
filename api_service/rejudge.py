"""Apply the browser-contradiction rules of policies 30-32 to sessions judged before them.

Raw telemetry is kept for days only, so old sessions cannot be scored again. These rules,
though, read only what every stored session keeps: the fingerprint, the environment families,
the forgery codes and the touch report. A session they convict becomes BOT; nothing is ever
moved the other way, and the previous verdict is recorded in ``rejudged``.

    python -m api_service.manage rejudge            # count only
    python -m api_service.manage rejudge --apply    # write
"""

from collections import Counter
from datetime import datetime, timezone

from core_ml.features.client_forgery import (
    APPLE_SYNTHETIC_TOUCH_RULE,
    FORGED_BROWSER_RULE,
    WEBVIEW_WEBDRIVER_RULE,
    apple_synthetic_touch_fires,
    contradictions,
    forged_browser_fires,
    forgery_codes,
    webview_webdriver_fires,
)
from core_ml.models.ensemble import DECISION_POLICY_VERSION

_MOBILE_TOKENS = ("mobile", "android", "iphone", "ipad", "ipod")
_BASIS = {FORGED_BROWSER_RULE: "forged_browser", WEBVIEW_WEBDRIVER_RULE: "webview_automation",
          APPLE_SYNTHETIC_TOUCH_RULE: "synthetic_touch"}
_REASON = {
    FORGED_BROWSER_RULE: "Forged browser: two independent claims no genuine browser makes ({}); applied to the "
                         "stored analysis by policy {}",
    WEBVIEW_WEBDRIVER_RULE: "Android WebView with navigator.webdriver hidden: a WebView runs no browser extensions, "
                            "so the app hosting it hid its own automation flag (applied to the stored analysis by "
                            "policy {1})",
    APPLE_SYNTHETIC_TOUCH_RULE: "Synthetic touches on an iPhone or iPad: contact radius 1 and force 1 at every point "
                                "(Chromium's CDP defaults) (applied to the stored analysis by policy {1})",
}
_FIELDS = {"fingerprint": 1, "verdict": 1, "decision_state": 1, "policy_version": 1, "reasons": 1,
           "breakdown.client_forgery": 1, "breakdown.automation_evidence": 1, "breakdown.touch": 1}


def judge(doc: dict):
    """(rule, contradictions, codes) a stored session now meets, or None."""
    breakdown = doc.get("breakdown") or {}
    evidence = breakdown.get("automation_evidence") or {}
    touch = breakdown.get("touch") or {}
    fingerprint = doc.get("fingerprint") if isinstance(doc.get("fingerprint"), dict) else {}
    payload = {"fingerprint": fingerprint}
    desktop = not any(token in str(fingerprint.get("userAgent") or "").lower() for token in _MOBILE_TOKENS)
    stored = (breakdown.get("client_forgery") or {}).get("codes") or []
    codes = sorted(set(stored) | set(forgery_codes(payload, evidence, desktop=desktop)))
    found = contradictions(codes, evidence, touch.get("research_flags"))
    if forged_browser_fires(codes, evidence, touch.get("research_flags")):
        return FORGED_BROWSER_RULE, found, codes
    if webview_webdriver_fires(payload, codes):
        return WEBVIEW_WEBDRIVER_RULE, found, codes
    if apple_synthetic_touch_fires(payload, touch):
        return APPLE_SYNTHETIC_TOUCH_RULE, found, codes
    return None


def rejudge(db, apply: bool = False, now=None) -> dict:
    """Counts of the sessions the rules convict, by rule and by previous state; writes if ``apply``."""
    now = now or datetime.now(timezone.utc)
    collection = db["detection_results"]
    by_rule, by_state, changed = Counter(), Counter(), 0
    for doc in collection.find({"verdict": {"$ne": "BOT"}}, _FIELDS).batch_size(500):
        found = judge(doc)
        if not found:
            continue
        rule, contradiction_codes, codes = found
        deferred = doc.get("decision_state") == "INSUFFICIENT_EVIDENCE"
        state = "insufficient" if deferred else str(doc.get("verdict") or "").lower()
        by_rule[rule] += 1
        by_state[state] += 1
        if not apply:
            continue
        reason = _REASON[rule].format(", ".join(contradiction_codes).lower().replace("_", " "), DECISION_POLICY_VERSION)
        result = collection.update_one({"_id": doc["_id"], "verdict": {"$ne": "BOT"}}, {"$set": {
            "verdict": "BOT", "is_bot": True, "decision_state": "FINAL", "verdict_locked": True,
            "policy_version": DECISION_POLICY_VERSION,
            "reasons": list(doc.get("reasons") or [])[:19] + [reason],
            "breakdown.automation_rule": rule, "breakdown.decision_basis": _BASIS[rule],
            "breakdown.decision_deferred": False, "breakdown.risk_score_in_domain": False,
            "breakdown.suspect_reason_codes": [], "breakdown.verdict_locked": True,
            "breakdown.client_forgery.codes": codes, "breakdown.client_forgery.contradictions": contradiction_codes,
            "rejudged": {"from_verdict": doc.get("verdict"), "from_state": doc.get("decision_state"),
                         "from_policy": doc.get("policy_version"), "rule": rule,
                         "policy": DECISION_POLICY_VERSION, "at": now},
        }})
        changed += result.modified_count
    return {"convicted": sum(by_rule.values()), "by_rule": dict(by_rule), "by_previous_state": dict(by_state),
            "written": changed, "applied": apply}
