"""E002 funding Ridge: fixed incremental features and no access to future labels."""
import numpy as np
import pandas as pd
import pytest

from quantlab.research.e002_funding import FUNDING_FEATURES, M2_FEATURES, fit_fold_predict_m2
from quantlab.research.e002_ridge import ALPHA, FEATURES


def frame(n=130):
    rng = np.random.default_rng(4321)
    result = pd.DataFrame({f: rng.normal(0.02, 0.005, n) for f in M2_FEATURES})
    result["target_range"] = np.maximum(0.001, rng.normal(0.045, 0.01, n))
    return result


def test_frozen_feature_family():
    assert len(FUNDING_FEATURES) == 7
    assert len(FEATURES) == 16
    assert len(M2_FEATURES) == 23
    assert len(set(M2_FEATURES)) == len(M2_FEATURES)
    assert not any(f.startswith("target_") for f in M2_FEATURES)
    assert ALPHA == 10.0


def test_nonnegative_finite_predictions():
    pred, n_negative = fit_fold_predict_m2(frame(), 79, 80, 110)
    assert pred.shape == (30,)
    assert np.isfinite(pred).all()
    assert np.all(pred >= 0)
    assert n_negative >= 0


def test_validation_labels_do_not_change_predictions():
    data = frame()
    base, _ = fit_fold_predict_m2(data, 79, 80, 110)
    changed = data.copy()
    changed.loc[79:, "target_range"] = 90.0
    result, _ = fit_fold_predict_m2(changed, 79, 80, 110)
    np.testing.assert_allclose(base, result, atol=1e-12, rtol=0)


def test_validation_funding_missing_is_not_imputed_from_future():
    data = frame()
    data.loc[87, FUNDING_FEATURES[0]] = np.nan
    with pytest.raises(ValueError, match="Missing features in validation"):
        fit_fold_predict_m2(data, 79, 80, 110)


def test_training_imputation_is_allowed():
    data = frame()
    data.loc[0:9, FUNDING_FEATURES[0]] = np.nan
    pred, _ = fit_fold_predict_m2(data, 79, 80, 110)
    assert np.isfinite(pred).all()
