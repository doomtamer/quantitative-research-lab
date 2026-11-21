"""E002 development-only funding feature reconstruction and temporal checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

FUNDING_COLS = (
    "funding_mean", "funding_std", "funding_mean_3d", "funding_mean_7d",
    "funding_mean_14d", "funding_mean_30d", "funding_z_30d",
)


def reconstruct_funding(events: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Compute frozen E002 funding columns from raw settlement events through t only."""
    if dates.tz is None:
        raise ValueError("dates require a timezone")
    raw = events.copy()
    raw["funding_time"] = pd.to_datetime(raw["funding_time"], utc=True, format="mixed", errors="coerce")
    raw["funding_rate"] = pd.to_numeric(raw["funding_rate"], errors="coerce")
    if raw[["funding_time", "funding_rate"]].isna().any().any():
        raise ValueError("Raw funding contains invalid timestamps or rates")
    if raw["funding_time"].duplicated().any():
        raise ValueError("Duplicate event timestamps")
    raw = raw.loc[(raw["funding_time"] >= dates.min()) &
                  (raw["funding_time"] < dates.max() + pd.Timedelta(days=1))].copy()
    raw["date"] = raw["funding_time"].dt.normalize()
    counts = raw.groupby("date").size().reindex(dates)
    if counts.isna().any() or not counts.eq(3).all():
        bad = counts[counts.ne(3)].head(8).to_dict()
        raise ValueError(f"Expected exactly 3 events per development day; examples: {bad}")
    # A complete day has 00:00, 08:00 and 16:00 settlements (minor milliseconds tolerated).
    minute_of_day = raw["funding_time"].dt.hour * 60 + raw["funding_time"].dt.minute
    if not minute_of_day.isin([0, 480, 960]).all():
        raise ValueError("Funding event outside scheduled 00/08/16 UTC time")
    slots = raw.groupby("date")["funding_time"].apply(lambda s: sorted(s.dt.hour.tolist()))
    if not slots.apply(lambda x: x == [0, 8, 16]).all():
        raise ValueError("Daily funding slots are not [00,08,16]")
    if not (raw["funding_time"] < raw["date"] + pd.Timedelta(days=1)).all():
        raise ValueError("Future event crossed its feature day close")
    daily = raw.groupby("date")["funding_rate"].agg(["mean", "std"]).reindex(dates)
    mean = daily["mean"]
    s30 = mean.rolling(30)
    out = pd.DataFrame(index=dates)
    out["funding_mean"] = mean
    out["funding_std"] = daily["std"]
    for n in (3, 7, 14, 30):
        out[f"funding_mean_{n}d"] = mean.rolling(n).mean()
    out["funding_z_30d"] = (mean - s30.mean()) / s30.std().replace(0, np.nan)
    return out


def compare_funding(rebuilt: pd.DataFrame, stored: pd.DataFrame, atol: float = 1e-10) -> dict:
    """Reject any disagreement, including mismatches of NaN positions."""
    diagnostics = {}
    for col in FUNDING_COLS:
        expected = rebuilt[col].to_numpy(dtype=float)
        observed = pd.to_numeric(stored[col], errors="coerce").to_numpy(dtype=float)
        if len(expected) != len(observed):
            raise ValueError(f"{col}: length mismatch")
        nan_match = np.array_equal(np.isnan(expected), np.isnan(observed))
        close = np.isclose(expected, observed, atol=atol, rtol=1e-7, equal_nan=True)
        mismatch = int((~close).sum())
        finite = np.isfinite(expected) & np.isfinite(observed)
        max_diff = float(np.max(np.abs(expected[finite] - observed[finite]))) if finite.any() else None
        diagnostics[col] = {
            "mismatch_count": mismatch, "nan_positions_identical": nan_match,
            "max_absolute_difference": max_diff,
        }
        if mismatch or not nan_match:
            raise ValueError(f"Feature reconstruction mismatch: {col} ({mismatch} rows)")
    return diagnostics
