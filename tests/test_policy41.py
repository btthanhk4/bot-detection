"""Policy 41: a mouse trajectory replayed from another session."""

import copy

import mongomock
import numpy as np
import pytest

from api_service import trajectory_store
from core_ml.features.trajectory_signature import (
    REPLAY_BOT_OVERLAP,
    REPLAY_SUSPECT_OVERLAP,
    replay_overlap,
    signatures,
)

WINDOWS_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/157.0.0.0 Safari/537.36")


def wander(seed, n=2500):
    """A meandering hand: a random walk of heading with pauses, sampled every ~8 ms."""
    rng = np.random.default_rng(seed)
    t, x, y, heading, out = 0.0, 0.5, 0.5, 0.0, []
    for i in range(n):
        if i % 180 == 179:
            t += 400  # a pause: the hand stops
        heading += rng.normal(0, 0.35)
        speed = 0.004 * (1 + np.sin(i / 15))
        x = min(0.97, max(0.03, x + np.cos(heading) * speed))
        y = min(0.97, max(0.03, y + np.sin(heading) * speed))
        t += 8 + rng.random()
        out.append({"time": round(t, 1), "type": "move", "source": "mouse", "x": round(x, 5), "y": round(y, 5)})
    return out


def exports(moves, first=300):
    """The collector 1.17 snapshots of a trail: 300 new moves and 100 of context each."""
    cut, prev = first, 0
    while prev < len(moves):
        yield moves[max(0, prev - 100):cut]
        prev, cut = cut, cut + 300


def test_signatures_ignore_speed_position_and_touch():
    trail = wander(1)
    base = signatures(trail)
    assert len(base) > 20
    faster = [{**r, "time": r["time"] / 1.5} for r in trail]
    assert len(signatures(faster) & base) >= len(base) // 2, "speed barely matters (only where the hand stops)"
    moved = [{**r, "x": r["x"] * 0.9 + 0.02} for r in trail]
    assert len(signatures(moved) & base) > 0
    assert signatures([{**r, "source": "touch"} for r in trail]) == set()
    assert signatures([{"type": "move", "x": "a", "y": 1, "time": 0}, None, 5]) == set()


def test_different_people_do_not_share_signatures():
    a, b = signatures(wander(1)), signatures(wander(2))
    assert len(a & b) < REPLAY_SUSPECT_OVERLAP


def test_replay_overlap_header_is_validated():
    for bad in (True, -1, 1.5, "9", None):
        assert replay_overlap({"_server_headers": {"replay_overlap": bad}}) is None
    assert replay_overlap({"_server_headers": {"replay_overlap": 9}}) == 9
    assert replay_overlap({}) is None


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True)["bot_detection"]


def _payload(records, page):
    return {"collector": {"pageInstanceId": page}, "mouse": {"records": records}}


def _session(db, trail, session, page, first=300):
    overlap = 0
    for export in exports(trail, first):
        overlap = trajectory_store.replay_overlap(db, _payload(export, page), session)
    return overlap


def test_store_finds_a_replay_cut_at_other_points(db):
    trail = wander(3)
    assert _session(db, trail, "original", "page-a") == 0
    assert _session(db, wander(4), "someone-else", "page-b") < REPLAY_SUSPECT_OVERLAP
    assert _session(db, trail, "replay", "page-c", first=217) >= REPLAY_BOT_OVERLAP


def test_same_page_under_a_new_session_id_is_not_a_replay(db):
    trail = wander(5)
    _session(db, trail, "before-rotation", "page-a")
    assert _session(db, trail, "after-rotation", "page-a", first=217) == 0


def test_store_failures_are_harmless():
    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("down")
    assert trajectory_store.replay_overlap(Broken(), _payload(wander(1)[:400], "p"), "s") is None
    assert trajectory_store.replay_overlap(None, _payload([], "p"), "s") is None


def _desktop(records, overlap):
    return {"_server_user_agent": WINDOWS_CHROME,
            "_server_headers": {"observed": True, "accept_language": True, "sec_ch_ua": "", "replay_overlap": overlap},
            "fingerprint": {"userAgent": WINDOWS_CHROME}, "botd": {"detectors": {}}, "mouse": {"records": records}}


def test_verdicts():
    from api_service.main import ensemble_detector

    records = wander(6)[-100:]
    clean = ensemble_detector.predict(_desktop(copy.deepcopy(records), 0))
    assert "REPLAYED_TRAJECTORY" not in clean["breakdown"]["desktop_risk"]["codes"]
    suspect = ensemble_detector.predict(_desktop(copy.deepcopy(records), REPLAY_SUSPECT_OVERLAP))
    assert suspect["verdict"] != "HUMAN"
    assert "REPLAYED_TRAJECTORY" in suspect["breakdown"]["desktop_risk"]["codes"]
    bot = ensemble_detector.predict(_desktop(copy.deepcopy(records), REPLAY_BOT_OVERLAP))
    assert (bot["verdict"], bot["breakdown"]["decision_basis"]) == ("BOT", "replayed_trajectory")
    assert bot["breakdown"]["verdict_locked"] is True
    short = ensemble_detector.predict(_desktop(copy.deepcopy(records[:12]), REPLAY_SUSPECT_OVERLAP))
    assert (short["verdict"], short["decision_state"]) == ("SUSPECT", "FINAL"), "evidence on a short session too"
