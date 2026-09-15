"""
Unit tests for ClickFraudGraphBuilder graph construction and memory bounds.
"""

import numpy as np
import pytest
import torch

from core_ml.features.graph_builder import ClickFraudGraphBuilder, _deterministic_hash_feature


class TestGraphBuilder:
    def test_deterministic_hash(self):
        # Same input across multiple calls must yield identical hash float
        h1 = _deterministic_hash_feature("192.168.1.50")
        h2 = _deterministic_hash_feature("192.168.1.50")
        assert h1 == h2
        assert 0.0 <= h1 < 1.0

        assert _deterministic_hash_feature("") == 0.0
        assert _deterministic_hash_feature(None) == 0.0

    def test_graph_node_and_edge_creation(self):
        builder = ClickFraudGraphBuilder(max_sessions=100)

        # Ingest 3 events
        ev1 = {
            "sessionId": "s1",
            "visitorId": "dev1",
            "pageUrl": "/home",
            "fingerprint": {"hardwareConcurrency": 8},
            "botd": {"heuristicScore": 0.0},
            "mouse": {"records": []},
        }
        ev2 = {
            "sessionId": "s2",
            "visitorId": "dev1",  # same device, different session (coordinated behavior)
            "pageUrl": "/checkout",
            "fingerprint": {"hardwareConcurrency": 8},
            "botd": {"heuristicScore": 0.8},
            "mouse": {"records": []},
        }
        ev3 = {
            "sessionId": "s3",
            "visitorId": "dev2",
            "pageUrl": "/home",
            "fingerprint": {"hardwareConcurrency": 4},
            "botd": {"heuristicScore": 0.1},
            "mouse": {"records": []},
        }

        builder.add_telemetry_event(ev1, ip_address="10.0.0.1", is_bot_ground_truth=0)
        builder.add_telemetry_event(ev2, ip_address="10.0.0.1", is_bot_ground_truth=1)
        builder.add_telemetry_event(ev3, ip_address="10.0.0.2", is_bot_ground_truth=0)

        assert len(builder.device_map) == 2
        assert len(builder.session_map) == 3
        assert len(builder.ip_map) == 2
        assert len(builder.target_map) == 2

        tensors = builder.to_torch_tensors()
        assert tensors["x_dict"]["device"].shape[0] == 2
        assert tensors["x_dict"]["session"].shape[0] == 3
        assert tensors["x_dict"]["ip"].shape[0] == 2
        assert tensors["y_session"].shape[0] == 3

    def test_memory_bounds_preserve_existing_topology(self):
        # Builder with small max_sessions limit
        builder = ClickFraudGraphBuilder(max_sessions=5)
        for i in range(10):
            ev = {
                "sessionId": f"sess_{i}",
                "visitorId": f"dev_{i}",
                "pageUrl": "/",
            }
            builder.add_telemetry_event(ev)

        # Capacity pruning prevents unbounded growth
        assert len(builder.session_map) <= 5
        assert "sess_0" in builder.session_map
        assert "sess_4" in builder.session_map

    def test_none_safe_ingestion(self):
        builder = ClickFraudGraphBuilder()
        idx = builder.add_telemetry_event(None)
        assert idx == 0
        assert len(builder.session_map) == 1

    def test_edge_deduplication_on_repeated_heartbeats(self):
        builder = ClickFraudGraphBuilder(max_sessions=100)
        # Send 10 repeated heartbeats for the EXACT SAME session, device, and IP
        ev = {
            "sessionId": "sess_recurring_heartbeat",
            "visitorId": "dev_same",
            "pageUrl": "/dashboard",
            "fingerprint": {},
            "botd": {},
            "mouse": {"records": []},
        }
        for _ in range(10):
            builder.add_telemetry_event(ev, ip_address="10.0.0.99")

        # Session count must be 1
        assert len(builder.session_map) == 1
        # Edges MUST be deduplicated: exactly 1 edge per relation type, not 10!
        assert len(builder.edges_device_session) == 1
        assert len(builder.edges_session_ip) == 1
        assert len(builder.edges_session_target) == 1
