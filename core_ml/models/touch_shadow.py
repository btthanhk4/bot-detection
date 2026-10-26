"""Shadow score for touch gestures, kept outside the release bundle.

The model (``core_ml/data/touch_shadow_model.json``, XGBoost JSON) is trained by
``python -m core_ml.train_touch``. It is reported next to the verdict and never
changes it: there is no validated mobile human baseline yet.
"""

import json
import logging
import os
import threading

import numpy as np

from core_ml.features.touch import MODEL_FEATURES, feature_vector, gesture_features, sanitize_gestures

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODEL_PATH = os.path.join(DATA_DIR, "touch_shadow_model.json")
META_PATH = os.path.join(DATA_DIR, "touch_shadow_meta.json")
MIN_SWIPES = 2

_lock = threading.Lock()
_state = {"loaded": False, "booster": None, "meta": None}


def _load():
    with _lock:
        if _state["loaded"]:
            return _state["booster"], _state["meta"]
        _state["loaded"] = True
        try:
            with open(META_PATH, encoding="utf-8") as handle:
                meta = json.load(handle)
            if tuple(meta.get("features") or ()) != MODEL_FEATURES:
                logger.warning("Touch shadow model features differ from this release; not loaded")
                return None, None
            import xgboost as xgb

            booster = xgb.Booster()
            booster.load_model(MODEL_PATH)
            _state["booster"], _state["meta"] = booster, meta
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("Touch shadow model could not be loaded")
        return _state["booster"], _state["meta"]


def score_touch(touch):
    """Mean bot probability over swipes, or None without a model or enough swipes."""
    booster, meta = _load()
    if booster is None:
        return None
    swipes = [f for f in (gesture_features(g["points"]) for g in sanitize_gestures(touch)) if f["kind"] == "swipe"]
    if len(swipes) < MIN_SWIPES:
        return {"model": meta.get("model_id"), "score": None, "swipes": len(swipes)}
    import xgboost as xgb

    matrix = xgb.DMatrix(np.asarray([feature_vector(f) for f in swipes], dtype=np.float32),
                         feature_names=list(MODEL_FEATURES))
    probabilities = booster.predict(matrix)
    return {
        "model": meta.get("model_id"),
        "score": round(float(np.mean(probabilities)), 4),
        "swipes": len(swipes),
    }
