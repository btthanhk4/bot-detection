"""
Tabular Classifier for Environment & Aggregated Behavioral Features (v2)
========================================================================
Uses XGBoost with:
  - StandardScaler feature normalization
  - Improved hyperparameters (subsample, colsample_bytree)
  - scale_pos_weight for imbalanced datasets
  - SHAP-compatible feature importance
"""

import os
import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


class TabularBotClassifier:
    def __init__(
        self,
        n_estimators: int = 300,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        scale_pos_weight: float = 1.0,
        min_child_weight: int = 3,
    ):
        self.model = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            scale_pos_weight=scale_pos_weight,
            min_child_weight=min_child_weight,
            reg_alpha=0.1,    # L1 regularization
            reg_lambda=1.0,   # L2 regularization
            eval_metric="logloss",
            random_state=42,
        )
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.feature_names = []

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list = None,
            X_val: np.ndarray = None, y_val: np.ndarray = None):
        """
        Train classifier on feature matrix X (n_samples, n_features) and binary labels y (0=Human, 1=Bot).
        Optionally uses validation set for early stopping.
        """
        self.feature_names = feature_names or [f"f_{i}" for i in range(X.shape[1])]

        # Fit and transform with StandardScaler
        X_scaled = self.scaler.fit_transform(X)

        # Setup eval set for early stopping
        fit_params = {}
        if X_val is not None and y_val is not None:
            X_val_scaled = self.scaler.transform(X_val)
            fit_params["eval_set"] = [(X_val_scaled, y_val)]
            fit_params["verbose"] = False

        self.model.fit(X_scaled, y, **fit_params)
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

        # Apply scaler transform
        x_scaled = self.scaler.transform(x_vector)
        probas = self.model.predict_proba(x_scaled)
        # Probability of class 1 (Bot)
        return float(probas[0, 1])

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities for multiple samples."""
        if not self.is_fitted:
            return np.full(X.shape[0], 0.5)
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)[:, 1]

    def get_feature_importances(self) -> dict:
        if not self.is_fitted:
            return {}
        importances = self.model.feature_importances_
        return dict(sorted(zip(self.feature_names, importances), key=lambda x: x[1], reverse=True))

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "model": self.model,
            "scaler": self.scaler,
            "fitted": self.is_fitted,
            "features": self.feature_names,
        }, path)

    def load(self, path: str) -> bool:
        if os.path.exists(path):
            data = joblib.load(path)
            self.model = data["model"]
            self.scaler = data.get("scaler", StandardScaler())
            self.is_fitted = data["fitted"]
            self.feature_names = data.get("features", [])
            return True
        return False
