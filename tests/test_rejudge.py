"""Policies 30-32 applied to stored sessions: only ever upgraded to BOT, the old verdict kept."""

import mongomock

from api_service.rejudge import judge, rejudge

WEBVIEW = ("Mozilla/5.0 (Linux; Android 11; MiTV-MOOQ3 Build/RTM4.220307.164; wv) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Version/4.0 Chrome/156.0.8078.47 Mobile Safari/537.36")
SAFARI9 = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/601.7.7 (KHTML, like Gecko) "
           "Version/9.1.2 Safari/601.7.7")
ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/150.0.0.0 Mobile Safari/537.36")
IPAD = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/27.0.1 Safari/605.1.15")
PATCHED = {"NATIVE_PATCH": ["signals.webdriverDeleted", "signals.webdriverPatched"]}


def session(sid, ua, *, verdict="SUSPECT", state="FINAL", families=None, codes=None, touch=None, **fingerprint):
    return {"_id": sid, "sessionId": sid, "verdict": verdict, "decision_state": state, "policy_version": "29",
            "reasons": ["old reason"], "fingerprint": {"userAgent": ua, **fingerprint},
            "breakdown": {"client_forgery": {"codes": codes or [], "contradictions": codes or []},
                          "automation_evidence": {"families": families or {}},
                          "touch": touch or {"gestures": 0, "research_flags": []}}}


def test_rejudge_upgrades_what_the_new_rules_convict_and_nothing_else():
    db = mongomock.MongoClient()["rejudge"]
    db["detection_results"].insert_many([
        session("webview", WEBVIEW, families=PATCHED, codes=["WEBDRIVER_TAMPERED"], webglRenderer="Mali-G52"),
        session("mac", SAFARI9, state="INSUFFICIENT_EVIDENCE", families={"NATIVE_PATCH": ["signals.webdriverPatched"]},
                codes=["WEBDRIVER_TAMPERED"], deviceMemory=8, platform="MacIntel"),
        session("spoof", ANDROID, state="INSUFFICIENT_EVIDENCE", platform="Linux armv8l",
                families={"CONTEXT": ["worker.platformMismatch"], "GPU": ["worker.rendererMismatch"]}),
        session("ipad", IPAD, platform="MacIntel", maxTouchPoints=5,
                touch={"gestures": 6, "research_flags": ["SYNTHETIC_CONTACT"]}),
        # Not convicted: one contradiction only, a person, an older WebKit iPad.
        session("alone", ANDROID, codes=["WEBDRIVER_TAMPERED"], families={"NATIVE_PATCH": ["signals.webdriverPatched"]}),
        session("human", ANDROID, verdict="HUMAN"),
        session("ipad16", IPAD.replace("27.0.1", "16.5"), platform="MacIntel", maxTouchPoints=5,
                touch={"gestures": 6, "research_flags": ["SYNTHETIC_CONTACT"]}),
        session("bot", ANDROID, verdict="BOT"),
    ])
    counted = rejudge(db)
    assert counted["convicted"] == 4 and counted["written"] == 0
    assert counted["by_previous_state"] == {"suspect": 2, "insufficient": 2}
    assert db["detection_results"].count_documents({"verdict": "BOT"}) == 1

    done = rejudge(db, apply=True)
    assert done["written"] == 4
    docs = {d["_id"]: d for d in db["detection_results"].find()}
    assert {sid for sid, d in docs.items() if d["verdict"] == "BOT"} == {"webview", "mac", "spoof", "ipad", "bot"}
    mac = docs["mac"]
    assert mac["decision_state"] == "FINAL" and mac["breakdown"]["decision_basis"] == "forged_browser"
    assert mac["breakdown"]["client_forgery"]["contradictions"] == ["UA_API_MISMATCH", "WEBDRIVER_TAMPERED"]
    assert mac["rejudged"]["from_state"] == "INSUFFICIENT_EVIDENCE" and mac["rejudged"]["from_policy"] == "29"
    assert mac["reasons"][0] == "old reason" and "stored analysis" in mac["reasons"][-1]
    assert docs["webview"]["breakdown"]["decision_basis"] == "webview_automation"
    assert docs["spoof"]["breakdown"]["client_forgery"]["contradictions"] == ["PLATFORM_SPOOFED", "ENVIRONMENT_EVIDENCE"]
    assert docs["ipad"]["breakdown"]["decision_basis"] == "synthetic_touch"
    assert "rejudged" not in docs["bot"] and docs["human"]["verdict"] == "HUMAN"
    # Running again changes nothing.
    assert rejudge(db, apply=True)["convicted"] == 0


def test_judge_reads_only_stored_fields():
    assert judge({}) is None
    assert judge(session("x", WEBVIEW)) is None
