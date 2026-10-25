from copy import deepcopy

import pytest

from core_ml.dataset.field_captures import BotCapture
from core_ml.dataset.loader import RealMouseSession
from core_ml.evaluate_profile_candidate import evaluate_candidate
from tests.test_profile_candidate import detector, payload


def capture(identity="s1", label="BOT"):
    data = payload()
    data["sessionId"] = identity
    probe = deepcopy(data)
    probe["botd"]["profile"]["worker"] = {}
    return BotCapture(identity, "headless-hints", (data, data, probe), label=label,
                      participant_id="person1" if label == "HUMAN" else None)


def test_integrated_evaluation_excludes_probe_and_reports_real_transitions():
    report = evaluate_candidate(detector(), [capture()])
    group = report["groups"][0]
    assert group["runs"] == 1
    assert group["sent_snapshots"] == group["changed_snapshots"] == 2
    assert group["transitions"] == {"HUMAN->BOT": 2}
    assert group["candidate_final"] == {"BOT": 1}
    assert group["rule_hits"] == 2
    assert report["release_approved"] is False


def test_integrated_evaluation_reports_human_false_positives_not_just_bot_recall():
    report = evaluate_candidate(detector(), [capture(label="HUMAN")])
    assert report["human_browser_runs"] == report["human_participants"] == 1
    group = report["groups"][0]
    assert group["label"] == "HUMAN"
    assert group["baseline_ever_bot"] == 0
    assert group["candidate_ever_bot"] == 1


@pytest.mark.parametrize("duplicate", ["id", "session"])
def test_integrated_evaluation_rejects_overlapping_inputs(duplicate):
    other = capture("s2")
    if duplicate == "id":
        other = BotCapture("s1", other.family, other.snapshots)
    else:
        for row in other.snapshots:
            row["sessionId"] = "s1"
    with pytest.raises(ValueError, match="unique"):
        evaluate_candidate(detector(), [capture(), other])


def test_mouse_dataset_is_separate_from_browser_human_controls():
    controls = [RealMouseSession(payload()["mouse"]["records"], 0, "dataset1",
                                 "phase2", "test", "humans_and_advanced_bots")]
    report = evaluate_candidate(detector(), [capture()], controls)
    assert report["human_browser_runs"] == 0
    group = next(g for g in report["groups"] if g["source"] == "mouse_only")
    assert group["changed_runs"] == group["profile_covered_snapshots"] == 0
    assert group["candidate_final"] == group["baseline_final"] == {"HUMAN": 1}


def test_integrated_evaluation_rejects_empty_capture_set():
    with pytest.raises(ValueError, match="At least one"):
        evaluate_candidate(detector(), [])
