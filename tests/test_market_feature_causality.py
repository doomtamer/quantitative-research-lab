import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/audit_market_feature_causality.py"
spec = importlib.util.spec_from_file_location("market_feature_audit", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_raw(n=90):
    x = np.arange(n, dtype=float)
    close = 100 + x + 2 * np.sin(x / 5)
    opening = close - 0.5
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC").astype(str),
        "open": opening,
        "high": close + 2,
        "low": opening - 2,
        "close": close,
        "volume": 1000 + 20*x + np.cos(x)*3,
        "taker_buy_base_volume": (1000 + 20*x + np.cos(x)*3)*0.53,
    })


def test_causal_reconstruction_prefix_invariance():
    raw = fixture_raw()
    full = module.reconstructed_market(raw)
    for t in [35, 60, 89]:
        prefix = module.reconstructed_market(raw.iloc[:t+1])
        for col in full:
            a = full.loc[t, col]
            b = prefix.loc[t, col]
            assert np.isclose(a, b, rtol=1e-10, atol=1e-10, equal_nan=True), col


def test_all_market_features_match_when_stored_correctly():
    raw = fixture_raw()
    f = module.reconstructed_market(raw)
    res = module.compare_columns(f, f.copy(), list(f))
    assert sum(x["mismatches"] for x in res.values()) == 0


def test_one_day_future_value_detected():
    raw = fixture_raw()
    expected = module.reconstructed_market(raw)
    tampered = expected.copy()
    tampered["ret_1d"] = tampered["ret_1d"].shift(-1)
    res = module.compare_columns(tampered, expected, ["ret_1d"])
    assert res["ret_1d"]["mismatches"] > 0


def test_date_gap_detected():
    raw = fixture_raw(10)
    a = raw.copy()
    a.loc[5:, "date"] = pd.date_range("2024-01-07", periods=5, freq="D", tz="UTC").astype(str)
    with pytest.raises(ValueError):
        module.validate_dates(a, raw, raw)
