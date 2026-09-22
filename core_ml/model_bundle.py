"""Integrity verification shared by model training, serving, and evaluation."""

import hashlib
import json
import os
import secrets


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
