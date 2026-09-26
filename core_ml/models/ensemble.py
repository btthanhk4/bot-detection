"""
Multi-Modal Ensemble Bot Detector (v2)
=======================================
Fuses DELBOT-Mouse Behavioral BiLSTM, Tabular Environment XGBoost, and BotD Heuristic Rules.
The fused score is not probability-calibrated. Client heuristics are untrusted
signals, and a decision is deferred until an LSTM window can be constructed.
"""

import numpy as np
from core_ml.features.env_features import extract_env_vector, safe_bool, safe_float
from core_ml.features.mouse_features import (
    MAX_MOUSE_RECORDS,
    compute_statistical_features,
    extract_mouse_stat_vector,
    extract_sequential_chunks,
    records_to_chunks,
    sanitize_mouse_records,
)
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier


DECISION_POLICY_VERSION = "6"


class EnsembleBotDetector:
    def __init__(
        self,
        lstm_model: MouseTrajectoryLSTM = None,
        tabular_model: TabularBotClassifier = None,
        w_lstm: float = 0.40,
        w_tabular: float = 0.40,
        w_heuristic: float = 0.20,
        threshold: float = 0.93,
        suspect_threshold: float = 0.45,
        min_mouse_points_for_bot: int = 25,
        lstm_available: bool = True,
        tabular_available: bool = True,
    ):
        self.lstm_model = lstm_model or MouseTrajectoryLSTM()
        self.tabular_model = tabular_model or TabularBotClassifier()
        self.w_lstm = w_lstm
        self.w_tabular = w_tabular
        self.w_heuristic = w_heuristic
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self.suspect_threshold = max(0.0, min(self.threshold, float(suspect_threshold)))
        # A 24-transition LSTM window needs 25 move events.
        self.min_mouse_points_for_bot = max(25, int(min_mouse_points_for_bot))
        if self.min_mouse_points_for_bot > MAX_MOUSE_RECORDS:
            raise ValueError("Minimum mouse points cannot exceed the retained record window")
        self.lstm_available = bool(lstm_available)
        self.tabular_available = bool(tabular_available)

    @staticmethod
    def _sanitize_probability(score, default: float) -> float:
        """Return a finite probability so invalid model output cannot poison fusion weights."""
        numeric = safe_float(score, default)
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _require_model_probability(score, name: str) -> float:
        try:
            numeric = float(score)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(f"{name} returned an invalid probability") from exc
        if not np.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise RuntimeError(f"{name} returned an invalid probability")
        return numeric

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
        touch_record_count = sum(
            isinstance(record, dict) and record.get("source") == "touch"
            for record in records
        )
        mouse_records = [
            record for record in records
            if isinstance(record, dict) and record.get("source") != "touch"
        ]
        valid_mouse_records = sanitize_mouse_records(mouse_records)
        valid_moves = [record for record in valid_mouse_records if record["type"] == "move"]
        distinct_positions = len({(record["x"], record["y"]) for record in valid_moves})
        usable_trajectory = bool(
            valid_moves and valid_moves[-1]["time"] > valid_moves[0]["time"]
            and distinct_positions >= 5
        )
        user_agent = str(fingerprint.get("userAgent") or "").lower()
        unsupported_mobile = any(
            token in user_agent for token in ("mobile", "android", "iphone", "ipad", "ipod")
        )
        legacy_touch_ambiguous = (
            safe_float(fingerprint.get("maxTouchPoints"), 0.0) > 0
            and any(
                isinstance(record, dict) and record.get("type") == "move"
                and record.get("source") is None
                for record in records
            )
        )
        # Client-provided chunks are untrusted and can disagree with raw records.
        # Rebuild canonical windows server-side so data sufficiency cannot be spoofed.
        chunks = records_to_chunks(valid_mouse_records, chunk_size=24, stride=12)

        # Compute mouse stats ONCE — reused for both fallback logic and tabular vector
        mouse_stats = compute_statistical_features(valid_mouse_records)

        # 1. BotD Heuristics evaluation
        heuristic_score = self._sanitize_probability(botd.get("heuristicScore"), 0.0)
        raw_reasons = botd.get("reasons")
        reasons = [str(reason)[:256] for reason in raw_reasons[:20]] if isinstance(raw_reasons, list) else []
        detectors = botd.get("detectors") if isinstance(botd.get("detectors"), dict) else {}

        # These flags originate in the browser and are evidence, not proof.
        critical_flags = []
        is_webdriver = any(safe_bool(value) for value in (
            detectors.get("webdriver"), botd.get("webDriver"), botd.get("webdriver")
        ))
        if is_webdriver:
            critical_flags.append("Client-reported webdriver automation signal")
            heuristic_score = max(heuristic_score, 0.95)
        if any(safe_bool(value) for value in (
            detectors.get("distinctiveProperties"),
            detectors.get("chromeDriverGlobal"),
            botd.get("automationTool"),
        )):
            critical_flags.append("Client-reported automation framework signal")
            heuristic_score = max(heuristic_score, 0.95)
        if any(safe_bool(value) for value in (
            detectors.get("headlessUa"), detectors.get("headless"), botd.get("headless")
        )):
            critical_flags.append("Client-reported headless browser signal")
            heuristic_score = max(heuristic_score, 0.80)
        reasons.extend(critical_flags)

        # 2. Behavioral LSTM evaluation
        chunks_tensor = extract_sequential_chunks(chunks)
        has_enough_mouse_data = chunks_tensor.size(0) > 0
        lstm_score = 0.5
        if has_enough_mouse_data and self.lstm_available:
            lstm_score = self._require_model_probability(
                self.lstm_model.predict_session_proba(chunks_tensor), "LSTM"
            )
            if lstm_score > 0.70:
                reasons.append(f"Mouse dynamics exhibit robotic trajectory (LSTM score: {lstm_score:.2f})")

        # 3. Tabular model evaluation (Canonical single source of truth vector)
        env_vec = extract_env_vector(fingerprint, botd)
        mouse_stat_vec = extract_mouse_stat_vector(mouse_stats)
        combined_tabular_vec = np.concatenate([env_vec, mouse_stat_vec])
        tabular_score = self._require_model_probability(
            self.tabular_model.predict_proba(combined_tabular_vec), "Tabular model"
        ) if self.tabular_available else 0.5

        heuristic_score = self._sanitize_probability(heuristic_score, 0.0)

        # BotD is positive evidence only. Its absence cannot dilute strong ML evidence.
        w_l = max(0.0, self.w_lstm) if self.lstm_available and has_enough_mouse_data else 0.0
        w_t = max(0.0, self.w_tabular) if self.tabular_available else 0.0
        ml_total = w_l + w_t
        baseline = (w_l * lstm_score + w_t * tabular_score) / ml_total if ml_total > 0 else 0.5
        heuristic_weight = min(1.0, max(0.0, self.w_heuristic) * heuristic_score)
        final_proba = baseline + (1.0 - baseline) * heuristic_weight

        # The full-session models are not validated for partial trajectories.
        # A client-reported automation flag cannot bypass this evidence gate.
        move_point_count = int(mouse_stats.get("move_point_count", 0))
        decision_deferred = (
            move_point_count < self.min_mouse_points_for_bot or not has_enough_mouse_data
            or not usable_trajectory
            or not self.lstm_available or not self.tabular_available
            or unsupported_mobile or legacy_touch_ambiguous
        )
        if decision_deferred:
            if not self.lstm_available or not self.tabular_available:
                reasons.append("Decision deferred: required model unavailable")
            elif unsupported_mobile:
                reasons.append("Decision deferred: mobile or tablet input is outside the trained mouse domain")
            elif legacy_touch_ambiguous:
                reasons.append("Decision deferred: legacy touch-capable input has no pointer source")
            elif touch_record_count and not move_point_count:
                reasons.append("Decision deferred: touch trajectory is outside the mouse model domain")
            elif not usable_trajectory and move_point_count >= self.min_mouse_points_for_bot:
                reasons.append("Decision deferred: mouse trajectory has insufficient spatial or temporal variation")
            else:
                reasons.append(
                    f"Decision deferred: need {self.min_mouse_points_for_bot} valid mouse move points "
                    f"(received {move_point_count})"
                )

        # Thresholds are deployment settings and must match the reported decision policy.
        if decision_deferred:
            verdict = "SUSPECT"
        elif final_proba >= self.threshold:
            verdict = "BOT"
        elif final_proba >= self.suspect_threshold or critical_flags:
            verdict = "SUSPECT"
        else:
            verdict = "HUMAN"

        # is_bot aligns with verdict (not a separate threshold)
        is_bot = (verdict == "BOT")

        confidence = abs(final_proba - 0.5) * 2.0  # Score margin, not calibrated confidence.

        return {
            "is_bot": is_bot,
            "verdict": verdict,
            "bot_probability": round(final_proba, 4),
            "risk_score": round(final_proba, 4),
            "score_calibrated": False,
            "policy_version": DECISION_POLICY_VERSION,
            "decision_state": "INSUFFICIENT_EVIDENCE" if decision_deferred else "FINAL",
            "confidence": round(confidence, 4),
            "reasons": reasons,
            "breakdown": {
                "behavioral_lstm_score": round(lstm_score, 4),
                "tabular_score": round(tabular_score, 4),
                "heuristic_score": round(heuristic_score, 4),
                "has_enough_mouse_data": has_enough_mouse_data,
                "usable_trajectory": usable_trajectory,
                "distinct_positions": distinct_positions,
                "mouse_points": move_point_count,
                "records_received": len(records),
                "touch_records_excluded": touch_record_count,
                "unsupported_mobile": unsupported_mobile,
                "legacy_touch_ambiguous": legacy_touch_ambiguous,
                "decision_deferred": decision_deferred,
                "minimum_mouse_points": self.min_mouse_points_for_bot,
                "weights_used": {
                    "w_lstm": round((1 - heuristic_weight) * w_l / ml_total, 3) if ml_total else 0,
                    "w_tabular": round((1 - heuristic_weight) * w_t / ml_total, 3) if ml_total else 0,
                    "w_heuristic": round(heuristic_weight, 3),
                },
                "fusion_baseline": round(baseline, 4),
                "heuristic_lift": round(final_proba - baseline, 4),
            },
        }
