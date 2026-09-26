"""Integrity verification shared by model training, serving, and evaluation."""

import hashlib
import json
import math
import os
import secrets


RELEASE_MINIMUM_METRICS = {"roc_auc": 0.80, "precision": 0.75, "recall": 0.75}
RELEASE_EARLY_MINIMUM_METRICS = {"roc_auc": 0.80, "precision": 0.90, "recall": 0.60}
RELEASE_MAXIMUM_METRICS = {"false_positive_rate": 0.0}


def release_evidence_valid(manifest: dict, policy_version: str, threshold: float,
                           suspect_threshold: float) -> bool:
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
            if not math.isfinite(value) or value < minimum:
                return False
        for name, maximum in RELEASE_MAXIMUM_METRICS.items():
            try:
                value = float(metrics[name])
            except (KeyError, TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(value) or value > maximum:
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
