"""Policy 48: three verdicts for the product.

The detector says when it has too little evidence to judge a session (no touch, no mouse input, nothing for or
against it). That is the honest outcome of the method, and its release gates test it. The product shows three
verdicts instead (the author's decision, 18 Nov 2026): BOT only when a rule convicts, SUSPECT when the session
shows an anomaly, HUMAN otherwise. A session without bot evidence is let through, as commercial bot scores treat
it: a HUMAN of the lowest confidence (basis ``no_bot_evidence``) that keeps where it came from
(``breakdown.three_verdicts``), so the method's own outcome can still be reported.

The anomalies, measured on the policy 47 replay of 18 Nov 2026 (3,674 sessions, 2,370 with a Fingerprint
reference; "flagged": Fingerprint bot "bad", tampering or anti-detect), among the 627 undecided sessions:

* Phones (528, 3.2% flagged; phones already HUMAN: 1.4%). Without an anomaly 2.3% flagged, never shown 3.7%
  (in-app browsers preload ad pages): they become HUMAN. Two anomalies make them SUSPECT:
  ``UNVERIFIED_PAGE_LOAD``, telemetry for a page the site never issued a valid token for (what forged
  telemetry looks like; a missing token only counts once the page was shown 5 s, see TOKEN_GRACE_MS), and
  ``SENSORS_UNAVAILABLE``, a motion sensor that reports nothing over 10 s (the farm of policy 43).
* Desktops (99, 79% flagged). Four anomalies make them SUSPECT:
  ``DESKTOP_IDLE``, a page shown 10 s or more with fewer than 10 mouse moves (38 of 44 flagged);
  an automation evidence family (15 of 15); no page token (2 of 2); a page never shown (5 of 7).
  Short visits and visits with some mouse input become HUMAN.
* Any device: what the detector itself raised (``CORE_ANOMALIES``), automation the profile diagnostics saw
  (``PROFILE_AUTOMATION``), and no sign that a page was ever shown (``NO_PAGE_PRESENCE``: no page presence
  and no page age, a bare telemetry post). None of the replay's undecided sessions showed them.
"""

THREE_VERDICTS_VERSION = "three_verdicts_v1"
NO_BOT_EVIDENCE_BASIS = "no_bot_evidence"
INPUT_ANOMALY_BASIS = "input_anomaly"
DESKTOP_IDLE_MS = 10_000
DESKTOP_IDLE_MAX_MOVES = 10
# What the detector itself raised on a session it could not judge: the page's own bot detectors (critical
# flags, a heuristic score of 0.8+), mouse models that disagree, or 25+ moves without spatial or temporal
# variation. Each is an anomaly, on any device.
CORE_ANOMALIES = ("CLIENT_AUTOMATION_SIGNAL", "HIGH_CLIENT_HEURISTIC_SCORE", "MODEL_DISAGREEMENT",
                  "DEGENERATE_TRAJECTORY")
# A page token that does not check out is an anomaly at once. A missing one only on a page shown 5 s or more:
# the collector waits 2 s for the token and an unload beacon does not wait, so a short visit on a slow phone
# network often ends before it arrives (50 of the replay's 63 undecided phones without one were shown under
# 5 s; Fingerprint flagged none of the 19 it had checked).
TOKEN_GRACE_MS = 5_000
_BAD_TOKEN = ("unknown", "mismatched", "reused")
_MODEL_UNAVAILABLE = "Decision deferred: required model unavailable"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def visible_ms(breakdown: dict, payload: dict = None):
    """How long the page was shown (collector 1.16+), else how old it was."""
    presence = breakdown.get("presence") if isinstance(breakdown.get("presence"), dict) else {}
    shown = _number(presence.get("visible_ms"))
    if shown is not None:
        return shown
    mouse = (payload or {}).get("mouse") if isinstance((payload or {}).get("mouse"), dict) else {}
    return _number(mouse.get("pageAgeMs"))


