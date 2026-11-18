"""Policy 40: the mouse models judge every window of a session, not only its last two seconds."""

import copy

import numpy as np
import pytest

from core_ml.features.session_mouse import (
    MAX_SESSION_CHUNKS,
    aggregate,
    collector_window,
    export_frame,
    is_extended_export,
    prior_evidence,
    session_pieces,
)
from core_ml.models.ensemble import EnsembleBotDetector

WINDOWS_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/157.0.0.0 Safari/537.36")


def trail(n_human=300, n_fast=0, fast_gap=2.0, seed=5):
    """A wandering desktop path: ``n_human`` moves every ~16.7 ms, then ``n_fast`` moves ``fast_gap`` ms apart."""
    rng = np.random.default_rng(seed)
    t, x, y, records = 0.0, 0.2, 0.3, []
    for index in range(n_human + n_fast):
        t += (16.7 + float(rng.uniform(-0.5, 0.5))) if index < n_human else fast_gap
        x = min(0.95, max(0.05, x + float(rng.normal(0.003, 0.002))))
        y = min(0.95, max(0.05, y + float(rng.normal(0.001, 0.002))))
        records.append({"time": round(t), "type": "move", "source": "mouse", "x": round(x, 5), "y": round(y, 5)})
    return records


def payload(records, move_base=None, frame=0, page="page-1"):
    mouse = {"records": records, "coordinateFrame": {"id": frame}}
    if move_base is not None:
        mouse.update(moveBase=move_base, frameMoves=move_base + sum(r["type"] == "move" for r in records))
    return {"sessionId": "s", "collector": {"pageInstanceId": page}, "_server_user_agent": WINDOWS_CHROME,
            "_server_headers": {"observed": True, "accept_language": True, "sec_ch_ua": ""},
            "fingerprint": {"userAgent": WINDOWS_CHROME}, "botd": {"detectors": {}}, "mouse": mouse}


class ChunkLSTM:
    """Bot-like (0.95) for chunks of moves under 6 ms apart, human-like (0.05) otherwise."""

    def predict_chunk_scores(self, tensor):
        return [0.95 if float(chunk[:, 7].mean()) < 0.006 else 0.05 for chunk in tensor]

    def predict_session_scores(self, tensor):
        scores = np.array(self.predict_chunk_scores(tensor))
        return float(scores.mean()), float(np.quantile(scores, 0.75))


class SpeedTabular:
    def __init__(self, bot_speed=None):
        self.bot_speed = bot_speed

    def predict_proba(self, vector):
        return 0.99 if self.bot_speed is not None and vector[-20] > self.bot_speed else 0.02


def detector(tabular=None):
    return EnsembleBotDetector(lstm_model=ChunkLSTM(), tabular_model=tabular or SpeedTabular())


# --- the session store keys and windows ---------------------------------------------------------

def test_export_frame_and_untrusted_fields():
    assert export_frame(payload(trail(30), move_base=7, frame=2))[:2] == (7, 2)
    for bad in (-1, True, 1.5, "3", None):
        p = payload(trail(30))
        p["mouse"]["moveBase"] = bad
        assert export_frame(p)[0] is None and not is_extended_export(p)
    assert export_frame({})[2] == "nopage"


def test_collector_window_is_what_collector_116_sent():
    records = trail(150)
    for index in range(0, 150, 5):
        records.insert(index, {"time": records[index]["time"], "type": "click", "source": "mouse",
                               "x": 0.5, "y": 0.5})
    window = collector_window(records)
    others = [r for r in records if r["type"] != "move"][-20:]
    moves = [r for r in records if r["type"] == "move"][-80:]
    assert len(window) == 100
    assert sorted(map(id, window)) == sorted(map(id, others + moves))


def test_overlapping_exports_share_keys():
    records = trail(400)
    first = session_pieces(payload(records[:250], move_base=0), records[:250])
    second = session_pieces(payload(records[150:], move_base=150), records[150:])
    first_chunks = {key for key, _ in first["chunks"]}
    second_chunks = {key for key, _ in second["chunks"]}
    overlap = first_chunks & second_chunks
    assert overlap, "the 100 moves of context are chunked under the same frame-global keys"
    for key in overlap:
        a = dict(first["chunks"])[key]
        b = dict(second["chunks"])[key]
        assert np.allclose(a, b), "the same moves give the same chunk"
    starts = sorted(int(key.rsplit("m", 1)[1]) for key in first_chunks | second_chunks)
    assert starts == list(range(0, 400 - 24, 12)), "together they cover the trail exactly once"
    windows = {key for key, _ in first["windows"]} | {key for key, _ in second["windows"]}
    assert {f"w{g}" for g in range(49, 400, 50)} <= {key.split(":")[-1] for key in windows}


