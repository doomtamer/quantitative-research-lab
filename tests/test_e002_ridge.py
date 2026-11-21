"""Unit tests: folds, train-local transformations, nonnegative range prediction."""
import numpy as np
import pandas as pd
import pytest

from quantlab.research.e002_ridge import FEATURES, cv_folds, fit_fold_predict


def synthetic_frame(n=120):
    rng = np.random.default_rng(27)
    out = pd.DataFrame({col: rng.normal(0.03, 0.01, n) for col in FEATURES})
    out["target_range"] = np.maximum(0.005, 0.04 + rng.normal(0, 0.01, n))
    return out


def test_fold_boundaries_match_e002_baselines():
    assert cv_folds(1716) == [(685, 686, 892), (891, 892, 1098), (1097, 1098, 1304),
                              (1303, 1304, 1510), (1509, 1510, 1716)]


def test_ridge_outputs_nonnegative():
    frame = synthetic_frame()
    predictions, n_negative = fit_fold_predict(frame, 69, 70, 100)
    assert predictions.shape == (30,)
    assert np.isfinite(predictions).all() and np.all(predictions >= 0)
    assert n_negative >= 0


def test_no_validation_target_leakage():
    frame = synthetic_frame()
    base, _ = fit_fold_predict(frame, 69, 70, 100)
    # Changing unknown future labels does not alter predictions.
    changed = frame.copy()
    changed.loc[69:, "target_range"] = 1000.0
    after, _ = fit_fold_predict(changed, 69, 70, 100)
    np.testing.assert_allclose(base, after, rtol=0, atol=1e-12)


def test_missing_in_training_and_no_future_imputation():
    frame = synthetic_frame()
    frame.loc[0:3, FEATURES[0]] = np.nan
    pred, _ = fit_fold_predict(frame, 69, 70, 100)
    assert np.isfinite(pred).all()
    frame.loc[75, FEATURES[0]] = np.nan
    with pytest.raises(ValueError, match="Missing features in validation"):
        fit_fold_predict(frame, 69, 70, 100)
