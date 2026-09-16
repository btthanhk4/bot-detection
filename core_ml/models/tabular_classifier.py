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
            # Enable early stopping only when validation set is provided
            self.model.set_params(early_stopping_rounds=30)

        self.model.fit(X_scaled, y, **fit_params)
        self.is_fitted = True
        return self

    def predict_proba(self, x_vector: np.ndarray) -> float:
        """
        Predict probability of being a BOT for a single sample (1D or 2D array).
        Returns float in [0.0, 1.0].
        """
        if x_vector is None:
            return 0.5

        # Clean NaN/Inf for numerical stability
        x_arr = np.nan_to_num(np.asarray(x_vector, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
        if x_arr.ndim == 1:
            sample = x_arr
        elif x_arr.ndim == 2 and x_arr.shape[0] == 1:
            sample = x_arr[0]
        else:
            return 0.5

        if not self.is_fitted:
            # Fallback heuristic: feature 0 is usually heuristic_score, feature 2 is flag_webdriver
            if len(sample) > 0:
                h_score = float(sample[0])
                flag_wd = float(sample[2]) if len(sample) > 2 else 0.0
                return min(1.0, h_score * 0.7 + flag_wd * 0.9)
            return 0.5

        x_arr = sample.reshape(1, -1)

        # A mismatched schema means these weights are not compatible. Silently
        # padding/truncating would attach values to the wrong feature names.
        expected_dim = getattr(self.scaler, "n_features_in_", x_arr.shape[1])
        if x_arr.shape[1] != expected_dim:
            return 0.5

        x_scaled = self.scaler.transform(x_arr)
        probas = self.model.predict_proba(x_scaled)
        probability = float(probas[0, 1])
        if not np.isfinite(probability):
            raise RuntimeError("Tabular model returned a non-finite probability")
        return max(0.0, min(1.0, probability))

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities for multiple samples."""
        if X is None or len(X) == 0:
            return np.array([], dtype=np.float32)

        X_arr = np.nan_to_num(np.asarray(X, dtype=np.float32), nan=0.0, posinf=100.0, neginf=-100.0)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(1, -1)
        elif X_arr.ndim != 2:
            return np.array([], dtype=np.float32)
        if not self.is_fitted:
            return np.full(X_arr.shape[0], 0.5)

        expected_dim = getattr(self.scaler, "n_features_in_", X_arr.shape[1])
        if X_arr.shape[1] != expected_dim:
            return np.full(X_arr.shape[0], 0.5)

        X_scaled = self.scaler.transform(X_arr)
        probabilities = np.asarray(self.model.predict_proba(X_scaled)[:, 1], dtype=np.float32)
        if not np.all(np.isfinite(probabilities)):
            raise RuntimeError("Tabular model returned non-finite probabilities")
        return np.clip(probabilities, 0.0, 1.0)

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

    def load(self, path: str, expected_feature_names: list = None) -> bool:
        if os.path.exists(path):
            try:
                data = joblib.load(path)
                self.model = data["model"]
                self.scaler = data.get("scaler", StandardScaler())
                self.is_fitted = data.get("fitted", False)
                self.feature_names = data.get("features", [])
                scaler_dim = int(getattr(self.scaler, "n_features_in_", 0) or 0)
                model_dim = int(getattr(self.model, "n_features_in_", 0) or 0)
                artifact_valid = bool(
                    self.is_fitted
                    and hasattr(self.scaler, "transform")
                    and hasattr(self.model, "predict_proba")
                    and scaler_dim > 0
                    and model_dim == scaler_dim
                    and (not self.feature_names or len(self.feature_names) == scaler_dim)
                    and (
                        expected_feature_names is None
                        or self.feature_names == list(expected_feature_names)
                    )
                )
                if not artifact_valid:
                    self.is_fitted = False
                return artifact_valid
            except Exception:
                self.is_fitted = False
                return False
        return False
