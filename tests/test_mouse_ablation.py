from pathlib import Path

import numpy as np
import pytest
from xgboost import XGBClassifier

from core_ml.experiments.mouse_ablation import (
    FEATURE_NAMES, audit_partitions, evaluate_runs, generator_family,
    make_run, run_experiment, training_matrix,
)


def window(variant=0):
    return [{"time": i * 16, "x": i / (100 + variant), "y": 0.2 + (i % 3) / 1000,
             "type": "move"} for i in range(30)]


def run(identity, label=0, variants=(0,), **kwargs):
    return make_run(identity, label, kwargs.get("family", "phase2"), kwargs.get("source", "dataset"),
                    kwargs.get("split", "train"), [window(v) for v in variants])


@pytest.mark.parametrize("variant", ["fixed", "jitter"])
@pytest.mark.parametrize("family", ["circular", "heavy-wander", "scrub-hover"])
def test_generator_group_keeps_timing_variants_together(family, variant):
    assert generator_family(f"stealth-{family}-{variant}-insecure-http") == family


def test_unknown_family_cannot_silently_become_an_independent_holdout():
    with pytest.raises(ValueError, match="Unknown generator"):
        generator_family("new-tool-seed1")


def test_feature_contract_and_duplicate_windows():
    item = run("r", variants=(0, 0, 1))
    assert len(FEATURE_NAMES) == 25
    assert item.vectors.shape == (2, 25)
    assert len(item.signatures) == 2
    assert np.isfinite(item.vectors[:, :20]).all()


def test_missing_local_evidence_remains_nan_not_zero():
    records = window()
    for i, record in enumerate(records):
        record["time"] = i * 1000
    item = make_run("r", 0, "phase2", "dataset", "train", [records])
    assert item.vectors.shape == (1, 25)
    assert np.isnan(item.vectors[0, 20:]).all()


def test_touch_and_short_windows_do_not_become_mouse_training_rows():
    touch = window()
    touch[2]["source"] = "touch"
    item = make_run("r", 0, "phase2", "dataset", "train", [touch, window()[:12]])
    assert item.vectors.shape == (0, 25)
    assert item.excluded_windows == 2


def test_class_and_session_weights_do_not_reward_long_sessions():
    runs = [run("h1", variants=(0,)), run("h2", variants=(1, 2, 3)),
            run("b1", 1, variants=(4, 5))]
    x, y, weights = training_matrix(runs, 25)
    assert x.shape == (6, 25)
    assert weights.mean() == pytest.approx(1)
    assert weights[y == 0].sum() == pytest.approx(weights[y == 1].sum())
    assert weights[0] == pytest.approx(weights[1:4].sum())


def test_training_requires_both_independent_labels():
    with pytest.raises(ValueError, match="both labels"):
        training_matrix([run("r")], 20)


def test_audit_rejects_duplicate_session_identity():
    with pytest.raises(ValueError, match="Session overlap"):
        audit_partitions({"train": [run("r")], "test": [run("r", variants=(3,))]})


def test_audit_rejects_duplicate_windows_even_with_different_clock_origins():
    records = window()
    for record in records:
        record["time"] += 9999
    shifted = make_run("b", 0, "phase2", "dataset", "test", [records])
    with pytest.raises(ValueError, match="Window leakage"):
        audit_partitions({"train": [run("a")], "test": [shifted]})


def test_audit_rejects_conflicting_labels_even_within_training():
    with pytest.raises(ValueError, match="conflicting"):
        audit_partitions({"train": [run("a"), run("b", 1)]})


def test_audit_digest_is_deterministic():
    a, b = run("a"), run("b", 1, variants=(2,))
    assert audit_partitions({"train": [a, b]}) == audit_partitions({"train": [b, a]})


def test_evaluation_counts_transient_errors_and_final_outcome():
    result = evaluate_runs([run("r", variants=(0, 1))], lambda _: np.array([0.1, 0.99]))[0]
    assert result["runs"] == 1
    assert result["final"] == {"BOT": 1}
    assert result["ever_human"] == result["ever_bot"] == 1
    assert result["eligible_windows"] == 2


@pytest.mark.parametrize("invalid", [[np.nan], [np.inf], [-1.0], [1.1], [], [[0.5]]])
def test_evaluation_rejects_invalid_model_output(invalid):
    with pytest.raises(ValueError, match="invalid probabilities"):
        evaluate_runs([run("r")], lambda _: np.asarray(invalid))


def test_empty_coverage_cannot_be_counted_as_human():
    item = make_run("r", 0, "phase2", "dataset", "test", [])

    def forbidden(_):
        raise AssertionError("No inference without eligible windows")

    result = evaluate_runs([item], forbidden)[0]
    assert result["final"] == {"SUSPECT": 1}
    assert result["no_eligible_window_runs"] == 1
    assert result["ever_human"] == 0


def test_experiment_cannot_save_into_product_repo():
    with pytest.raises(ValueError, match="outside"):
        run_experiment([], [], None, Path(__file__).resolve().parents[1] / "core_ml/weights")


def test_full_ablation_holds_out_generator_family_and_persists_only_candidates(tmp_path):
    real = [run(f"{split}-{label}", label, variants=(index * 2 + label,), split=split)
            for index, split in enumerate(("train", "val", "test")) for label in (0, 1)]
    field = [run(f"field-{family}", 1, variants=(10 + index,), family=family, source="field")
             for index, family in enumerate(("circular", "heavy-wander", "scrub-hover"))]
    destination = tmp_path / "candidate"
    report = run_experiment(real, field, lambda x: np.full(len(x), 0.5), destination)
    assert report["release_approved"] is False
    assert len(report["folds"]) == len(list(destination.glob("*.ubj"))) / 3 == 3
    for fold in report["folds"]:
        assert fold["heldout_family"] not in fold["split_counts"]["train"]["field_families"]
        assert fold["split_counts"]["test"]["field_families"] == [fold["heldout_family"]]
        assert len(fold["arms"]) == 4
        restored = XGBClassifier()
        restored.load_model(destination / f"{fold['heldout_family']}-refit_with_field_local.ubj")
        test_runs = [r for r in real if r.split == "test"] + [
            r for r in field if r.family == fold["heldout_family"]
        ]
        replay = evaluate_runs(test_runs, lambda x: restored.predict_proba(x)[:, 1])
        assert replay == fold["arms"]["refit_with_field_local"]["test"]


def test_experiment_cannot_overwrite_previous_artifacts(tmp_path):
    with pytest.raises(FileExistsError):
        run_experiment([], [], None, tmp_path)
