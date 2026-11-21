import pandas as pd
import pytest
from quantlab.research.baseline import regression_baselines

def test_baseline():
    r = regression_baselines(pd.Series([.1, .2, -.1, 0, .05]), 3)
    assert r['zero_return']['test_observations'] == 2

def test_invalid_split():
    with pytest.raises(ValueError):
        regression_baselines(pd.Series([1, 2, 3]), 3)
