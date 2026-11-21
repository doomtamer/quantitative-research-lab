"""E002 M2: exact M1 Ridge methodology plus a fixed funding-rate feature set.

Development only; the caller must pass the frozen E002 development rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.research.e002_ridge import ALPHA, FEATURES as MARKET_FEATURES, make_pipeline

# Predeclare the E001 funding-feature family, without new feature selection.
FUNDING_FEATURES = (
    "funding_mean",
    "funding_std",
    "funding_mean_3d",
    "funding_mean_7d",
    "funding_mean_14d",
    "funding_mean_30d",
    "funding_z_30d",
)
M2_FEATURES = (*MARKET_FEATURES, *FUNDING_FEATURES)


def fit_fold_predict_m2(
    frame: pd.DataFrame, train_stop: int, valid_start: int, valid_stop: int
) -> tuple[np.ndarray, int]:
    """Fit M2 on training rows only; purge one label row; clip negative ranges.

    train_stop is exclusive; validation rows are [valid_start:valid_stop].
    All preprocessing is fitted independently in each training window.
    """
    if not 1 <= train_stop < valid_start < valid_stop <= len(frame):
        raise ValueError("Invalid fold boundaries or missing label purge")
    cols = list(M2_FEATURES)
    if not set(cols + ["target_range"]).issubset(frame.columns):
        raise ValueError("Missing M2 inputs")
    x_train = frame.iloc[:train_stop][cols].to_numpy(dtype=float)
    x_valid = frame.iloc[valid_start:valid_stop][cols].to_numpy(dtype=float)
    y_train = frame.iloc[:train_stop]["target_range"].to_numpy(dtype=float)
    if not np.isfinite(y_train).all() or (y_train < 0).any():
        raise ValueError("Invalid training target")
    if np.isinf(x_train).any() or np.isinf(x_valid).any():
        raise ValueError("Infinite feature values")
    if np.isnan(x_train).all(axis=0).any():
        raise ValueError("At least one feature entirely missing in training fold")
    if np.isnan(x_valid).any():
        raise ValueError("Missing features in validation; check time alignment")
    pipe = make_pipeline(alpha=ALPHA)
    pipe.fit(x_train, y_train)
    pred_raw = np.asarray(pipe.predict(x_valid), dtype=float)
    if not np.isfinite(pred_raw).all():
        raise ValueError("Nonfinite prediction")
    n_neg = int(np.count_nonzero(pred_raw < 0))
    return np.maximum(pred_raw, 0.0), n_neg
