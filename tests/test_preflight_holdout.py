"""Unit tests for frozen holdout helpers, with synthetic arrays only."""
import importlib.util
import sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

# Scripts import only existing installed quantlab research modules.
from evaluate_e002_holdout_once import metrics, test_hac as hac_comparison
from preflight_e002_holdout import checks_from_metadata
from quantlab.research.e002_funding import FUNDING_FEATURES
from quantlab.research.e002_ridge import FEATURES


def valid_meta():
    return {
        'holdout_evaluated':False, 'n_development':1716, 'n_holdout_reserved':429,
        'n_cv_predictions':1030, 'm1_features': list(FEATURES),
        'm2_incremental_funding_features':list(FUNDING_FEATURES),
        'm2_total_features':23, 'ridge_alpha':10.0,'label_purge_days':1,
        'source_feature_sha256':'example'
    }


def valid_audits():
    target = {'n_development':1716,'n_holdout_reserve':429,'holdout_target_evaluated':False}
    market = {'status':'PASS','n_total_feature_or_target_mismatches':0,'holdout_rows_parsed':False,'source_sha256':'example'}
    funding = {'reconstruction_passed':True,'holdout_labels_read':False,'source_feature_sha256':'example',
               'feature_comparisons':{f:{'mismatch_count':0} for f in FUNDING_FEATURES}}
    return target, market, funding


def test_metadata_frozen_passes():
    checks_from_metadata(valid_meta(), *valid_audits())


def test_metadata_fails_on_changed_features():
    bad = valid_meta(); bad['m2_incremental_funding_features'] = ['funding_mean']
    with pytest.raises(ValueError):
        checks_from_metadata(bad, *valid_audits())


def test_metadata_fails_on_missing_purge():
    bad = valid_meta(); bad['label_purge_days'] = 0
    with pytest.raises(ValueError):
        checks_from_metadata(bad, *valid_audits())


def test_metrics_expected():
    v = metrics(np.array([0.04,0.02]),np.array([0.03,0.03]))
    assert v['MAE'] == pytest.approx(0.01)
    assert v['RMSE'] == pytest.approx(0.01)


def test_hac_direction():
    y=np.linspace(0.01,0.06,50)
    b2=y+0.01
    m2=y+0.005
    h=hac_comparison(y,b2,m2)
    assert h['7']['mean_improvement_M2_over_B2'] > 0
