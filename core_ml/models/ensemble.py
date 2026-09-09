"""
Multi-Modal Ensemble Bot Detector
Fuses DELBOT-Mouse Behavioral LSTM, Tabular Environment XGBoost, and BotD Heuristic Rules.
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

    def predict(self, telemetry_payload: dict) -> dict:
        """
        Takes raw telemetry JSON payload from collector and outputs unified decision.
        """
        fingerprint = telemetry_payload.get("fingerprint", {})
        botd = telemetry_payload.get("botd", {})
        mouse = telemetry_payload.get("mouse", {})

        records = mouse.get("records", [])
        chunks = mouse.get("chunks", [])

        # 1. BotD Heuristics evaluation
        heuristic_score = float(botd.get("heuristicScore", 0.0))
        reasons = list(botd.get("reasons", []))
        detectors = botd.get("detectors", {})

        # Immediate hard rule triggers (100% confidence bot flags)
        if detectors.get("webdriver", False):
            reasons.append("Critical: Webdriver automation flag confirmed")
        if detectors.get("distinctiveProperties", False):
            reasons.append("Critical: Automation framework signature detected")

        # 2. Behavioral LSTM evaluation
        chunks_tensor = extract_sequential_chunks(chunks)
        has_enough_mouse_data = chunks_tensor.size(0) > 0
        if has_enough_mouse_data:
            lstm_score = self.lstm_model.predict_session_proba(chunks_tensor)
            if lstm_score > 0.70:
                reasons.append(f"Mouse dynamics exhibit robotic trajectory (LSTM score: {lstm_score:.2f})")
        else:
            # If user hasn't moved mouse yet, use mouse stats or default
            stats = compute_statistical_features(records)
            if stats["straightness"] > 0.98 and stats["point_count"] > 5:
                lstm_score = 0.85
                reasons.append("Unnaturally straight mouse trajectory")
            else:
                lstm_score = 0.50  # neutral

        # 3. Tabular model evaluation
        env_vec = extract_env_vector(fingerprint, botd)
        mouse_stats = compute_statistical_features(records)
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
            ],
            dtype=np.float32,
        )
        combined_tabular_vec = np.concatenate([env_vec, mouse_stat_vec])
        tabular_score = self.tabular_model.predict_proba(combined_tabular_vec)

        # 4. Weighted Fusion
        # Adjust weights dynamically if mouse data is insufficient
        if not has_enough_mouse_data:
            w_h = 0.45
            w_t = 0.55
            w_l = 0.0
        else:
            w_l = self.w_lstm
            w_t = self.w_tabular
            w_h = self.w_heuristic

        total_w = w_l + w_t + w_h
        final_proba = (w_l * lstm_score + w_t * tabular_score + w_h * heuristic_score) / total_w

        # If critical hard rule triggered, elevate probability to >= 0.95
        if detectors.get("webdriver", False) or detectors.get("distinctiveProperties", False):
            final_proba = max(final_proba, 0.96)

        is_bot = final_proba >= self.threshold

        if final_proba >= 0.75:
            verdict = "BOT"
        elif final_proba >= 0.45:
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
            },
        }
