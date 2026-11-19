"""Policy 52 (ua_hints_anchor_v1): a desktop user agent its own Client Hints contradict, and an environment anchor,
convict. Also the research capture of the gateway's TLS ClientHello summary."""

import copy
import hashlib
import json

from api_service.main import tls_client
from api_service.rejudge import judge
from core_ml.features.client_forgery import UA_HINTS_ANCHOR_RULE, ua_hints_anchor_fires
from core_ml.release_cases import (
    CLIENT_FORGERY_CASES,
    CLIENT_FORGERY_RULE_GATE,
    CLIENT_FORGERY_RULE_GATE_V51,
)

WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 "
           "Mobile Safari/537.36")


def test_rule_conditions():
    hints_gpu = {"families": {"CLIENT_HINTS": ["signals.uaHintsMismatch"], "GPU": ["worker.rendererMismatch"]}}
    assert ua_hints_anchor_fires(hints_gpu, desktop=True)
    assert not ua_hints_anchor_fires(hints_gpu, desktop=False), "phones keep their own rules"
    assert not ua_hints_anchor_fires({"families": {"CLIENT_HINTS": ["signals.uaHintsMismatch"]}}, desktop=True)
    switcher = {"families": {"CLIENT_HINTS": ["signals.uaHintsMismatch"], "NATIVE_PATCH": ["signals.navigatorGetterPatched"],
                             "CONTEXT": ["worker.uaMismatch"]}}
    assert not ua_hints_anchor_fires(switcher, desktop=True), "a user-agent switcher has no anchor family"
    assert not ua_hints_anchor_fires({"families": {"GPU": ["worker.rendererMismatch"]}}, desktop=True)
    server = {"families": {"CLIENT_HINTS": ["server.http_ua_mismatch"], "PERMISSION": ["permission"]}}
    assert ua_hints_anchor_fires(server, desktop=True)
    declared_once = {"families": {"CLIENT_HINTS": ["server.http_ua_mismatch"], "HEADLESS_ENV": ["detectors.headlessUa"]}}
    assert not ua_hints_anchor_fires(declared_once, desktop=True), "HeadlessChrome in one UA is one lie, not two"
    renderer = {"families": {"CLIENT_HINTS": ["server.http_ua_mismatch"],
                             "HEADLESS_ENV": ["detectors.headlessUa", "signals.headlessScreen"]}}
    assert ua_hints_anchor_fires(renderer, desktop=True)


def test_fixtures_and_frozen_gate():
    from api_service.main import ensemble_detector

    ours = CLIENT_FORGERY_CASES[54:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("BOT", "FINAL", "forged_browser"), ("BOT", "FINAL", "forged_browser"),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None), ("HUMAN", "FINAL", None), ("SUSPECT", "FINAL", None)]
    for verdict, state, basis, payload in ours:
        result = ensemble_detector.predict(copy.deepcopy(payload))
        assert (result["verdict"], result["decision_state"]) == (verdict, state)
        if verdict == "BOT":
            assert result["breakdown"]["automation_rule"] == UA_HINTS_ANCHOR_RULE
            assert result["breakdown"]["verdict_locked"] is True
            assert any("Client Hints" in reason for reason in result["reasons"])
    assert CLIENT_FORGERY_RULE_GATE_V51["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(CLIENT_FORGERY_CASES[:54], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "ua_hints_anchor_v1" in CLIENT_FORGERY_RULE_GATE["rules"] and CLIENT_FORGERY_RULE_GATE["passed"] == 59


def stored(ua, families, verdict="SUSPECT"):
    return {"verdict": verdict, "decision_state": "FINAL", "fingerprint": {"userAgent": ua},
            "breakdown": {"automation_evidence": {"families": families}, "client_forgery": {"codes": []},
                          "touch": {}}}


def test_rejudge_convicts_stored_desktops_only():
    families = {"CLIENT_HINTS": ["signals.uaHintsMismatch"], "GPU": ["worker.rendererMismatch"]}
    rule, found, _ = judge(stored(WINDOWS, families))
    assert rule == UA_HINTS_ANCHOR_RULE and found == ["CLIENT_HINTS", "GPU"]
    assert judge(stored(ANDROID, families)) is None or judge(stored(ANDROID, families))[0] != UA_HINTS_ANCHOR_RULE
    assert judge(stored(WINDOWS, {"CLIENT_HINTS": ["signals.uaHintsMismatch"]})) is None


def test_tls_client_summary():
    headers = {"x-dc-tls-ciphers": "0x2a2a:TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:0x1a1a",
               "x-dc-tls-curves": "0x9a9a:X25519MLKEM768:X25519:prime256v1", "x-dc-tls-proto": "TLSv1.3"}
    summary = tls_client(headers)
    assert summary["ciphers"] == "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384", "GREASE removed"
    assert summary["curves"] == "X25519MLKEM768:X25519:prime256v1" and summary["protocol"] == "TLSv1.3"
    shuffled_grease = {**headers, "x-dc-tls-ciphers": "0x5a5a:TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384"}
    assert tls_client(shuffled_grease)["signature"] == summary["signature"], "GREASE does not change the signature"
    assert tls_client({}) is None and tls_client({"x-dc-tls-ciphers": "-"}) is None


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION

    assert DECISION_POLICY_VERSION == "52"
