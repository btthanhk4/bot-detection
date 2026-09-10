"""
Multi-Modal Ensemble Bot Detector (v2)
=======================================
Fuses DELBOT-Mouse Behavioral BiLSTM, Tabular Environment XGBoost, and BotD Heuristic Rules.
Improvements:
  - Confidence-based adaptive weighting (higher confidence → higher weight)
  - Improved data sufficiency scoring
  - 6 new mouse features integrated into tabular vector
  - Better threshold calibration
"""

import numpy as np
from core_ml.features.env_features import extract_env_vector
from core_ml.features.mouse_features import compute_statistical_features, extract_sequential_chunks
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier


class EnsembleBotDetector:
    def __init__(
        self,
        lstm_model: MouseTrajectoryLSTM = None,
        tabular_model: TabularBotClassifier = None,
        w_lstm: float = 0.40,
        w_tabular: float = 0.40,
        w_heuristic: float = 0.20,
        threshold: float = 0.50,
    ):
        self.lstm_model = lstm_model or MouseTrajectoryLSTM()
        self.tabular_model = tabular_model or TabularBotClassifier()
        self.w_lstm = w_lstm
        self.w_tabular = w_tabular
        self.w_heuristic = w_heuristic
        self.threshold = threshold

    def _compute_confidence_weight(self, score: float) -> float:
        """Higher confidence (further from 0.5) → higher weight."""
        return abs(score - 0.5) * 2.0 + 0.3  # min weight = 0.3

    def predict(self, telemetry_payload: dict) -> dict:
        """
        Takes raw telemetry JSON payload from collector and outputs unified decision.
        """
        fingerprint = telemetry_payload.get("fingerprint", {})
        botd = telemetry_payload.get("botd", {})
        mouse = telemetry_payload.get("mouse", {})

        records = mouse.get("records", [])
        chunks = mouse.get("chunks", [])

        # Compute mouse stats ONCE — reused for both fallback logic and tabular vector
        mouse_stats = compute_statistical_features(records)

        # 1. BotD Heuristics evaluation
        heuristic_score = float(botd.get("heuristicScore", 0.0))
        reasons = list(botd.get("reasons", []))
        detectors = botd.get("detectors", {})

        # Immediate hard rule triggers (100% confidence bot flags)
        critical_flags = []
        if detectors.get("webdriver", False):
            critical_flags.append("Critical: Webdriver automation flag confirmed")
        if detectors.get("distinctiveProperties", False):
            critical_flags.append("Critical: Automation framework signature detected")
        reasons.extend(critical_flags)

        # 2. Behavioral LSTM evaluation
        chunks_tensor = extract_sequential_chunks(chunks)
        has_enough_mouse_data = chunks_tensor.size(0) > 0
        if has_enough_mouse_data:
            lstm_score = self.lstm_model.predict_session_proba(chunks_tensor)
            if lstm_score > 0.70:
                reasons.append(f"Mouse dynamics exhibit robotic trajectory (LSTM score: {lstm_score:.2f})")
        else:
            # If user hasn't moved mouse enough, use precomputed mouse stats
            if mouse_stats["point_count"] > 5:
                if mouse_stats["straightness"] > 0.98:
                    lstm_score = 0.80
                    reasons.append("Unnaturally straight mouse trajectory")
                elif mouse_stats["time_regularity"] < 0.05 and mouse_stats["point_count"] > 10:
                    lstm_score = 0.75
                    reasons.append("Suspiciously regular timing between mouse events")
                else:
                    lstm_score = 0.50  # neutral
            else:
                lstm_score = 0.50  # neutral

        # 3. Tabular model evaluation (with 6 new features)
        env_vec = extract_env_vector(fingerprint, botd)
        # Reuse precomputed mouse_stats (no duplicate call)
        mouse_stat_vec = np.array(
            [
                mouse_stats["mean_speed"],
                mouse_stats["std_speed"],
                mouse_stats["max_speed"],
                mouse_stats["mean_accel"],
                mouse_stats["std_accel"],
                mouse_stats["straightness"],
                mouse_stats["pause_ratio"],
                float(mouse_stats["direction_changes_x"]),
                float(mouse_stats["direction_changes_y"]),
                mouse_stats["jerk_mean"],
                mouse_stats["angular_entropy"],
                # 6 new features
                mouse_stats["curvature_mean"],
                mouse_stats["curvature_std"],
                mouse_stats["time_regularity"],
                mouse_stats["velocity_autocorrelation"],
                mouse_stats["accel_zero_crossing_rate"],
                mouse_stats["movement_efficiency"],
                # 3 additional features (v2.1)
                mouse_stats["click_to_move_ratio"],
                mouse_stats["speed_skewness"],
                mouse_stats["idle_time_ratio"],
            ],
            dtype=np.float32,
        )
        combined_tabular_vec = np.concatenate([env_vec, mouse_stat_vec])
        tabular_score = self.tabular_model.predict_proba(combined_tabular_vec)

        # 4. Confidence-Based Adaptive Weighted Fusion
        if not has_enough_mouse_data:
            # Without sufficient mouse data, rely on env + heuristics
            w_h = 0.45
            w_t = 0.55
            w_l = 0.0
        else:
            # Base weights adjusted by confidence
            conf_lstm = self._compute_confidence_weight(lstm_score)
            conf_tab = self._compute_confidence_weight(tabular_score)
            conf_heur = self._compute_confidence_weight(heuristic_score)

            w_l = self.w_lstm * conf_lstm
            w_t = self.w_tabular * conf_tab
            w_h = self.w_heuristic * conf_heur

        total_w = w_l + w_t + w_h
        final_proba = (w_l * lstm_score + w_t * tabular_score + w_h * heuristic_score) / total_w

        # If critical hard rule triggered, elevate probability to >= 0.95
        if critical_flags:
            final_proba = max(final_proba, 0.96)

        is_bot = final_proba >= self.threshold

        # Calibrated verdict thresholds
        if final_proba >= 0.75:
            verdict = "BOT"
        elif final_proba >= 0.40:
            verdict = "SUSPECT"
        else:
            verdict = "HUMAN"

        confidence = abs(final_proba - 0.5) * 2.0  # 0.0 to 1.0

        return {
            "is_bot": is_bot,
            "verdict": verdict,
            "bot_probability": round(final_proba, 4),
            "confidence": round(confidence, 4),
            "reasons": reasons,
            "breakdown": {
                "behavioral_lstm_score": round(lstm_score, 4),
                "tabular_score": round(tabular_score, 4),
                "heuristic_score": round(heuristic_score, 4),
                "has_enough_mouse_data": has_enough_mouse_data,
                "mouse_points": len(records),
                "weights_used": {
                    "w_lstm": round(w_l / total_w, 3) if total_w > 0 else 0,
                    "w_tabular": round(w_t / total_w, 3) if total_w > 0 else 0,
                    "w_heuristic": round(w_h / total_w, 3) if total_w > 0 else 0,
                },
            },
        }
