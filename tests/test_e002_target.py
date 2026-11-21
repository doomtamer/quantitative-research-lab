import numpy as np
import pandas as pd

from quantlab.research.e002_target import next_day_range, observed_range, observed_range_features


def test_next_day_range_uses_future_high_low_and_current_close():
    hi = pd.Series([110.0, 120.0, 132.0])
    lo = pd.Series([90.0, 100.0, 120.0])
    close = pd.Series([100.0, 105.0, 125.0])
    y = next_day_range(hi, lo, close)
    assert np.isclose(y.iloc[0], (120 - 100) / 100)
    assert np.isclose(y.iloc[1], (132 - 120) / 105)
    assert np.isnan(y.iloc[2])


def test_observed_range_uses_previous_close_not_current_open():
    hi = pd.Series([110.0, 120.0, 132.0])
    lo = pd.Series([90.0, 100.0, 120.0])
    close = pd.Series([100.0, 105.0, 125.0])
    r = observed_range(hi, lo, close)
    assert pd.isna(r.iloc[0])
    assert np.isclose(r.iloc[1], 20 / 100)
    assert np.isclose(r.iloc[2], 12 / 105)


def test_baseline_features_never_use_future_data():
    hi = pd.Series([100.0 + i + 5 for i in range(50)])
    lo = pd.Series([100.0 + i - 5 for i in range(50)])
    close = pd.Series([100.0 + i for i in range(50)])
    initial = observed_range_features(hi, lo, close)
    # Perturb only tomorrow's H/L: ranges available through today must be unchanged.
    hi_new, lo_new = hi.copy(), lo.copy()
    hi_new.iloc[40] += 20
    lo_new.iloc[40] -= 20
    revised = observed_range_features(hi_new, lo_new, close)
    pd.testing.assert_frame_equal(initial.iloc[:40], revised.iloc[:40])
