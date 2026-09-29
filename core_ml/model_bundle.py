"""Integrity verification shared by model training, serving, and evaluation."""

import hashlib
import json
import math
import os
import secrets

from core_ml.collector_windows import TRAIN_FULL_TRAJECTORY_CHECKPOINTS
from core_ml.release_cases import KNOWN_FAILURE_WINDOWS, REGRESSION_CASE_FINGERPRINT


RELEASE_MINIMUM_METRICS = {"roc_auc": 0.80, "precision": 0.75, "recall": 0.75}
RELEASE_EARLY_MINIMUM_METRICS = {"roc_auc": 0.80, "precision": 0.90, "recall": 0.60}
RELEASE_MAXIMUM_METRICS = {"false_positive_rate": 0.0}


def release_evidence_valid(manifest: dict, policy_version: str, threshold: float,
                           suspect_threshold: float, *,
                           min_mouse_points_for_bot: int = 25) -> bool:
    """Check that the exact deployed policy has passed its validation gates."""
    training = manifest.get("training") or {}
    if not isinstance(training, dict):
        return False
    dataset = training.get("dataset") or {}
    if not isinstance(dataset, dict):
        return False
    splits = dataset.get("split_counts") or {}
    if not isinstance(splits, dict):
        return False
    if (
        training.get("diagnostic_only") is True
        or training.get("decision_policy_version") != policy_version
        or training.get("production_decision_threshold") != threshold
        or training.get("production_suspect_threshold") != suspect_threshold
        or any(
            type(splits.get(split)) is not int or splits[split] <= 0
            for split in ("train", "val", "test")
        )
    ):
        return False

    metric_groups = training.get("metrics") or {}
    if not isinstance(metric_groups, dict):
        return False
    metrics_by_split = metric_groups.get("ensemble") or {}
    if not isinstance(metrics_by_split, dict):
        return False
    for split in ("val", "early_val", "mid_val", "late_val"):
        metrics = metrics_by_split.get(split)
        if not isinstance(metrics, dict):
            return False
        minimums = RELEASE_MINIMUM_METRICS if split == "val" else RELEASE_EARLY_MINIMUM_METRICS
        for name, minimum in minimums.items():
            try:
                value = float(metrics[name])
            except (KeyError, TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(value) or not minimum <= value <= 1.0:
                return False
        for name, maximum in RELEASE_MAXIMUM_METRICS.items():
            try:
                value = float(metrics[name])
            except (KeyError, TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(value) or not 0.0 <= value <= maximum:
                return False
        coverage = metrics.get("decision_coverage")
        try:
            coverage = float(coverage)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(coverage) or not 0.0 < coverage <= 1.0:
            return False
    if policy_version in ("7", "8", "9", "10"):
        checkpoints = 1000 if policy_version in ("9", "10") else 100 if policy_version == "8" else 25
        if (
            training.get("environment_features_trained") is not False
            or training.get("minimum_mouse_points_for_bot") != min_mouse_points_for_bot
            or min_mouse_points_for_bot != 25
            or training.get("collector_window_policy") != "mouse_export_v1"
            or training.get("rolling_checkpoints") != checkpoints
        ):
            return False
        if policy_version == "8" and (
            training.get("rolling_full_replay") is not True
            or training.get("lstm_p75_min_weighted_mean") != 0.70
        ):
            return False
        if policy_version in ("9", "10"):
            regression = metrics_by_split.get("known_regressions") or {}
            if (
                training.get("rolling_full_replay") is not True
                or training.get("train_full_trajectory_windows") is not True
                or training.get("train_full_trajectory_checkpoints") != TRAIN_FULL_TRAJECTORY_CHECKPOINTS
                or training.get("lstm_aggregation") != "mean_p75_disagreement_v2"
                or training.get("regression_case_fingerprint") != REGRESSION_CASE_FINGERPRINT
                or not isinstance(regression, dict)
                or regression.get("session_count") != len(KNOWN_FAILURE_WINDOWS)
                or type(regression.get("checked_windows")) not in (int, float)
                or not math.isfinite(regression["checked_windows"])
                or regression["checked_windows"] != int(regression["checked_windows"])
                or regression["checked_windows"] < sum(len(times) for _, times in KNOWN_FAILURE_WINDOWS.values())
            ):
                return False
        if policy_version == "10" and training.get("explicit_automation_rule_gate") != {
            "rule": "headless_ua_and_framework_v1",
            "positive_cases": 2,
            "negative_cases": 5,
            "passed": 7,
        }:
            return False
        for split, min_humans, min_bots in (
            ("rolling_val", 10, 20), ("rolling_test", 20, 30),
        ):
            metrics = metrics_by_split.get(split)
            if not isinstance(metrics, dict):
                return False
            counts = {}
            for name in (
                "human_sessions", "bot_sessions", "human_ever_bot",
                "human_ever_suspect", "bot_ever_human", "human_windows", "bot_windows",
                "human_bot_windows", "bot_human_windows",
                *(("human_suspect_windows",) if policy_version in ("9", "10") else ()),
            ):
                value = metrics.get(name)
                try:
                    valid_count = (
                        type(value) in (int, float) and math.isfinite(value)
                        and value >= 0 and value == int(value)
                    )
                except (OverflowError, ValueError):
                    return False
                if not valid_count:
                    return False
                counts[name] = int(value)
            max_human_suspect_fraction = metrics.get("max_human_suspect_fraction")
            if policy_version in ("9", "10") and (
                type(max_human_suspect_fraction) not in (int, float)
                or not math.isfinite(max_human_suspect_fraction)
                or not 0 <= max_human_suspect_fraction <= 0.25
            ):
                return False
            if (
                counts["human_sessions"] < min_humans
                or counts["bot_sessions"] < min_bots
                or counts["human_windows"] != checkpoints * counts["human_sessions"]
                or counts["bot_windows"] != checkpoints * counts["bot_sessions"]
                or counts["human_ever_bot"] != 0
                or counts["human_bot_windows"] != 0
                or counts["human_ever_suspect"] > counts["human_sessions"]
                or counts["bot_ever_human"] > counts["bot_sessions"]
                or counts["bot_human_windows"] > counts["bot_windows"]
                or (policy_version not in ("9", "10") and counts["human_ever_suspect"] / counts["human_sessions"] > 0.80)
                or (policy_version in ("9", "10") and (
                    counts["human_suspect_windows"] > 0.10 * counts["human_windows"]
                    or counts["human_suspect_windows"] > counts["human_windows"]
                ))
                or counts["bot_ever_human"] / counts["bot_sessions"] > 0.05
                or (policy_version in ("8", "9", "10") and (counts["bot_ever_human"] or counts["bot_human_windows"]))
            ):
                return False
    return True


class ModelBundleError(RuntimeError):
    """Raised when a model bundle cannot be trusted or is incomplete."""


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_bundle(
    weights_dir: str,
    expected_feature_names: list,
    *,
    require_manifest: bool = True,
) -> dict:
    """Return a verified manifest or raise instead of loading mismatched weights."""
    manifest_path = os.path.join(weights_dir, "model_manifest.json")
    if not os.path.isfile(manifest_path):
        if require_manifest:
            raise ModelBundleError("Model manifest is missing")
        return {}

    try:
        with open(manifest_path, "r", encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ModelBundleError("Model manifest cannot be read") from exc

    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ModelBundleError("Unsupported model manifest schema")
    bundle_id = manifest.get("bundle_id")
    if (
        not isinstance(bundle_id, str)
        or len(bundle_id) != 32
        or any(character not in "0123456789abcdef" for character in bundle_id)
    ):
        raise ModelBundleError("Model manifest bundle_id is missing or invalid")
    if manifest.get("feature_names") != list(expected_feature_names):
        raise ModelBundleError("Model feature schema does not match runtime")

    artifacts = manifest.get("artifacts") or {}
    for filename in ("tabular_model.joblib", "behavioral_lstm.pt"):
        expected_hash = artifacts.get(filename)
        artifact_path = os.path.join(weights_dir, filename)
        if not expected_hash or not os.path.isfile(artifact_path):
            raise ModelBundleError(f"Missing artifact metadata for {filename}")
        try:
            actual_hash = file_sha256(artifact_path)
        except OSError as exc:
            raise ModelBundleError(f"Cannot read model artifact {filename}") from exc
        if not secrets.compare_digest(actual_hash, str(expected_hash)):
            raise ModelBundleError(f"Artifact hash mismatch for {filename}")

    return manifest
