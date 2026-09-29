"""
Unit tests for core ML models and multi-modal ensemble.
"""

import math
import joblib
import numpy as np
import pytest
import torch
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES


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
        assert clf.predict_proba(np.zeros((1, 50))) == p
        assert clf.predict_proba(np.zeros((2, 50))) == 0.5
        assert clf.predict_proba(None) == 0.5

    def test_batch_predict_accepts_single_vector(self):
        clf = TabularBotClassifier()

        probabilities = clf.predict_batch(np.zeros(50))

        assert probabilities.shape == (1,)
        assert probabilities[0] == 0.5

    def test_load_reports_unfitted_artifact_as_unavailable(self, tmp_path):
        path = tmp_path / "unfitted.joblib"
        joblib.dump(
            {
                "model": XGBClassifier(),
                "scaler": StandardScaler(),
                "fitted": False,
                "features": [],
            },
            path,
        )

        classifier = TabularBotClassifier()

        assert classifier.load(str(path)) is False
        assert classifier.is_fitted is False

    def test_load_rejects_artifact_claiming_fitted_without_fitted_objects(self, tmp_path):
        path = tmp_path / "false-ready.joblib"
        joblib.dump(
            {
                "model": XGBClassifier(),
                "scaler": StandardScaler(),
                "fitted": True,
                "features": [],
            },
            path,
        )

        classifier = TabularBotClassifier()

        assert classifier.load(str(path)) is False
        assert classifier.is_fitted is False

    def test_fitted_model_round_trip_remains_available(self, tmp_path):
        path = tmp_path / "trained.joblib"
        features = ["a", "b", "c"]
        classifier = TabularBotClassifier(n_estimators=3, max_depth=2)
        classifier.fit(
            np.array([[0, 0, 0], [1, 1, 1], [0.1, 0.2, 0.1], [0.9, 0.8, 0.9]]),
            np.array([0, 1, 0, 1]),
            feature_names=features,
        )
        classifier.save(str(path))

        loaded = TabularBotClassifier()

        assert loaded.load(str(path)) is True
        assert loaded.is_fitted is True

        incompatible = TabularBotClassifier()
        assert incompatible.load(str(path), expected_feature_names=["x", "y", "z"]) is False
        assert incompatible.is_fitted is False

    def test_dimension_mismatch_resilience(self):
        clf = TabularBotClassifier(n_estimators=5)
        X_train = np.random.randn(20, 50).astype(np.float32)
        y_train = np.random.randint(0, 2, size=20)
        clf.fit(X_train, y_train)

        for size in (30, 70):
            with pytest.raises(RuntimeError, match="feature dimension"):
                clf.predict_proba(np.random.randn(size))

    def test_fitted_runtime_failure_is_not_hidden_as_neutral_probability(self, monkeypatch):
        clf = TabularBotClassifier(n_estimators=5)
        X_train = np.random.randn(20, 4).astype(np.float32)
        clf.fit(X_train, np.array([0, 1] * 10))

        def fail_transform(_values):
            raise RuntimeError("broken scaler")

        monkeypatch.setattr(clf.scaler, "transform", fail_transform)

        with pytest.raises(RuntimeError, match="broken scaler"):
            clf.predict_proba(X_train[0])


class TestBehavioralLSTM:
    @pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1, 1.1])
    def test_rejects_invalid_output_from_any_chunk(self, monkeypatch, invalid):
        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
        monkeypatch.setattr(
            model, "forward", lambda _chunks: torch.tensor([[invalid], [0.99]])
        )
        with pytest.raises(RuntimeError, match="invalid chunk probabilities"):
            model.predict_session_proba(torch.zeros(2, 24, 8))

    def test_rejects_wrong_chunk_count(self, monkeypatch):
        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
        monkeypatch.setattr(model, "forward", lambda _chunks: torch.tensor([[0.99]]))
        with pytest.raises(RuntimeError, match="invalid chunk probabilities"):
            model.predict_session_proba(torch.zeros(2, 24, 8))

    def test_monotonic_scores_reject_invalid_chunk(self, monkeypatch):
        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
        monkeypatch.setattr(model, "forward", lambda _chunks: torch.tensor([[0.1], [float("nan")]]))
        with pytest.raises(RuntimeError, match="invalid chunk probabilities"):
            model.predict_session_scores(torch.zeros(2, 24, 8))

    def test_p75_override_requires_support_from_session_mean(self, monkeypatch):
        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16, p75_min_weighted_mean=0.0)
        predictions = torch.tensor([[0.01], [0.02], [0.8], [0.95]])
        monkeypatch.setattr(model, "forward", lambda _chunks: predictions)
        chunks = torch.zeros(4, 24, 8)

        legacy = model.predict_session_proba(chunks)
        model.p75_min_weighted_mean = 0.7
        guarded = model.predict_session_proba(chunks)

        assert guarded < legacy
        assert guarded < 0.7

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


