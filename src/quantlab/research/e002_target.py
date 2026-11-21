"""E002 target and point-in-time-compatible, observed-range baseline features.

For a row indexed by UTC day t, the prediction is made after t closes.
The E002 target is the HIGH-LOW width of t+1 normalized by close[t].
"""
from __future__ import annotations

import pandas as pd


def next_day_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """y[t] = (H[t+1] - L[t+1]) / C[t]; last day has no label."""
    return ((high.shift(-1) - low.shift(-1)) / close).rename("target_range")


def observed_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """R[t] = (H[t] - L[t]) / C[t-1]; known after close[t]."""
    return ((high - low) / close.shift(1)).rename("e002_range_today")


def observed_range_features(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.DataFrame:
    """Trailing averages include day t, never day t+1."""
    r = observed_range(high, low, close)
    return pd.DataFrame({
        "e002_range_today": r,
        "e002_range_mean_7": r.rolling(7, min_periods=7).mean(),
        "e002_range_mean_30": r.rolling(30, min_periods=30).mean(),
        "e002_range_std_30": r.rolling(30, min_periods=30).std(),
    })
