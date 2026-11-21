"""Synthetic tests for E002 development funding reconstruction."""
import numpy as np
import pandas as pd
import pytest
from quantlab.research.e002_pit import FUNDING_COLS, compare_funding, reconstruct_funding


def sample(n=40):
    days = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    events = []
    for k, day in enumerate(days):
        for hour in (0, 8, 16):
            events.append({"funding_time": day + pd.Timedelta(hours=hour), "funding_rate": (k+hour/10) / 1e6})
    return days, pd.DataFrame(events)


def test_reconstruct_past_only():
    days, events = sample()
    d = reconstruct_funding(events, days)
    assert set(FUNDING_COLS) == set(d.columns)
    assert np.isclose(d["funding_mean"].iloc[2], (2+0.8)/1e6)
    assert np.isnan(d["funding_mean_7d"].iloc[5])
    assert np.isfinite(d["funding_mean_7d"].iloc[6])
    assert np.isfinite(d["funding_z_30d"].iloc[30])
    assert all(v["mismatch_count"] == 0 for v in compare_funding(d, d).values())


def test_reject_duplicate_and_missing_slot():
    days, events = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        reconstruct_funding(pd.concat([events, events.iloc[:1]], ignore_index=True), days)
    with pytest.raises(ValueError, match="exactly 3"):
        reconstruct_funding(events.iloc[1:], days)


def test_reject_feature_tampering():
    days, events = sample()
    reconstructed = reconstruct_funding(events, days)
    changed = reconstructed.copy()
    changed.loc[days[10], "funding_mean"] += 0.0001
    with pytest.raises(ValueError, match="mismatch"):
        compare_funding(reconstructed, changed)
