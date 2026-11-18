"""Apply the browser-contradiction rules of policies 30-32 to sessions judged before them.

Raw telemetry is kept for days only, so old sessions cannot be scored again. These rules,
though, read only what every stored session keeps: the fingerprint, the environment families,
the forgery codes and the touch report. A session they convict becomes BOT; nothing is ever
moved the other way, and the previous verdict is recorded in ``rejudged``.

    python -m api_service.manage rejudge            # count only
    python -m api_service.manage rejudge --apply    # write

Policy 48 (``map_three_verdicts``): stored sessions the detector left insufficient become SUSPECT (an anomaly
in what they stored) or HUMAN, as new sessions are; the previous state is recorded in ``rejudged``.

    python -m api_service.manage three-verdicts            # count only
    python -m api_service.manage three-verdicts --apply    # write

``rescore`` (19 Nov 2026): every stored session whose raw snapshots are still kept is scored again with the
running detector and policy 48's three verdicts, snapshot after snapshot, under the same storage rules as the
API (a locked BOT stays, a verdict mapped from too little evidence never replaces one the evidence made). Only a
verdict that changes is written, with the previous one in ``rejudged``; a session updated in the last 30
minutes is left to the live traffic.

    python -m api_service.manage rescore            # count only
    python -m api_service.manage rescore --apply    # write
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

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
    user_agent = str(fingerprint.get("userAgent") or "")
    found = contradictions(codes, evidence, touch.get("research_flags"), user_agent=user_agent)
    if forged_browser_fires(codes, evidence, touch.get("research_flags"), user_agent=user_agent):
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


def map_three_verdicts(db, apply: bool = False, now=None) -> dict:
    """Policy 48 on stored sessions: counts of the insufficient ones by the verdict they map to; writes if
    ``apply``. Only what a session stored is read (its presence, phone report, environment families and mouse
    count), so a desktop stored without page presence (collector before 1.16) cannot show DESKTOP_IDLE."""
    from core_ml.three_verdicts import (
        INPUT_ANOMALY_BASIS,
        NO_BOT_EVIDENCE_BASIS,
        THREE_VERDICTS_VERSION,
        input_anomalies,
    )

    now = now or datetime.now(timezone.utc)
    collection = db["detection_results"]
    counts, written = Counter(), 0
    for doc in collection.find({"decision_state": "INSUFFICIENT_EVIDENCE"},
                               {"breakdown": 1, "verdict": 1, "decision_state": 1, "policy_version": 1,
                                "reasons": 1}).batch_size(500):
        breakdown = doc.get("breakdown") or {}
        anomalies = input_anomalies(breakdown, stored=True)
        verdict = "SUSPECT" if anomalies else "HUMAN"
        phone = bool((breakdown.get("mobile_human") or {}).get("device") or breakdown.get("unsupported_mobile"))
        counts[f"{'phone' if phone else 'desktop'} {verdict}"] += 1
        for code in anomalies:
            counts[f"anomaly {code}"] += 1
        if not apply:
            continue
        reason = (f"Policy {DECISION_POLICY_VERSION}: too little input, and an anomaly: "
                  + ", ".join(anomalies).lower().replace("_", " ") if anomalies else
                  f"Policy {DECISION_POLICY_VERSION}: too little input and no bot evidence: a HUMAN of the lowest confidence")
        result = collection.update_one({"_id": doc["_id"], "decision_state": "INSUFFICIENT_EVIDENCE"}, {"$set": {
            "verdict": verdict, "is_bot": False, "decision_state": "FINAL", "verdict_locked": False,
            "verdict_mapped": True, "policy_version": DECISION_POLICY_VERSION,
            "reasons": [reason] + list(doc.get("reasons") or [])[:19],
            "breakdown.decision_basis": INPUT_ANOMALY_BASIS if anomalies else NO_BOT_EVIDENCE_BASIS,
            "breakdown.decision_deferred": False, "breakdown.verdict_locked": False,
            "breakdown.suspect_reason_codes": anomalies,
            "breakdown.three_verdicts": {
                "version": THREE_VERDICTS_VERSION, "from_state": "INSUFFICIENT_EVIDENCE",
                "from_basis": breakdown.get("decision_basis"),
                "from_codes": list(breakdown.get("suspect_reason_codes") or []), "anomalies": anomalies},
            "rejudged": {"from_verdict": doc.get("verdict"), "from_state": doc.get("decision_state"),
                         "from_policy": doc.get("policy_version"), "rule": THREE_VERDICTS_VERSION,
                         "policy": DECISION_POLICY_VERSION, "at": now},
        }})
        written += result.modified_count
    return {"mapped": sum(v for k, v in counts.items() if not k.startswith("anomaly")),
            "counts": dict(counts), "written": written, "applied": apply}


RESCORE_VERSION = "rescore_v1"
RESCORE_QUIET_MINUTES = 30
_SNAPSHOT_FIELDS = {"payload_json": 1, "server_headers": 1, "server_user_agent": 1, "received_at": 1}


def _verdict_class(verdict, state) -> str:
    value = str(verdict or "").upper()
    if value in ("BOT", "HUMAN"):
        return value
    return "INSUFFICIENT" if state == "INSUFFICIENT_EVIDENCE" else "SUSPECT"


def _replaces(stored, result) -> bool:
    """The rule api_service.database.save_detection_result applies: does a new result replace the stored one."""
    if stored is None:
        return True
    if result.get("decision_state") != "FINAL":
        return stored["decision_state"] != "FINAL"
    if (result.get("breakdown") or {}).get("three_verdicts"):
        return stored["decision_state"] != "FINAL" or stored["mapped"]
    if str(result.get("verdict") or "").upper() != "BOT":
        return not stored["is_bot"] or stored["decision_state"] != "FINAL" or not stored["locked"]
    return True


def score_session(detector, snapshots, map_result):
    """Replay a session's raw snapshots in order, as the API scores and stores them: the session's mouse scores
    carried from one snapshot to the next (policy 40), each result mapped (policy 48), the storage rules applied.
    Returns the stored state the session ends with, or None when no snapshot could be scored."""
    prior, stored, strikes = None, None, 0
    for snapshot in snapshots:
        try:
            payload = json.loads(snapshot.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        payload["_server_headers"] = snapshot.get("server_headers") or {}
        payload["_server_user_agent"] = snapshot.get("server_user_agent") or ""
        payload["_session_mouse"] = prior
        try:
            result = detector.predict(payload)
        except Exception:  # noqa: BLE001 - a snapshot the detector rejects is skipped, as live
            continue
        new = result.pop("_session_mouse_new", None) or {}
        prior = {"chunks": {**((prior or {}).get("chunks") or {}), **(new.get("chunks") or {})},
                 "windows": {**((prior or {}).get("windows") or {}), **(new.get("windows") or {})}}
        result = map_result(result, payload)
        verdict = str(result.get("verdict") or "").upper()
        rule_locked = bool((result.get("breakdown") or {}).get("verdict_locked", verdict == "BOT"))
        if _replaces(stored, result):
            strikes += 1 if verdict == "BOT" and not rule_locked else 0
            stored = {"result": result, "decision_state": result.get("decision_state"), "is_bot": verdict == "BOT",
                      "locked": rule_locked or (verdict == "BOT" and strikes >= 2), "strikes": strikes,
                      "mapped": bool((result.get("breakdown") or {}).get("three_verdicts"))}
    return stored


def rescore(db, detector=None, apply: bool = False, now=None, quiet_minutes: int = RESCORE_QUIET_MINUTES,
            model_bundle_id: str = "") -> dict:
    """Counts of the stored verdicts the running code changes, by transition; writes them if ``apply``."""
    from api_service.database import _safe_probability, _sanitize_bson_value
    from core_ml.three_verdicts import apply_three_verdicts

    if detector is None:
        from api_service import main

        detector, model_bundle_id = main.ensemble_detector, main.model_bundle_id
    now = now or datetime.now(timezone.utc)
    quiet_before = now - timedelta(minutes=quiet_minutes)
    results = db["detection_results"]
    changes, written, scored, unscored, live = Counter(), 0, 0, 0, 0
    for doc in results.find({}, {"sessionId": 1, "verdict": 1, "decision_state": 1, "policy_version": 1,
                                 "updated_at": 1}).batch_size(200):
        updated = doc.get("updated_at")
        if isinstance(updated, datetime):
            if (updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)) > quiet_before:
                live += 1
                continue
        snapshots = {}
        for name in ("telemetry_captures", "labeled_captures"):
            for snapshot in db[name].find({"sessionId": doc["sessionId"]}, _SNAPSHOT_FIELDS):
                snapshots[snapshot["_id"]] = snapshot
        stored = score_session(detector, sorted(snapshots.values(), key=lambda s: s.get("received_at") or 0),
                               apply_three_verdicts) if snapshots else None
        if stored is None:
            unscored += 1
            continue
        scored += 1
        result = stored["result"]
        old = _verdict_class(doc.get("verdict"), doc.get("decision_state"))
        new = _verdict_class(result.get("verdict"), result.get("decision_state"))
        if old == new:
            continue
        changes[f"{old} -> {new}"] += 1
        if not apply:
            continue
        verdict = str(result.get("verdict") or "UNKNOWN").upper()
        update = results.update_one({"_id": doc["_id"], "updated_at": updated}, {"$set": {
            "verdict": verdict, "is_bot": verdict == "BOT",
            "decision_state": str(result.get("decision_state") or "FINAL"),
            "verdict_locked": stored["locked"], "bot_strikes": stored["strikes"],
            "verdict_mapped": stored["mapped"],
            "bot_probability": _safe_probability(result.get("bot_probability")),
            "confidence": _safe_probability(result.get("confidence")),
            "score_calibrated": result.get("score_calibrated") is True,
            "policy_version": str(result.get("policy_version") or DECISION_POLICY_VERSION)[:32],
            "model_bundle_id": str(model_bundle_id or result.get("model_bundle_id") or "")[:128],
            "reasons": _sanitize_bson_value(list(result.get("reasons") or [])[:20]),
            "breakdown": _sanitize_bson_value(result.get("breakdown") or {}),
            "rejudged": {"from_verdict": doc.get("verdict"), "from_state": doc.get("decision_state"),
                         "from_policy": doc.get("policy_version"), "rule": RESCORE_VERSION,
                         "policy": DECISION_POLICY_VERSION, "at": now},
        }})
        written += update.modified_count
    return {"scored": scored, "without_raw": unscored, "left_to_live_traffic": live,
            "changed": sum(changes.values()), "changes": dict(changes), "written": written, "applied": apply}
