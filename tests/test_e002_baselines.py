import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

script = Path(__file__).resolve().parents[1] / "scripts/run_e002_baselines.py"
spec = importlib.util.spec_from_file_location("e002_baselines", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fold_geometry_and_one_day_gap():
    f = module.folds(1716)
    assert len(f) == 5
    assert [c - b for _, b, c in f] == [206] * 5
    assert [b - stop for stop, b, _ in f] == [1] * 5
    assert f[0] == (685, 686, 892)
    assert f[-1] == (1509, 1510, 1716)


def test_baselines_use_only_prior_known_labels_and_today_range():
    n = 1716
    dates = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    targets = np.linspace(0.01, 0.10, n)
    ranges = np.linspace(0.02, 0.07, n)
    df = pd.DataFrame({"date": dates, "target_range": targets,
                       "e002_range_today": ranges,
                       "e002_range_mean_7": pd.Series(ranges).rolling(7).mean(),
                       "e002_range_mean_30": pd.Series(ranges).rolling(30).mean()})
    m, d, p = module.evaluate(df)
    assert len(d) == 1030
    first = d.iloc[0]
    assert np.isclose(first["B0_train_mean"], targets[:685].mean())
    assert np.isclose(first["B1_persistence"], ranges[686])
    assert np.isclose(first["B2_mean_7"], ranges[680:687].mean())
    assert not m["MAE"].isna().any()
    assert not p["MAE"].isna().any()
