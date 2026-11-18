"""Policy 45: a desktop user agent claiming Chrome 83 or older on a page that exposes
navigator.userAgentData (Chrome 84+) contradicts itself (ANACHRONISTIC_UA)."""

import copy
import hashlib
import json

from core_ml.features.client_forgery import (
    CHROME_UA_HINTS,
    forgery_codes,
    page_exposes_ua_hints,
)
from core_ml.release_cases import (
    CLIENT_FORGERY_CASES,
    CLIENT_FORGERY_RULE_GATE,
    CLIENT_FORGERY_RULE_GATE_V44,
)

WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.0.0 Safari/537.36"
HINTS = {"brands": [], "platform": "", "mobile": False}


def payload(ua, hints=True):
    body = {"fingerprint": {"userAgent": ua}, "botd": {}}
    if hints:
        body["botd"]["profile"] = {"main": {"clientHints": dict(HINTS), "clientHintsStatus": "ok"}}
    return body


def test_old_chrome_with_ua_hints_is_anachronistic():
    assert CHROME_UA_HINTS == 84
    for major in (58, 64, 70, 83):
        assert forgery_codes(payload(WIN.format(major)), {}, desktop=True) == ["ANACHRONISTIC_UA"], major


def test_what_is_not_anachronistic():
    assert forgery_codes(payload(WIN.format(84)), {}, desktop=True) == []
    assert forgery_codes(payload(WIN.format(109)), {}, desktop=True) == [], "Windows 7's last Chrome has the API"
    assert forgery_codes(payload(WIN.format(70), hints=False), {}, desktop=True) == [], "a genuine Chrome 70"
    assert forgery_codes(payload(WIN.format(70)), {}, desktop=False) == [], "judged on desktops only"
    android = "Mozilla/5.0 (Linux; Android 7.0; SM-G930F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0 Mobile Safari/537.36"
    assert forgery_codes(payload(android), {}, desktop=True) == [], "a phone user agent is never judged here"
    firefox = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0"
    assert forgery_codes(payload(firefox), {}, desktop=True) == []


def test_ua_hints_presence_reads_the_profile():
    assert page_exposes_ua_hints(payload(WIN.format(70)))
    assert not page_exposes_ua_hints(payload(WIN.format(70), hints=False))
    assert not page_exposes_ua_hints({"botd": {"profile": {"main": {"clientHints": None}}}})
    assert not page_exposes_ua_hints({"botd": "malformed"})


def test_fixtures():
    from api_service.main import ensemble_detector
    ours = CLIENT_FORGERY_CASES[50:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("BOT", "FINAL", "forged_browser"), ("SUSPECT", "FINAL", "client_forgery"),
        ("SUSPECT", "FINAL", "client_forgery"), ("SUSPECT", "FINAL", "client_forgery")]
    bot = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert bot["breakdown"]["automation_rule"] == "forged_browser_v1" and bot["breakdown"]["verdict_locked"] is True
    assert "ANACHRONISTIC_UA" in bot["breakdown"]["client_forgery"]["codes"]


def test_policy_44_gate_is_frozen_on_its_own_fixtures():
    first = CLIENT_FORGERY_CASES[:50]
    assert CLIENT_FORGERY_RULE_GATE_V44["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "anachronistic_ua_v1" in CLIENT_FORGERY_RULE_GATE["rules"]
    assert "anachronistic_ua_v1" not in CLIENT_FORGERY_RULE_GATE_V44["rules"]


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION == "45"
