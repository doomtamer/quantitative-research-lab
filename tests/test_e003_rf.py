"""Tests: fixed RF specification and no target/holdout leakage."""
import numpy as np
import pandas as pd
import pytest
from quantlab.research.e003_rf import (
    RF_FEATURES_MARKET, RF_FEATURES_FUNDING, RF_KWARGS, make_rf_pipeline,
    predict_fold,
)


def fake(n=90):
    r = np.random.default_rng(22)
    d = pd.DataFrame({k: r.normal(size=n) for k in RF_FEATURES_FUNDING})
    d["target_range"] = np.maximum(.005, .045 + .009 * r.normal(size=n))
    return d


def test_feature_sets():
    assert len(RF_FEATURES_MARKET) == 16
    assert len(RF_FEATURES_FUNDING) == 23
    assert len(set(RF_FEATURES_FUNDING)) == 23
    assert all(not f.startswith("target_") for f in RF_FEATURES_FUNDING)


def test_fixed_model_configuration():
    p = make_rf_pipeline()
    assert p.named_steps["rf"].get_params()["n_estimators"] == RF_KWARGS["n_estimators"]
    assert p.named_steps["rf"].get_params()["random_state"] == 2026


def test_same_predictions_after_validation_target_changes():
    frame = fake()
    a, _ = predict_fold(frame, RF_FEATURES_MARKET, 60, 61, 75)
    frame.loc[61:74, "target_range"] = 1000  # never allowed to affect fit
    b, _ = predict_fold(frame, RF_FEATURES_MARKET, 60, 61, 75)
    np.testing.assert_array_equal(a, b)
    assert (a >= 0).all()


def test_reject_training_on_first_validation_day():
    with pytest.raises(ValueError):
        predict_fold(fake(), RF_FEATURES_MARKET, 60, 60, 75)


def test_reject_target_as_feature():
    with pytest.raises(ValueError):
        predict_fold(fake(), ("target_range",), 60, 61, 75)


def test_training_only_imputation():
    frame = fake()
    col = RF_FEATURES_MARKET[0]
    frame.loc[3, col] = np.nan
    pred, _ = predict_fold(frame, RF_FEATURES_MARKET, 60, 61, 75)
    assert np.isfinite(pred).all()


def test_reject_future_missing_feature():
    frame = fake()
    frame.loc[65, RF_FEATURES_MARKET[0]] = np.nan
    with pytest.raises(ValueError):
        predict_fold(frame, RF_FEATURES_MARKET, 60, 61, 75)