def test_stored_pieces_are_not_rebuilt():
    records = trail(400)
    full = session_pieces(payload(records, move_base=0), records)
    known = {key for key, _ in full["chunks"][:10]} | {key for key, _ in full["windows"][:2]}
    rest = session_pieces(payload(records, move_base=0), records, known=known)
    assert len(rest["chunks"]) == len(full["chunks"]) - 10
    assert len(rest["windows"]) == len(full["windows"]) - 2
    assert not known & ({key for key, _ in rest["chunks"]} | {key for key, _ in rest["windows"]})


def test_windows_need_context_and_older_collectors_add_none():
    records = trail(160)
    pieces = session_pieces(payload(records[60:], move_base=60), records[60:])
    ends = sorted(int(key.rsplit("w", 1)[1]) for key, _ in pieces["windows"])
    assert ends == [159], "grid ends 99 and 149 lack 100 moves of context in this export; its last move has them"
    assert session_pieces(payload(records[-100:]), records[-100:]) == {"chunks": [], "windows": []}


def test_prior_evidence_is_bounded_and_clean():
    raw = {"chunks": {"a:0:m0": 0.2, "bad": "x", "b:0:m12": 1.5, "c:0:m24": float("nan"), 5: 0.1,
                      "k" * 80: 0.1, "d:0:m36": True},
           "windows": "not a map"}
    assert prior_evidence({"_session_mouse": raw}) == {"chunks": {"a:0:m0": 0.2}, "windows": {}}
    assert prior_evidence({}) == {"chunks": {}, "windows": {}}


def test_aggregate_counts_once_and_returns_only_new():
    prior = {"chunks": {"p:0:m0": 0.1, "p:0:m12": 0.1}, "windows": {"p:0:w49": 0.02}}
    result = aggregate(prior, {"p:0:m12": 0.1, "p:0:m24": 0.9}, {"p:0:w99": 0.04})
    assert result["chunks"] == 3 and result["windows"] == 2
    assert result["lstm_mean"] == pytest.approx((0.1 + 0.1 + 0.9) / 3)
    assert result["new"] == {"chunks": {"p:0:m24": 0.9}, "windows": {"p:0:w99": 0.04}}
    full = {"chunks": {f"p:0:m{12 * i}": 0.1 for i in range(MAX_SESSION_CHUNKS)}, "windows": {}}
    assert aggregate(full, {"p:0:m999999": 0.5}, {})["new"]["chunks"] == {}, "a full session stores no more"


# --- the decision ---------------------------------------------------------------------------------

def test_a_quick_last_stroke_no_longer_decides_the_session():
    records = trail(300, n_fast=60)
    legacy = detector().predict(payload(collector_window(records)))
    assert legacy["verdict"] == "SUSPECT"
    assert "MODEL_DISAGREEMENT" in legacy["breakdown"]["suspect_reason_codes"]
    whole = detector().predict(payload(records, move_base=0))
    assert whole["verdict"] == "HUMAN"
    report = whole["breakdown"]["session_mouse"]
    assert report["applied"] and report["chunks"] >= 12 and report["windows"] >= 2
    assert report["snapshot"]["lstm_tail"] == pytest.approx(0.95)
    assert whole["_session_mouse_new"]["chunks"], "the API stores what this snapshot added"


def test_session_evidence_accumulates_across_snapshots():
    records = trail(300, n_fast=60)
    first = detector().predict(payload(records[:200], move_base=0))
    prior = {"chunks": dict(first["_session_mouse_new"]["chunks"]),
             "windows": dict(first["_session_mouse_new"]["windows"])}
    later = payload(records[100:], move_base=100)
    later["_session_mouse"] = prior
    result = detector().predict(later)
    assert result["verdict"] == "HUMAN"
    assert result["breakdown"]["session_mouse"]["chunks"] == (360 - 25) // 12 + 1
    resent = copy.deepcopy(later)
    resent["_session_mouse"] = {
        "chunks": {**prior["chunks"], **result["_session_mouse_new"]["chunks"]},
        "windows": {**prior["windows"], **result["_session_mouse_new"]["windows"]}}
    again = detector().predict(resent)
    assert again["_session_mouse_new"] == {"chunks": {}, "windows": {}}, "a resent snapshot adds nothing"
    assert again["breakdown"]["session_mouse"]["chunks"] == result["breakdown"]["session_mouse"]["chunks"]


