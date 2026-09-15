"""
Unit tests for core ML models and multi-modal ensemble.
"""

import math
import os
import numpy as np
import pytest
import torch

from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.gnn_detector import HeteroClickFraudGNN
from core_ml.models.ensemble import EnsembleBotDetector
from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES
from core_ml.features.graph_builder import SESSION_FEATURE_DIM


class TestTabularClassifier:
    def test_fit_and_predict(self):
        clf = TabularBotClassifier(n_estimators=10, max_depth=3)
        n_features = len(ENV_FEATURE_NAMES) + len(STATISTICAL_FEATURE_NAMES)
        X = np.random.randn(50, n_features).astype(np.float32)
        y = np.random.randint(0, 2, size=50)

        clf.fit(X, y)
        assert clf.is_fitted

        # Single predict
        p = clf.predict_proba(X[0])
        assert 0.0 <= p <= 1.0

        # Batch predict
        probas = clf.predict_batch(X[:5])
        assert len(probas) == 5
        assert ((probas >= 0.0) & (probas <= 1.0)).all()

    def test_unfitted_fallback(self):
        clf = TabularBotClassifier()
        assert not clf.is_fitted
        p = clf.predict_proba(np.zeros(50))
        assert 0.0 <= p <= 1.0
        assert clf.predict_proba(None) == 0.5

    def test_dimension_mismatch_resilience(self):
        clf = TabularBotClassifier(n_estimators=5)
        X_train = np.random.randn(20, 50).astype(np.float32)
        y_train = np.random.randint(0, 2, size=20)
        clf.fit(X_train, y_train)

        # Fewer features (padding should trigger)
        p_short = clf.predict_proba(np.random.randn(30))
        assert 0.0 <= p_short <= 1.0

        # More features (truncation should trigger)
        p_long = clf.predict_proba(np.random.randn(70))
        assert 0.0 <= p_long <= 1.0


class TestBehavioralLSTM:
    def test_forward_and_predict_session(self):
        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=32, num_layers=2)
        batch = torch.randn(4, 24, 8)
        out = model(batch)
        assert out.shape == (4, 1)
        assert ((out >= 0.0) & (out <= 1.0)).all()

        # predict_session_proba
        proba = model.predict_session_proba(batch)
        assert 0.0 <= proba <= 1.0

        # Empty chunks
        assert model.predict_session_proba(None) == 0.5
        assert model.predict_session_proba(torch.zeros(0, 24, 8)) == 0.5


class TestHeteroGNN:
    def test_gnn_forward(self):
        gnn = HeteroClickFraudGNN(hidden_dim=32)
        x_dict = {
            "device": torch.randn(2, len(ENV_FEATURE_NAMES)),
            "ip": torch.randn(3, 3),
            "session": torch.randn(4, len(STATISTICAL_FEATURE_NAMES) + 2),
            "target": torch.randn(1, 2),
        }
        edge_index_dict = {
            ("device", "operates", "session"): torch.tensor([[0, 1], [0, 1]], dtype=torch.long),
            ("ip", "originates", "session"): torch.tensor([[0, 1], [0, 1]], dtype=torch.long),
            ("target", "targeted_by", "session"): torch.tensor([[0, 0], [0, 1]], dtype=torch.long),
        }
        logits = gnn(x_dict, edge_index_dict)
        assert logits.shape == (4, 2)

        probs = gnn.predict_session_probabilities(x_dict, edge_index_dict)
        assert probs.shape == (4,)
        assert ((probs >= 0.0) & (probs <= 1.0)).all()

    def test_gnn_missing_keys_resilience(self):
        gnn = HeteroClickFraudGNN(hidden_dim=32, num_layers=2)
        # x_dict missing 'target' and 'ip' keys completely
        partial_x_dict = {
            "device": torch.randn(2, len(ENV_FEATURE_NAMES)),
            "session": torch.randn(2, SESSION_FEATURE_DIM),
        }
        # edge_dict is empty
        empty_edge_dict = {}
        logits = gnn(partial_x_dict, empty_edge_dict)
        assert logits.shape == (2, 2)
        assert not torch.isnan(logits).any()


class TestEnsembleDetector:
    def test_ensemble_decisions(self):
        ensemble = EnsembleBotDetector()

        # 1. Obvious bot payload (webdriver = True)
        bot_payload = {
            "fingerprint": {"hardwareConcurrency": 1, "deviceMemory": 2},
            "botd": {
                "heuristicScore": 0.85,
                "detectors": {"webdriver": True, "headlessUa": True},
                "reasons": ["navigator.webdriver is true"],
            },
            "mouse": {"records": []},
        }
        res_bot = ensemble.predict(bot_payload)
        assert res_bot["is_bot"] is True
        assert res_bot["bot_probability"] >= 0.75
        assert res_bot["verdict"] == "BOT"

        # 2. None / empty payload (graceful degradation)
        res_empty = ensemble.predict(None)
        assert isinstance(res_empty, dict)
        assert "is_bot" in res_empty
        assert "bot_probability" in res_empty
        assert "breakdown" in res_empty

    def test_ensemble_corrupted_payload_resilience(self):
        ensemble = EnsembleBotDetector()
        corrupted_payload = {
            "botd": {"heuristicScore": "invalid_string_not_float", "detectors": None},
            "fingerprint": {"screenResolution": None, "hardwareConcurrency": "NaN"},
            "mouse": {
                "records": [
                    {"time": "bad_time", "x": None, "y": float("nan"), "type": "move"},
                    {"time": 100, "x": float("inf"), "y": -float("inf"), "type": "move"},
                ],
                "chunks": [
                    [[float("nan")] * 8] * 24
                ]
            }
        }
        res = ensemble.predict(corrupted_payload)
        assert isinstance(res, dict)
        assert not math.isnan(res["bot_probability"])
        assert 0.0 <= res["bot_probability"] <= 1.0
        assert res["verdict"] in ("HUMAN", "BOT", "SUSPECT")

    def test_ensemble_uses_configured_thresholds(self):
        detector = EnsembleBotDetector(threshold=0.99, suspect_threshold=0.98)
        result = detector.predict({"botd": {"heuristicScore": 0.6}})
        assert result["verdict"] != "BOT"

    def test_unavailable_lstm_is_not_used(self):
        detector = EnsembleBotDetector(lstm_available=False)
        chunk = [[0.01] * 8 for _ in range(24)]
        result = detector.predict({"mouse": {"chunks": [chunk]}})
        assert result["breakdown"]["weights_used"]["w_lstm"] == 0

    def test_client_chunks_cannot_spoof_mouse_sufficiency(self):
        class FailingLSTM:
            def predict_session_proba(self, _chunks):
                raise AssertionError("LSTM must not receive client-provided chunks")

        detector = EnsembleBotDetector(lstm_model=FailingLSTM())
        fake_chunk = [[0.1] * 8 for _ in range(24)]
        result = detector.predict({"mouse": {"records": [], "chunks": [fake_chunk]}})

        assert result["breakdown"]["has_enough_mouse_data"] is False
        assert result["breakdown"]["behavioral_lstm_score"] == 0.5