def input_anomalies(breakdown: dict, payload: dict = None, *, stored: bool = False) -> list:
    """The anomalies of a session the detector could not judge (see the module docstring). ``stored``: a
    session read back from storage, where an older collector may simply not have reported page presence."""
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    mobile = breakdown.get("mobile_human") if isinstance(breakdown.get("mobile_human"), dict) else {}
    presence = breakdown.get("presence") if isinstance(breakdown.get("presence"), dict) else {}
    evidence = breakdown.get("automation_evidence") if isinstance(breakdown.get("automation_evidence"), dict) else {}
    found = [code for code in CORE_ANOMALIES if code in (breakdown.get("suspect_reason_codes") or [])]
    # Automation the profile diagnostics saw (a HeadlessChrome brand or user agent in the page or its worker,
    # a worker's navigator.webdriver): not released as a BOT rule, but no person shows it.
    if (breakdown.get("profile_shadow") or {}).get("shadow_verdict") == "BOT":
        found.append("PROFILE_AUTOMATION")
    shown = visible_ms(breakdown, payload)
    # Collectors since 1.16 always report page presence, and earlier ones the page's age: without either,
    # nothing says a page was ever shown (a bare telemetry post).
    if shown is None and not presence.get("reported") and not stored:
        found.append("NO_PAGE_PRESENCE")
    if "UNVERIFIED_PAGE_LOAD" in (mobile.get("missing") or []):
        headers = (payload or {}).get("_server_headers") if isinstance((payload or {}).get("_server_headers"), dict) else {}
        if (headers.get("page_view") in _BAD_TOKEN or (shown is not None and shown >= TOKEN_GRACE_MS)
                or (shown is None and not stored)):
            found.append("UNVERIFIED_PAGE_LOAD")
    if mobile.get("device") or breakdown.get("unsupported_mobile"):
        if "SENSORS_UNAVAILABLE" in (presence.get("research_flags") or []):
            found.append("SENSORS_UNAVAILABLE")
        return found
    if "NOT_VIEWED" in (presence.get("codes") or []):
        found.append("NOT_VIEWED")
    if evidence.get("families"):
        found.append("ENVIRONMENT_FAMILY")
    if shown is not None and shown >= DESKTOP_IDLE_MS and (_number(breakdown.get("mouse_points")) or 0) < DESKTOP_IDLE_MAX_MOVES:
        found.append("DESKTOP_IDLE")
    return found


def apply_three_verdicts(result: dict, payload: dict = None) -> dict:
    """An insufficient-evidence result becomes SUSPECT (an anomaly) or HUMAN (no bot evidence); any other
    result is returned as it is."""
    if not isinstance(result, dict) or result.get("decision_state") != "INSUFFICIENT_EVIDENCE":
        return result
    if any(str(reason).startswith(_MODEL_UNAVAILABLE) for reason in result.get("reasons") or []):
        return result
    breakdown = dict(result.get("breakdown") or {})
    anomalies = input_anomalies(breakdown, payload)
    suspect = bool(anomalies)
    breakdown["three_verdicts"] = {
        "version": THREE_VERDICTS_VERSION, "from_state": "INSUFFICIENT_EVIDENCE",
        "from_basis": breakdown.get("decision_basis"),
        "from_codes": list(breakdown.get("suspect_reason_codes") or []), "anomalies": anomalies,
    }
    breakdown["decision_basis"] = INPUT_ANOMALY_BASIS if suspect else NO_BOT_EVIDENCE_BASIS
    breakdown["decision_deferred"] = False
    breakdown["verdict_locked"] = False
    breakdown["suspect_reason_codes"] = anomalies if suspect else []
    reason = (
        "Too little input to judge the behaviour, and an anomaly: "
        + ", ".join(anomalies).lower().replace("_", " ")
        if suspect else
        "Too little input to judge the behaviour and no bot evidence: let through as a HUMAN of the lowest "
        "confidence (three verdicts, policy 48)"
    )
    return {**result, "verdict": "SUSPECT" if suspect else "HUMAN", "is_bot": False, "decision_state": "FINAL",
            "reasons": [reason, *(result.get("reasons") or [])], "breakdown": breakdown}
