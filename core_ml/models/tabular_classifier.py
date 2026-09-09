"""
Tabular Classifier for Environment & Aggregated Behavioral Features
Uses XGBoost / Random Forest on combined FingerprintJS, BotD, and Mouse Statistical features.
"""

import os
import joblib
import numpy as np
from xgboost import XGBClassifier


class TabularBotClassifier:
    def __init__(self, n_estimators: int = 150, max_depth: int = 5, learning_rate: float = 0.05):
        self.model = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            eval_metric="logloss",
            random_state=42,
        )
        self.is_fitted = False
        self.feature_names = []

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list = None):
        """
        Train classifier on feature matrix X (n_samples, n_features) and binary labels y (0=Human, 1=Bot)
        """
        self.feature_names = feature_names or [f"f_{i}" for i in range(X.shape[1])]
        self.model.fit(X, y)
        self.is_fitted = True
        return self

    def predict_proba(self, x_vector: np.ndarray) -> float:
        """
        Predict probability of being a BOT for a single sample (1D or 2D array).
        Returns float in [0.0, 1.0].
        """
        if not self.is_fitted:
            # Fallback heuristic: feature 0 is usually heuristic_score, feature 2 is flag_webdriver
            if x_vector is not None and len(x_vector) > 0:
                h_score = float(x_vector[0])
                flag_wd = float(x_vector[2]) if len(x_vector) > 2 else 0.0
                return min(1.0, h_score * 0.7 + flag_wd * 0.9)
            return 0.5

        if x_vector.ndim == 1:
            x_vector = x_vector.reshape(1, -1)

        probas = self.model.predict_proba(x_vector)
        # Probability of class 1 (Bot)
        return float(probas[0, 1])

    def get_feature_importances(self) -> dict:
        if not self.is_fitted:
            return {}
        importances = self.model.feature_importances_
        return dict(sorted(zip(self.feature_names, importances), key=lambda x: x[1], reverse=True))

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({"model": self.model, "fitted": self.is_fitted, "features": self.feature_names}, path)

    def load(self, path: str) -> bool:
        if os.path.exists(path):
            data = joblib.load(path)
            self.model = data["model"]
            self.is_fitted = data["fitted"]
            self.feature_names = data.get("features", [])
            return True
        return False
