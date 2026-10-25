"""Build immutable research snapshots, independently of model predictions."""

import hashlib
import json
import uuid


def build_capture(payload: dict, *, received_at: int, client_ip: str,
                  user_agent: str, bundle_id: str, policy_version: str,
                  retention_days: int) -> dict:
    # Store JSON verbatim after API validation, not the truncated dashboard
    # projection. This preserves scroll, touch and nested profile evidence.
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    stable_identity = payload.get("timestamp") is not None and payload.get("sequence") is not None
    collector = payload.get("collector")
    collector = collector if isinstance(collector, dict) else {}
    return {
        "schema_version": 1,
        "event_id": digest if stable_identity else uuid.uuid4().hex,
        "identity_kind": "payload_sha256" if stable_identity else "server_uuid",
        "payload_sha256": digest,
        "payload_json": payload_json,
        "sessionId": payload["sessionId"],
        "visitorId": payload["visitorId"],
        "study_id": collector.get("studyId"),
        "site_id": collector.get("siteId"),
        "page_instance_id": collector.get("pageInstanceId"),
        "received_at": received_at,
        "expires_at_ms": received_at + retention_days * 86_400_000,
        "client_ip": client_ip,
        "server_user_agent": user_agent,
        # Capture-time provenance is not a claim that inference succeeded.
        "capture_bundle_id": bundle_id,
        "capture_policy_version": policy_version,
    }
