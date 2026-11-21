"""Regression tests for E002 preflight's split feature storage."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from preflight_e002_holdout import load_development_inputs
from quantlab.research.e002_ridge import FEATURES
from quantlab.research.e002_funding import FUNDING_FEATURES


def create_inputs(tmp_path, *, misaligned=False):
    dates = pd.date_range('2021-01-01', periods=4, freq='D', tz='UTC')
    derived_cols = {'e002_range_today', 'e002_range_mean_7'}
    source_cols = [c for c in FEATURES if c not in derived_cols] + list(FUNDING_FEATURES)
    source = pd.DataFrame({'date': dates, **{name: [0.1]*4 for name in source_cols}})
    development = pd.DataFrame({
        'date': dates + (pd.Timedelta(days=1) if misaligned else pd.Timedelta(0)),
        'e002_range_today': [None, 0.01, 0.02, 0.03],
        'e002_range_mean_7': [None, None, None, 0.02],
        'target_range': [0.05] * 4,
    })
    a = tmp_path / 'btc_daily_features.csv'
    b = tmp_path / 'e002_development_target.csv'
    source.to_csv(a, index=False)
    development.to_csv(b, index=False)
    return a, b


def test_preflight_can_join_derived_features_not_in_base_csv(tmp_path):
    source, derived = create_inputs(tmp_path)
    loaded = load_development_inputs(source, derived, n=4)
    assert all(c in loaded.columns for c in FEATURES)
    assert all(c in loaded.columns for c in FUNDING_FEATURES)
    assert 'target_range' not in loaded.columns
    assert loaded['e002_range_today'].iloc[-1] == pytest.approx(0.03)
    assert loaded['e002_range_mean_7'].iloc[-1] == pytest.approx(0.02)


def test_preflight_rejects_misaligned_dates(tmp_path):
    source, derived = create_inputs(tmp_path, misaligned=True)
    with pytest.raises(ValueError, match='do not align'):
        load_development_inputs(source, derived, n=4)


def test_preflight_rejects_incomplete_dev_rows(tmp_path):
    source, derived = create_inputs(tmp_path)
    with pytest.raises(ValueError, match='Incomplete'):
        load_development_inputs(source, derived, n=5)
