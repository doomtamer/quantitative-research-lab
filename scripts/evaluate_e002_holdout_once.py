#!/usr/bin/env python3
"""ONE-TIME E002 final holdout evaluation.

DO NOT RUN UNTIL PRE-FLIGHT HAS BEEN REVIEWED.  After a one-time marker is
created, a second run is refused, even if an error occurs. Any recovery must
be reviewed explicitly, never automatic. No hyperparameter search is performed.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from quantlab.research.e002_ridge import ALPHA, make_pipeline
from quantlab.research.e002_funding import M2_FEATURES
from quantlab.research.e002_target import observed_range_features

from preflight_e002_holdout import ROOT, OUT, EVAL_DIR, FILE_LIST, sha256

SOURCE = ROOT / 'data/processed/btc_daily_features.csv'
RAW = ROOT / 'data/processed/btc_daily_raw.csv'
DEV = ROOT / 'data/processed/e002_development_target.csv'
MARKER = EVAL_DIR / 'ATTEMPT_STARTED.json'


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    actual, pred = np.asarray(actual, dtype=float), np.asarray(pred, dtype=float)
    if len(actual) == 0 or len(actual) != len(pred) or not np.isfinite(actual).all() or not np.isfinite(pred).all():
        raise ValueError('Invalid arrays for metric')
    error = actual - pred
    return {'MAE': float(np.abs(error).mean()), 'RMSE': float(np.sqrt(np.mean(error ** 2)))}


def test_hac(actual: np.ndarray, b2: np.ndarray, m2: np.ndarray, lags=(7, 14, 30)) -> dict:
    diff = np.abs(actual-b2) - np.abs(actual-m2)
    out = {}
    for lag in lags:
        model = sm.OLS(diff, np.ones((len(diff),1))).fit(cov_type='HAC', cov_kwds={'maxlags':lag})
        out[str(lag)] = {
            'mean_improvement_M2_over_B2': float(diff.mean()),
            't': float(model.tvalues[0]),
            'p_two_sided': float(model.pvalues[0]),
            'ci95': [float(v) for v in model.conf_int()[0]],
        }
    return out


def assert_manifest() -> dict:
    if not OUT.is_file():
        raise FileNotFoundError('Missing frozen manifest. Run preflight first.')
    frozen = json.loads(OUT.read_text(encoding='utf-8'))
    if frozen.get('status') != 'PREFLIGHT_PASSED' or frozen.get('publication_time_proven') is not False:
        raise ValueError('Frozen manifest invalid')
    if set(frozen.get('files_sha256', {})) != set(FILE_LIST):
        raise ValueError('Frozen manifest file list does not match evaluator')
    for rel, expected in frozen['files_sha256'].items():
        if sha256(ROOT / rel) != expected:
            raise ValueError(f'File changed since frozen preflight: {rel}')
    if (frozen.get('n_training'), frozen.get('n_holdout'), frozen.get('purged_feature_date')) != (1715, 429, '2025-09-12'):
        raise ValueError('Manifest partition changed')
    if list(frozen.get('feature_names_M2', [])) != list(M2_FEATURES) or float(frozen.get('model_alpha', -1)) != ALPHA:
        raise ValueError('Frozen model specification differs')
    return frozen


def evaluate() -> None:
    frozen = assert_manifest()  # uses SHA-256 of data only, does not parse holdout labels
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    # Create a permanent guard BEFORE parsing any holdout target. Never remove automatically.
    with MARKER.open('x', encoding='utf-8') as f:
        json.dump({'started_utc': datetime.now(timezone.utc).isoformat(),
                   'frozen_manifest_sha256': sha256(OUT),
                   'note': 'One-time evaluation started. Do not repeat even if interrupted.'}, f, indent=2)

    source = pd.read_csv(SOURCE)
    raw = pd.read_csv(RAW, usecols=['date','open','high','low','close'])
    dev = pd.read_csv(DEV, nrows=1715, usecols=['date','target_range'])
    if len(source) != 2145 or len(raw) != 2146 or len(dev) != 1715:
        raise ValueError('Unexpected data size')
    date_s = pd.to_datetime(source['date'], utc=True, errors='coerce')
    date_r = pd.to_datetime(raw['date'], utc=True, errors='coerce')
    date_d = pd.to_datetime(dev['date'], utc=True, errors='coerce')
    for dates in (date_s, date_r, date_d):
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ValueError('Malformed chronological index')
        if not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
            raise ValueError('Date continuity failure')
    if not date_s.reset_index(drop=True).equals(date_r.iloc[:-1].reset_index(drop=True)):
        raise ValueError('Raw and feature dates differ')
    if not date_s.iloc[:1715].reset_index(drop=True).equals(date_d.reset_index(drop=True)):
        raise ValueError('Development training dates differ')
    if date_s.iloc[1715].date().isoformat() != '2025-09-12' or date_s.iloc[1716].date().isoformat() != '2025-09-13':
        raise ValueError('Holdout boundary invalid')
    if date_s.iloc[-1].date().isoformat() != '2026-11-15':
        raise ValueError('Holdout endpoint invalid')
    for col in ['open','high','low','close']:
        raw[col] = pd.to_numeric(raw[col], errors='coerce')
    if not np.isfinite(raw[['open','high','low','close']].to_numpy()).all():
        raise ValueError('Raw candle nonfinite')
    if (raw[['open','high','low','close']] <= 0).any().any():
        raise ValueError('Raw candle nonpositive')
    if (raw['high'] < raw[['open','close']].max(axis=1)).any() or (raw['low'] > raw[['open','close']].min(axis=1)).any():
        raise ValueError('Raw OHLC inconsistent')

    # Observed candle t known after UTC day t close. No t+1 inputs are used.
    observed = observed_range_features(raw['high'],raw['low'],raw['close']).iloc[:-1].reset_index(drop=True)
    for col in ('e002_range_today','e002_range_mean_7'):
        source[col] = observed[col]
    holdout = source.iloc[1716:].copy()
    if len(holdout) != 429:
        raise ValueError('Holdout count invalid')
    y_holdout = pd.to_numeric(holdout['target_range'], errors='coerce').to_numpy(dtype=float)
    if not np.isfinite(y_holdout).all() or (y_holdout < 0).any():
        raise ValueError('Holdout target invalid')
    # Independent target formula verification using next-day market candles.
    expected_y = ((raw['high'].shift(-1) - raw['low'].shift(-1)) / raw['close']).iloc[1716:2145].to_numpy(dtype=float)
    if not np.allclose(y_holdout,expected_y,rtol=1e-9,atol=1e-10):
        raise ValueError('Holdout target inconsistent with raw OHLC')

    b2 = pd.to_numeric(holdout['e002_range_mean_7'], errors='coerce').to_numpy(dtype=float)
    if not np.isfinite(b2).all():
        raise ValueError('B2 unavailable on holdout')
    x_train = source.iloc[:1715][list(M2_FEATURES)].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    x_test = holdout[list(M2_FEATURES)].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    y_train = pd.to_numeric(dev['target_range'], errors='coerce').to_numpy(dtype=float)
    if not np.isfinite(y_train).all() or (y_train < 0).any():
        raise ValueError('Training labels invalid')
    if np.isinf(x_train).any() or np.isinf(x_test).any() or np.isnan(x_train).all(axis=0).any():
        raise ValueError('Invalid training or test features')
    if np.isnan(x_test).any():
        raise ValueError('M2 holdout features missing; no post-hoc filling allowed beyond frozen pipeline')
    pipe = make_pipeline(alpha=ALPHA)
    pipe.fit(x_train, y_train)
    predicted_raw = np.asarray(pipe.predict(x_test), dtype=float)
    if not np.isfinite(predicted_raw).all():
        raise ValueError('Nonfinite predictions')
    m2 = np.maximum(predicted_raw, 0.0)
    stats = {'B2_mean_7': metrics(y_holdout,b2), 'M2_market_funding_ridge': metrics(y_holdout,m2)}
    hac = test_hac(y_holdout,b2,m2)
    out = pd.DataFrame({
        'date': date_s.iloc[1716:].dt.strftime('%Y-%m-%d').to_numpy(),
        'actual': y_holdout,
        'B2_mean_7': b2,
        'M2_market_funding_ridge': m2,
    })
    out.to_csv(EVAL_DIR / 'holdout_predictions.csv', index=False)
    summary = {
        'status': 'FINAL_HOLDOUT_EVALUATED_ONCE',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'n_training':1715, 'purged_day':'2025-09-12',
        'n_holdout':len(out), 'first_date':out['date'].iloc[0], 'last_date':out['date'].iloc[-1],
        'target':'(high[t+1]-low[t+1])/close[t]',
        'model_primary':'B2_mean_7','model_secondary':'M2_market_funding_ridge',
        'model_alpha':ALPHA, 'n_features':len(M2_FEATURES),
        'n_negative_raw_ridge_forecasts':int((predicted_raw < 0).sum()),
        'metrics':stats, 'paired_absolute_loss_HAC':hac,
        'evaluation_manifest_sha256':sha256(OUT),
        'limitations':['Vendor availability/release timestamps not independently verified',
                       'One terminal test, interpreted conditional on historical data timing',
                       'No tuning, reselection or rerun allowed after viewing final results'],
    }
    (EVAL_DIR / 'holdout_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('=== E002 FINAL HOLDOUT EVALUATED ONCE ===')
    print('N:', len(out), '| training:',1715,'| purge: 1 label row')
    for name, vals in stats.items():
        print(name, f"MAE={vals['MAE']:.8f} RMSE={vals['RMSE']:.8f}")
    print('M2 improvement over B2:', f"{stats['B2_mean_7']['MAE']-stats['M2_market_funding_ridge']['MAE']:+.8f}")
    print('HAC(7) two-sided p-value:', f"{hac['7']['p_two_sided']:.6f}")
    print('Conditional on unverified vendor publication-time assumptions.')
    print('Saved:',EVAL_DIR)
    print('Do not rerun or tune on holdout results.')


if __name__ == '__main__':
    evaluate()
