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
from core_ml.features.mouse_features import compute_statistical_features, extract_sequential_chunks, extract_mouse_stat_vector
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
        threshold: float = 0.70,
        suspect_threshold: float = 0.45,
    ):
        self.lstm_model = lstm_model or MouseTrajectoryLSTM()
        self.tabular_model = tabular_model or TabularBotClassifier()
        self.w_lstm = w_lstm
        self.w_tabular = w_tabular
        self.w_heuristic = w_heuristic
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self.suspect_threshold = max(0.0, min(self.threshold, float(suspect_threshold)))

    def _compute_confidence_weight(self, score: float) -> float:
        """Higher confidence (further from 0.5) → higher weight."""
        return abs(score - 0.5) * 2.0 + 0.3  # min weight = 0.3

    def predict(self, telemetry_payload: dict) -> dict:
        """
        Takes raw telemetry JSON payload from collector and outputs unified decision.
        Completely safe against None, empty dicts, missing keys, or malformed data.
        """
        payload = telemetry_payload if isinstance(telemetry_payload, dict) else {}
        fingerprint = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
        botd = payload.get("botd") if isinstance(payload.get("botd"), dict) else {}
        mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}

        raw_records = mouse.get("records") or mouse.get("trajectory")
        records = raw_records if isinstance(raw_records, list) else []
        chunks = mouse.get("chunks") if isinstance(mouse.get("chunks"), list) else []

        # Compute mouse stats ONCE — reused for both fallback logic and tabular vector
        mouse_stats = compute_statistical_features(records)

        # 1. BotD Heuristics evaluation
        try:
            raw_h_score = float(botd.get("heuristicScore") or 0.0)
        except (ValueError, TypeError):
            raw_h_score = 0.0
        heuristic_score = max(0.0, min(1.0, raw_h_score))
        raw_reasons = botd.get("reasons")
        reasons = [str(reason)[:256] for reason in raw_reasons[:20]] if isinstance(raw_reasons, list) else []
        detectors = botd.get("detectors") if isinstance(botd.get("detectors"), dict) else {}

        # Immediate hard rule triggers (100% confidence bot flags)
        critical_flags = []
        is_webdriver = detectors.get("webdriver", False) or botd.get("webDriver", False) or botd.get("webdriver", False)
        if is_webdriver:
            critical_flags.append("Critical: Webdriver automation flag confirmed")
            heuristic_score = max(heuristic_score, 0.95)
        if detectors.get("distinctiveProperties", False) or botd.get("automationTool", False):
            critical_flags.append("Critical: Automation framework signature detected")
            heuristic_score = max(heuristic_score, 0.95)
        if detectors.get("headlessUa", False) or detectors.get("headless", False) or botd.get("headless", False):
            critical_flags.append("Headless browser environment detected")
            heuristic_score = max(heuristic_score, 0.80)
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
            if mouse_stats.get("move_point_count", 0) > 5:
                if mouse_stats.get("straightness", 0.0) > 0.98:
                    lstm_score = 0.80
                    reasons.append("Unnaturally straight mouse trajectory")
                elif mouse_stats.get("time_regularity", 1.0) < 0.05 and mouse_stats.get("point_count", 0) > 10:
                    lstm_score = 0.75
                    reasons.append("Suspiciously regular timing between mouse events")
                else:
                    lstm_score = 0.50  # neutral
            else:
                lstm_score = 0.50  # neutral

        # 3. Tabular model evaluation (Canonical single source of truth vector)
        env_vec = extract_env_vector(fingerprint, botd)
        mouse_stat_vec = extract_mouse_stat_vector(mouse_stats)
        combined_tabular_vec = np.concatenate([env_vec, mouse_stat_vec])
        tabular_score = self.tabular_model.predict_proba(combined_tabular_vec)

        # 4. Confidence-Based Adaptive Weighted Fusion
        if not has_enough_mouse_data:
            # Without full 24-point chunks, check if partial mouse trajectory exists
            if mouse_stats.get("move_point_count", 0) >= 5:
                w_l = 0.15 * self._compute_confidence_weight(lstm_score)
                w_t = 0.50 * self._compute_confidence_weight(tabular_score)
                w_h = 0.35 * self._compute_confidence_weight(heuristic_score)
            else:
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

        # Clean scores against NaN
        lstm_score = float(np.nan_to_num(lstm_score, nan=0.5))
        tabular_score = float(np.nan_to_num(tabular_score, nan=0.5))
        heuristic_score = float(np.nan_to_num(heuristic_score, nan=0.0))

        total_w = w_l + w_t + w_h
        final_proba = (w_l * lstm_score + w_t * tabular_score + w_h * heuristic_score) / total_w if total_w > 1e-6 else 0.5

        # If critical hard rule triggered, elevate probability to >= 0.95
        if critical_flags:
            final_proba = max(final_proba, 0.96)

        # No-mouse penalty: real users almost always generate mouse movement
        # If a session has zero mouse data and no critical flags, apply mild bot suspicion
        if mouse_stats.get("move_point_count", 0) == 0 and not critical_flags:
            final_proba = min(1.0, final_proba + 0.05)

        final_proba = max(0.0, min(1.0, float(final_proba)))

        # Thresholds are deployment settings and must match the reported decision policy.
        if final_proba >= self.threshold:
            verdict = "BOT"
        elif final_proba >= self.suspect_threshold:
            verdict = "SUSPECT"
        else:
            verdict = "HUMAN"

        # is_bot aligns with verdict (not a separate threshold)
        is_bot = (verdict == "BOT")

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