def test_bot_evidence_of_one_snapshot_still_counts():
    records = trail(300, n_fast=110)
    result = detector(SpeedTabular(bot_speed=0.8)).predict(payload(records, move_base=0))
    assert result["verdict"] == "BOT", "a BOT window is not averaged away (two of them lock the session)"
    assert result["breakdown"]["session_mouse"]["applied"] is False


def test_an_inert_session_is_not_made_human_by_the_session():
    # A session that is bot-like all along stays so as a session.
    records = trail(0, n_fast=400)
    result = detector().predict(payload(records, move_base=0))
    assert result["verdict"] != "HUMAN"


def test_old_collector_single_snapshot_is_exactly_policy_39():
    from api_service.main import ensemble_detector
    records = trail(90)
    plain = ensemble_detector.predict(payload(records))
    marked = payload(records)
    marked["_session_mouse"] = None
    live = ensemble_detector.predict(marked)
    for key in ("verdict", "decision_state", "bot_probability"):
        assert live[key] == plain[key]
    assert live["breakdown"]["behavioral_lstm_score"] == plain["breakdown"]["behavioral_lstm_score"]
    assert live["breakdown"]["session_mouse"]["applied"] is False
    assert plain["breakdown"]["session_mouse"] is None and plain["_session_mouse_new"] is None


def test_extended_export_keeps_per_snapshot_rules_on_the_trained_window():
    from api_service.main import ensemble_detector
    records = trail(400)
    result = ensemble_detector.predict(payload(records, move_base=0))
    assert result["breakdown"]["mouse_points"] == 100, "rules read the 100-record window"
    assert result["breakdown"]["records_received"] == 100
    assert result["breakdown"]["session_mouse"]["chunks"] == (400 - 25) // 12 + 1


def test_session_store_round_trip():
    import mongomock

    from api_service import session_mouse_store as store

    db = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    store.ensure_indexes(db)
    assert store.load(db, "s") is None
    assert store.save(db, "s", {"chunks": {"p:0:m0": 0.25, "bad.key": 0.5, "p:0:m12": 2.0}, "windows": {}})
    assert store.save(db, "s", {"chunks": {"p:0:m24": 0.75}, "windows": {"p:0:w49": 0.1}})
    assert store.load(db, "s") == {"chunks": {"p:0:m0": 0.25, "p:0:m24": 0.75}, "windows": {"p:0:w49": 0.1}}
    assert not store.save(db, "s", {"chunks": {}, "windows": {}})

    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("down")
    assert store.load(Broken(), "s") is None
    assert store.save(Broken(), "s", {"chunks": {"p:0:m0": 0.1}}) is False
    assert store.has_mouse_moves({"mouse": {"records": [{"type": "move", "source": "mouse"}]}})
    assert not store.has_mouse_moves({"mouse": {"records": [{"type": "move", "source": "touch"}]}})


def test_api_passes_session_evidence_and_stores_it(monkeypatch):
    import mongomock
    from fastapi.testclient import (
        TestClient,  # noqa: F401  (the app imports cleanly with it)
    )

    from api_service import database, main

    db = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    monkeypatch.setattr(database, "get_db", lambda: db)
    records = trail(300)
    data = payload(records, move_base=0)
    data["sessionId"] = "sess-api"
    assert main._session_mouse_prior(data) is None
    result = main.ensemble_detector.predict({**data, "_session_mouse": main._session_mouse_prior(data)})
    main._session_mouse_save("sess-api", result["_session_mouse_new"])
    stored = main._session_mouse_prior(data)
    assert len(stored["chunks"]) == result["breakdown"]["session_mouse"]["chunks"]
    phone = {"sessionId": "p", "mouse": {"records": [{"type": "move", "source": "touch", "time": 1, "x": 0, "y": 0}]}}
    assert main._session_mouse_prior(phone) is None


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("40", "41", "42", "43", "44", "45", "46", "47", "48")
