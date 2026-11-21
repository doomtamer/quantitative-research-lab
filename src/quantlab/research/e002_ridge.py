"""E002 range forecasting: one predeclared M1 Ridge versus B2 seven-day mean.

This module only accepts development rows supplied by its caller. Time-ordered
folds, 1-row label embargo, fold-local imputers/scalers and nonnegative outputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ALPHA = 10.0
# E001's frozen M1 market features, plus two contemporary range features
# justified by the E002 target protocol. No target_* or funding feature is used.
FEATURES = (
    "ret_1d", "ret_3d", "ret_7d", "ret_14d", "ret_30d",
    "vol_7d", "vol_14d", "vol_30d", "atr_14_pct",
    "candle_body", "candle_range", "volume_z_30d",
    "taker_buy_imbalance", "dist_ma_30d",
    "e002_range_today", "e002_range_mean_7",
)


def cv_folds(n: int, k: int = 5) -> list[tuple[int, int, int]]:
    """(train_stop_exclusive, validation_start, validation_stop_exclusive).

    One observation is purged to avoid using a target whose next-day candle is
    on the first validation feature date.
    """
    min_train = max(365, int(n * 0.4))
    if min_train >= n or n - min_train < k:
        raise ValueError("Development set too short")
    edges = np.linspace(min_train, n, k + 1).astype(int)
    return [(int(edges[i]) - 1, int(edges[i]), int(edges[i + 1])) for i in range(k)]


def make_pipeline(alpha: float = ALPHA) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=alpha)),
    ])


def fit_fold_predict(frame: pd.DataFrame, train_stop: int, valid_start: int, valid_stop: int) -> tuple[np.ndarray, int]:
    """Only train on rows before train_stop; output nonnegative range forecasts."""
    if not 1 <= train_stop < valid_start < valid_stop <= len(frame):
        raise ValueError("Invalid fold boundaries or missing label purge")
    if valid_start - train_stop < 1:
        raise ValueError("Training/validation gap required")
    cols = list(FEATURES)
    x_train = frame.iloc[:train_stop][cols].to_numpy(dtype=float)
    y_train = frame.iloc[:train_stop]["target_range"].to_numpy(dtype=float)
    x_valid = frame.iloc[valid_start:valid_stop][cols].to_numpy(dtype=float)
    if (not np.isfinite(y_train).all()) or (y_train < 0).any():
        raise ValueError("Training target invalid")
    if (np.isinf(x_train).any() or np.isinf(x_valid).any()):
        raise ValueError("Infinite feature values")
    # If a feature is entirely missing in the training fold, the fold is not
    # meaningful even if the imputer can replace it with zeros.
    if np.isnan(x_train).all(axis=0).any():
        raise ValueError("A feature is entirely missing from training fold")
    if np.isnan(x_valid).any():
        raise ValueError("Missing features in validation; check availability/time alignment")
    pipe = make_pipeline()
    pipe.fit(x_train, y_train)
    pred_raw = np.asarray(pipe.predict(x_valid), dtype=float)
    if not np.isfinite(pred_raw).all():
        raise ValueError("Nonfinite prediction")
    n_negative = int((pred_raw < 0).sum())
    return np.maximum(pred_raw, 0.0), n_negative