class TestEnsembleDetector:
    def test_explicit_automation_requires_server_and_browser_corroboration(self):
        headless = "Mozilla/5.0 HeadlessChrome/154.0.0.0"
        regular = "Mozilla/5.0 Chrome/154.0.0.0"
        detector = EnsembleBotDetector()
        cases = (
            (headless, headless, {"webdriver": True}, "BOT"),
            (headless, headless, {"chromeDriverGlobal": True}, "BOT"),
            (regular, headless, {"webdriver": True}, "SUSPECT"),
            ("", headless, {"webdriver": True}, "SUSPECT"),
            (headless, regular, {"webdriver": True}, "SUSPECT"),
            (headless, headless, {"headlessUa": True}, "SUSPECT"),
            (regular, regular, {}, "SUSPECT"),
        )
        for server_ua, browser_ua, flags, expected in cases:
            result = detector.predict({
                "_server_user_agent": server_ua,
                "fingerprint": {"userAgent": browser_ua},
                "botd": {"detectors": flags},
                "mouse": {"records": []},
            })
            assert result["verdict"] == expected
            assert result["is_bot"] is (expected == "BOT")
            assert result["breakdown"]["decision_basis"] == (
                "explicit_automation" if expected == "BOT" else "insufficient_evidence"
            )
            assert result["breakdown"]["risk_score_in_domain"] is False
            assert result["decision_state"] == (
                "FINAL" if expected == "BOT" else "INSUFFICIENT_EVIDENCE"
            )

    def test_confirmed_profile_decision_does_not_depend_on_mouse_models(self):
        class BrokenLstm:
            def predict_session_scores(self, _chunks):
                raise RuntimeError("LSTM unavailable")

        class BrokenTabular:
            def predict_proba(self, _features):
                raise RuntimeError("Tabular unavailable")

        detector = EnsembleBotDetector(lstm_model=BrokenLstm(), tabular_model=BrokenTabular())
        headless = "Mozilla/5.0 HeadlessChrome/154.0.0.0"
        for count in (0, 25):
            records = [
                {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
                for i in range(count)
            ]
            result = detector.predict({
                "_server_user_agent": headless,
                "fingerprint": {"userAgent": headless},
                "botd": {"detectors": {"webdriver": True}},
                "mouse": {"records": records},
            })
            assert result["verdict"] == "BOT"
            assert result["decision_state"] == "FINAL"
            assert result["breakdown"]["decision_basis"] == "explicit_automation"
            assert result["breakdown"]["behavioral_lstm_score"] is None
            assert result["breakdown"]["tabular_score"] is None
            assert result["breakdown"]["risk_score_in_domain"] is False

    def test_tabular_score_is_not_applicable_without_trained_mouse_input(self):
        class StrongTabular:
            def predict_proba(self, _features):
                return 0.999

        detector = EnsembleBotDetector(tabular_model=StrongTabular())
        no_mouse = detector.predict({"mouse": {"records": []}})
        assert no_mouse["verdict"] == "SUSPECT"
        assert no_mouse["breakdown"]["tabular_score"] == 0.999
        assert no_mouse["breakdown"]["tabular_score_in_domain"] is False
        assert no_mouse["breakdown"]["risk_score_in_domain"] is False

        records = [
            {"time": index * 20, "x": index / 100, "y": 0.2, "type": "move"}
            for index in range(25)
        ]
        enough_mouse = detector.predict({"mouse": {"records": records}})
        assert enough_mouse["breakdown"]["tabular_score_in_domain"] is True
        assert enough_mouse["breakdown"]["risk_score_in_domain"] is True

    def test_mean_risk_is_monotonic_and_tail_only_abstains(self, monkeypatch):
        class Tabular:
            def __init__(self, probability):
                self.probability = probability

            def predict_proba(self, _features):
                return self.probability

        model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=16)
        tabular = Tabular(0.99)
        detector = EnsembleBotDetector(lstm_model=model, tabular_model=tabular)
        records = [
            {"time": index * 16, "x": index / 100, "y": 0.2 + index % 3 / 100,
             "type": "move"}
            for index in range(37)
        ]
        results = []
        for scores in ([0.5, 0.99], [0.6, 0.99]):
            monkeypatch.setattr(model, "forward", lambda _chunks, scores=scores: (
                torch.tensor(scores).reshape(-1, 1)
            ))
            results.append(detector.predict({"mouse": {"records": records}}))
        assert results[1]["risk_score"] > results[0]["risk_score"]
        assert results[1]["breakdown"]["behavioral_lstm_tail_score"] >= (
            results[0]["breakdown"]["behavioral_lstm_tail_score"]
        )

        tabular.probability = 0.1
        monkeypatch.setattr(model, "forward", lambda _chunks: torch.tensor([[0.1], [1.0]]))
        uncertain = detector.predict({"mouse": {"records": records}})
        assert uncertain["risk_score"] < detector.suspect_threshold
        assert uncertain["breakdown"]["suspicion_risk_score"] < detector.suspect_threshold
        assert uncertain["breakdown"]["behavioral_disagreement"] is True
        assert uncertain["verdict"] == "SUSPECT"

    def test_disagreeing_models_abstain_instead_of_calling_bot_human(self):
        class LSTM:
            def predict_session_scores(self, _chunks):
                return 0.4441, 0.7638

        class Tabular:
            def predict_proba(self, _features):
                return 0.0275

        detector = EnsembleBotDetector(lstm_model=LSTM(), tabular_model=Tabular())
        records = [
            {"time": index * 16, "x": index / 100, "y": 0.2 + index % 3 / 100,
             "type": "move"}
            for index in range(37)
        ]
        result = detector.predict({"mouse": {"records": records}})

        assert result["risk_score"] < detector.suspect_threshold
        assert result["breakdown"]["suspicion_risk_score"] < detector.suspect_threshold
        assert result["breakdown"]["behavioral_disagreement"] is True
        assert result["verdict"] == "SUSPECT"

        class AgreeingTabular:
            def predict_proba(self, _features):
                return 0.9

        detector.tabular_model = AgreeingTabular()
        agreeing = detector.predict({"mouse": {"records": records}})
        assert agreeing["breakdown"]["behavioral_disagreement"] is False
        assert agreeing["verdict"] == "SUSPECT"

    def test_ensemble_decisions(self):
        ensemble = EnsembleBotDetector()

        # A browser-reported flag alone is not enough for a final block decision.
        bot_payload = {
            "fingerprint": {"hardwareConcurrency": 1, "deviceMemory": 2},
            "botd": {
                "heuristicScore": 0.999,
                "detectors": {"webdriver": True, "headlessUa": True},
                "reasons": ["navigator.webdriver is true"],
            },
            "mouse": {"records": []},
        }
        res_bot = ensemble.predict(bot_payload)
        assert res_bot["is_bot"] is False
        assert res_bot["verdict"] == "SUSPECT"
        assert res_bot["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert res_bot["score_calibrated"] is False

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

    def test_string_false_does_not_trigger_critical_bot_rule(self):
        detector = EnsembleBotDetector(lstm_available=False, tabular_available=False)
        result = detector.predict({
            "botd": {
                "heuristicScore": 0,
                "webdriver": "false",
                "automationTool": "0",
                "headless": "no",
                "detectors": {
                    "webdriver": "false",
                    "distinctiveProperties": "false",
                    "headlessUa": "false",
                },
            }
        })

        assert result["verdict"] != "BOT"
        assert not any(reason.startswith("Client-reported") for reason in result["reasons"])

    def test_non_finite_model_scores_fail_inference(self):
        class InvalidLSTM:
            def predict_session_proba(self, _chunks):
                return float("nan")

        class InvalidTabular:
            def predict_proba(self, _features):
                return float("inf")

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        detector = EnsembleBotDetector(lstm_model=InvalidLSTM(), tabular_model=InvalidTabular())
        with pytest.raises(RuntimeError, match="LSTM returned an invalid probability"):
            detector.predict({"mouse": {"records": records}})

    def test_positive_botd_evidence_never_reduces_fused_risk(self):
        class FixedModel:
            def __init__(self, probability):
                self.probability = probability

            def predict_proba(self, _features):
                return self.probability

            def predict_session_proba(self, _chunks):
                return self.probability

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(25)
        ]
        for lstm_score, tabular_score in ((1.0, 1.0), (0.05, 0.7), (0.5, 0.5)):
            detector = EnsembleBotDetector(
                lstm_model=FixedModel(lstm_score),
                tabular_model=FixedModel(tabular_score),
            )
            scores = [
                detector.predict({
                    "mouse": {"records": records},
                    "botd": {"heuristicScore": heuristic_score},
                })["risk_score"]
                for heuristic_score in (0, 0.1, 0.2, 0.3, 0.5, 1)
            ]
            assert scores == sorted(scores)

    def test_degenerate_mouse_records_do_not_finalize_human(self):
        class BenignModel:
            def predict_proba(self, _features):
                return 0.01

            def predict_session_proba(self, _chunks):
                return 0.01

        detector = EnsembleBotDetector(
            lstm_model=BenignModel(), tabular_model=BenignModel()
        )
        for records in (
            [{"time": 0, "x": 0.2, "y": 0.2, "type": "move"}] * 25,
            [{"time": i * 20, "x": 0.2, "y": 0.2, "type": "move"} for i in range(25)],
        ):
            result = detector.predict({"mouse": {"records": records}})
            assert result["verdict"] == "SUSPECT"
            assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
            assert result["breakdown"]["usable_trajectory"] is False

    def test_clamped_or_repeated_time_mouse_records_do_not_finalize(self):
        class StrongModels:
            def predict_session_proba(self, _chunks):
                return 0.99

            def predict_proba(self, _features):
                return 0.99

        detector = EnsembleBotDetector(
            lstm_model=StrongModels(), tabular_model=StrongModels(),
        )
        negative_records = [
            {"time": i * 20, "x": -i - 1, "y": -i - 1, "type": "move"}
            for i in range(30)
        ]
        repeated_times = [
            {"time": 0 if i < 29 else 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        for records in (negative_records, repeated_times):
            result = detector.predict({"mouse": {"records": records}})
            assert result["verdict"] == "SUSPECT"
            assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
            assert result["breakdown"]["usable_trajectory"] is False

    def test_mouse_points_counts_only_valid_moves(self):
        records = [
            {"time": 0, "x": 0.1, "y": 0.1, "type": "move"},
            {"time": 1, "x": 0.1, "y": 0.1, "type": "click"},
            {"time": "bad", "x": 0.2, "y": 0.2, "type": "move"},
        ]
        result = EnsembleBotDetector(lstm_available=False, tabular_available=False).predict(
            {"mouse": {"records": records}}
        )

        assert result["breakdown"]["mouse_points"] == 1
        assert result["breakdown"]["records_received"] == 3

    def test_short_session_defers_bot_decision_without_critical_flag(self):
        class StrongTabular:
            def predict_proba(self, _features):
                return 0.99

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(23)
        ]
        detector = EnsembleBotDetector(
            tabular_model=StrongTabular(), lstm_available=False, threshold=0.70
        )
        result = detector.predict({"mouse": {"records": records}})

        assert result["verdict"] == "SUSPECT"
        assert result["is_bot"] is False
        assert result["bot_probability"] > 0.70
        assert result["breakdown"]["decision_deferred"] is True
        assert result["breakdown"]["weights_used"]["w_lstm"] == 0
        assert result["breakdown"]["behavioral_lstm_score"] == 0.5

    def test_minimum_mouse_evidence_allows_final_decision(self):
        class StrongModels:
            def predict_session_proba(self, _chunks):
                return 0.99

            def predict_proba(self, _features):
                return 0.99

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(25)
        ]
        detector = EnsembleBotDetector(
            lstm_model=StrongModels(), tabular_model=StrongModels()
        )
        result = detector.predict({"mouse": {"records": records}})

        assert result["verdict"] == "BOT"
        assert result["breakdown"]["decision_deferred"] is False

    def test_24_moves_cannot_finalize_without_lstm_window(self):
        class StrongModels:
            def predict_session_proba(self, _chunks):
                return 0.99

            def predict_proba(self, _features):
                return 0.99

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(25)
        ]
        detector = EnsembleBotDetector(lstm_model=StrongModels(), tabular_model=StrongModels())

        for count in (0, 23, 24):
            result = detector.predict({"mouse": {"records": records[:count]}})
            assert result["verdict"] == "SUSPECT"
            assert result["is_bot"] is False
            assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
            assert result["breakdown"]["weights_used"]["w_lstm"] == 0
            assert result["breakdown"]["minimum_mouse_points"] == 25

        result = detector.predict({"mouse": {"records": records}})
        assert result["decision_state"] == "FINAL"
        assert result["is_bot"] is True

    def test_browser_flag_cannot_bypass_short_session_evidence_gate(self):
        detector = EnsembleBotDetector(lstm_available=False, tabular_available=False)
        result = detector.predict({"botd": {"detectors": {"webdriver": True}}})

        assert result["verdict"] == "SUSPECT"
        assert result["is_bot"] is False
        assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert result["bot_probability"] < 0.96

    def test_browser_flag_alone_cannot_override_benign_model_scores(self):
        class BenignModel:
            def predict_session_proba(self, _chunks):
                return 0.05

            def predict_proba(self, _features):
                return 0.05

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(25)
        ]
        detector = EnsembleBotDetector(
            lstm_model=BenignModel(), tabular_model=BenignModel()
        )
        result = detector.predict({
            "botd": {"detectors": {"webdriver": True}},
            "mouse": {"records": records},
        })

        assert result["decision_state"] == "FINAL"
        assert result["is_bot"] is False
        assert result["verdict"] == "SUSPECT"
        assert result["bot_probability"] < 0.70
        assert result["policy_version"] == DECISION_POLICY_VERSION

    def test_minimum_point_setting_cannot_exceed_retained_window(self):
        with pytest.raises(ValueError, match="retained record window"):
            EnsembleBotDetector(min_mouse_points_for_bot=101)

    def test_deferred_decision_survives_equal_threshold_configuration(self):
        detector = EnsembleBotDetector(
            threshold=0.70,
            suspect_threshold=0.70,
            lstm_available=False,
            tabular_available=False,
        )

        result = detector.predict({})

        assert result["verdict"] == "SUSPECT"
        assert result["is_bot"] is False

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

    def test_absent_heuristic_flags_do_not_override_strong_ml_evidence(self):
        class StrongLSTM:
            def predict_session_proba(self, _chunks):
                return 0.99

        class StrongTabular:
            def predict_proba(self, _features):
                return 0.99

        records = [
            {"time": i * 20, "x": 0.1 + i * 0.01, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        detector = EnsembleBotDetector(lstm_model=StrongLSTM(), tabular_model=StrongTabular())
        result = detector.predict({
            "botd": {"heuristicScore": 0.0, "detectors": {}},
            "mouse": {"records": records},
        })

        assert result["verdict"] == "BOT"
        assert result["bot_probability"] > 0.8
        assert result["breakdown"]["weights_used"]["w_heuristic"] < 0.1

    def test_touch_trajectory_is_not_classified_as_mouse(self):
        class FailingLSTM:
            def predict_session_proba(self, _chunks):
                raise AssertionError("Touch points must not reach the mouse model")

        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move", "source": "touch"}
            for i in range(30)
        ]
        result = EnsembleBotDetector(lstm_model=FailingLSTM()).predict(
            {"mouse": {"records": records}}
        )

        assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert result["is_bot"] is False
        assert result["breakdown"]["mouse_points"] == 0
        assert result["breakdown"]["touch_records_excluded"] == 30

    def test_missing_model_defers_decision_even_with_mouse_points(self):
        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        result = EnsembleBotDetector(lstm_available=False).predict(
            {"mouse": {"records": records}}
        )

        assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert result["is_bot"] is False

    def test_mobile_user_agent_defers_legacy_untagged_touch_records(self):
        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        result = EnsembleBotDetector().predict({
            "fingerprint": {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"},
            "mouse": {"records": records},
        })

        assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert result["is_bot"] is False
        assert result["breakdown"]["unsupported_mobile"] is True

    def test_touch_capable_legacy_desktop_input_is_ambiguous(self):
        records = [
            {"time": i * 20, "x": i / 100, "y": 0.2, "type": "move"}
            for i in range(30)
        ]
        result = EnsembleBotDetector().predict({
            "fingerprint": {"userAgent": "Desktop Chrome", "maxTouchPoints": 5},
            "mouse": {"records": records},
        })

        assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
        assert result["is_bot"] is False
        assert result["breakdown"]["legacy_touch_ambiguous"] is True
