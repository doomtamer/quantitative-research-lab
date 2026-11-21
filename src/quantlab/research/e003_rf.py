"""Fixed-specification E003 Random Forest, using E002's frozen feature sets.

This is an exploratory development-only comparison, NOT confirmatory OOS research.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from quantlab.research.e002_ridge import FEATURES as MARKET_FEATURES
from quantlab.research.e002_funding import FUNDING_FEATURES

RF_FEATURES_MARKET = tuple(MARKET_FEATURES)
RF_FEATURES_FUNDING = tuple(MARKET_FEATURES) + tuple(FUNDING_FEATURES)

# Frozen before E003 predictions are produced; do not tune on same 1030 days.
RF_KWARGS = dict(
    n_estimators=300,
    max_depth=6,
    min_samples_leaf=20,
    max_features=0.8,
    bootstrap=True,
    random_state=2026,
    n_jobs=1,
)


def make_rf_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("rf", RandomForestRegressor(**RF_KWARGS)),
    ])


def predict_fold(frame: pd.DataFrame, features: tuple[str, ...],
                 train_stop: int, val_start: int, val_stop: int) -> tuple[np.ndarray, int]:
    """Train strictly on frame[:train_stop]; validate frame[val_start:val_stop].

    train_stop and val_stop are exclusive; one row must be purged.
    """
    if not (1 <= train_stop < val_start < val_stop <= len(frame)):
        raise ValueError("Invalid fold: next-day label must be purged")
    if len(features) != len(set(features)) or any(s.startswith("target_") for s in features):
        raise ValueError("Duplicate features or target leakage")
    if "target_range" not in frame or not set(features).issubset(frame.columns):
        raise ValueError("Missing target or model feature")
    y = frame.iloc[:train_stop]["target_range"].to_numpy(dtype=float)
    xtr = frame.iloc[:train_stop][list(features)].to_numpy(dtype=float)
    xvl = frame.iloc[val_start:val_stop][list(features)].to_numpy(dtype=float)
    if not np.isfinite(y).all() or np.any(y < 0):
        raise ValueError("Non-finite or negative training target")
    if np.isinf(xtr).any() or np.isinf(xvl).any():
        raise ValueError("Infinite feature value")
    if np.isnan(xtr).all(axis=0).any():
        raise ValueError("All-missing training feature column")
    if np.isnan(xvl).any():
        raise ValueError("Missing validation feature; check availability")
    pipe = make_rf_pipeline()
    pipe.fit(xtr, y)
    raw = np.asarray(pipe.predict(xvl), dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError("Nonfinite RF prediction")
    return np.maximum(raw, 0.0), int(np.sum(raw < 0))
