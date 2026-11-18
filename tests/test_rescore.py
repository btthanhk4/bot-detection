"""rescore: stored sessions scored again from their raw snapshots with the running code, under the API's storage
rules; only changed verdicts are written, with the previous one kept."""

import json
from datetime import datetime, timedelta, timezone

import mongomock

from api_service.rejudge import RESCORE_VERSION, rescore

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=5)

RESULTS = {
    "bot": {"verdict": "BOT", "decision_state": "FINAL", "policy_version": "49", "bot_probability": 0.99,
            "reasons": ["forged"], "breakdown": {"decision_basis": "forged_browser", "verdict_locked": True}},
    "model_bot": {"verdict": "BOT", "decision_state": "FINAL", "policy_version": "49", "bot_probability": 0.97,
                  "reasons": ["mouse"], "breakdown": {"decision_basis": "ensemble", "verdict_locked": False}},
    "suspect": {"verdict": "SUSPECT", "decision_state": "FINAL", "policy_version": "49", "reasons": ["risk"],
                "breakdown": {"decision_basis": "mobile_risk"}},
    "human": {"verdict": "HUMAN", "decision_state": "FINAL", "policy_version": "49", "reasons": ["touch"],
              "breakdown": {"decision_basis": "mobile_clean_environment"}},
    "insufficient": {"verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE", "policy_version": "49",
                     "reasons": ["too little"], "breakdown": {
                         "decision_basis": "insufficient_evidence", "unsupported_mobile": True,
                         "mobile_human": {"device": "android", "missing": ["FEW_GESTURES"]},
                         "presence": {"visible_ms": 8000, "codes": [], "research_flags": []},
                         "automation_evidence": {"families": {}}}},
}


class Detector:
    def predict(self, payload):
        result = json.loads(json.dumps(RESULTS[payload["marker"]]))
        result["_session_mouse_new"] = {"chunks": {payload["marker"]: 1}}
        return result


def session(db, sid, verdict, markers, *, state="FINAL", updated=OLD, collection="telemetry_captures"):
    db["detection_results"].insert_one({"_id": sid, "sessionId": sid, "verdict": verdict, "decision_state": state,
                                        "policy_version": "41", "updated_at": updated, "reasons": ["old"]})
    for i, marker in enumerate(markers):
        db[collection].insert_one({"_id": f"{sid}-{i}", "sessionId": sid, "received_at": 1000 + i,
                                   "payload_json": json.dumps({"marker": marker}), "server_headers": {}})


def test_rescore_follows_the_storage_rules_and_writes_only_changes():
    db = mongomock.MongoClient()["rescore"]
    session(db, "conviction", "SUSPECT", ["suspect", "bot"])
    session(db, "evidence-stays", "HUMAN", ["suspect", "insufficient"])
    session(db, "same", "HUMAN", ["insufficient"])
    session(db, "live", "SUSPECT", ["bot"], updated=NOW - timedelta(minutes=5))
    session(db, "no-raw", "HUMAN", [])
    session(db, "labelled", "SUSPECT", ["bot"], collection="labeled_captures")
    session(db, "locked", "HUMAN", ["bot", "human"])
    session(db, "unlocked", "BOT", ["model_bot", "human"])
    session(db, "old-insufficient", "SUSPECT", ["insufficient"], state="INSUFFICIENT_EVIDENCE")

    counted = rescore(db, detector=Detector(), now=NOW, model_bundle_id="bundle49")
    assert counted["changes"] == {"SUSPECT -> BOT": 2, "HUMAN -> SUSPECT": 1, "HUMAN -> BOT": 1, "BOT -> HUMAN": 1,
                                  "INSUFFICIENT -> HUMAN": 1}
    assert (counted["scored"], counted["without_raw"], counted["left_to_live_traffic"], counted["written"]) == (
        7, 1, 1, 0)
    assert db["detection_results"].find_one({"_id": "conviction"})["verdict"] == "SUSPECT", "a dry run writes nothing"

    done = rescore(db, detector=Detector(), apply=True, now=NOW, model_bundle_id="bundle49")
    assert done["written"] == 6
    docs = {d["_id"]: d for d in db["detection_results"].find()}
    conviction = docs["conviction"]
    assert (conviction["verdict"], conviction["is_bot"], conviction["verdict_locked"], conviction["policy_version"],
            conviction["model_bundle_id"]) == ("BOT", True, True, "49", "bundle49")
    provenance = dict(conviction["rejudged"])
    assert provenance.pop("at").replace(tzinfo=timezone.utc) == NOW
    assert provenance == {"from_verdict": "SUSPECT", "from_state": "FINAL", "from_policy": "41",
                          "rule": RESCORE_VERSION, "policy": provenance["policy"]}
    assert docs["evidence-stays"]["verdict"] == "SUSPECT", "a mapped verdict never replaces an evidence-made one"
    assert docs["locked"]["verdict"] == "BOT", "a locked BOT stays"
    assert docs["unlocked"]["verdict"] == "HUMAN", "one mouse-model BOT is not locked"
    assert docs["old-insufficient"]["verdict"] == "HUMAN" and docs["old-insufficient"]["verdict_mapped"] is True
    assert docs["live"]["verdict"] == "SUSPECT" and "rejudged" not in docs["live"]
    assert docs["same"]["verdict"] == "HUMAN" and "rejudged" not in docs["same"]
    assert rescore(db, detector=Detector(), now=NOW)["changed"] == 0, "a second run finds nothing to change"
