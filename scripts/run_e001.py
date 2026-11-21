#!/usr/bin/env python3
"""E001: BTCUSDT daily funding-rate incremental predictive value.

Strict workflow:
  --phase audit    Check raw funding event timestamps and source provenance.
  --phase cv       Walk-forward evaluation on the development window only.
  --phase final    One-shot evaluation on untouched final 20% (after methodology lock).

Uses existing BTC dataset; does not download data or submit trades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'processed' / 'btc_daily_features.csv'
FUNDING_RAW = ROOT / 'data' / 'raw' / 'binance_funding_events.csv'
OUTPUT = ROOT / 'reports' / 'E001_funding_rate'

# Pre-specified predictors. No information from t+1 is used.
MARKET = [
    'ret_1d', 'ret_3d', 'ret_7d', 'ret_14d', 'ret_30d',
    'vol_7d', 'vol_14d', 'vol_30d', 'atr_14_pct',
    'candle_body', 'candle_range', 'volume_z_30d',
    'taker_buy_imbalance', 'dist_ma_30d',
]
FUNDING = [
    'funding_mean', 'funding_std', 'funding_mean_3d',
    'funding_mean_7d', 'funding_mean_14d',
    'funding_mean_30d', 'funding_z_30d',
]
TARGET = 'target_close_ret'
FINAL_TEST_SHARE = 0.20
N_FOLDS = 5
RIDGE_ALPHA = 10.0  # pre-declared; no tuning on the holdout


def read_features() -> pd.DataFrame:
    if not DATA.exists():
        raise FileNotFoundError(f'Dataset not found: {DATA}')
    frame = pd.read_csv(DATA, parse_dates=['date'])
    frame['date'] = pd.to_datetime(frame['date'], utc=True, errors='coerce')
    if frame['date'].isna().any() or frame['date'].duplicated().any():
        raise ValueError('Invalid or duplicate feature dates')
    frame = frame.sort_values('date').reset_index(drop=True)
    required = [TARGET, *MARKET, *FUNDING]
    missing = [col for col in required if col not in frame]
    if missing:
        raise ValueError(f'Missing required columns: {missing}')
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
    if frame[TARGET].isna().any():
        raise ValueError('Target contains missing values')
    if len(frame) < 1000:
        raise ValueError('Not enough observations for specified research protocol')
    expected = pd.date_range(frame['date'].iloc[0], frame['date'].iloc[-1], freq='D')
    if not frame['date'].reset_index(drop=True).equals(pd.Series(expected, name='date')):
        raise ValueError('Missing daily dates in dataset')
    return frame


def audit_funding(frame: pd.DataFrame) -> dict:
    if not FUNDING_RAW.exists():
        raise FileNotFoundError(f'Funding events not found: {FUNDING_RAW}')
    raw = pd.read_csv(FUNDING_RAW)
    for col in ['funding_time', 'funding_rate', 'source']:
        if col not in raw:
            raise ValueError(f'Missing funding raw column: {col}')
    raw['funding_time'] = pd.to_datetime(raw['funding_time'], errors='coerce', utc=True)
    raw['funding_rate'] = pd.to_numeric(raw['funding_rate'], errors='coerce')
    raw = raw.sort_values('funding_time').reset_index(drop=True)
    if raw[['funding_time', 'funding_rate']].isna().any().any():
        raise ValueError('Funding events contain missing timestamps or rates')
    dupes = int(raw['funding_time'].duplicated().sum())
    intervals = raw['funding_time'].diff().dropna().dt.total_seconds() / 3600
    counts = raw.groupby(raw['funding_time'].dt.normalize()).size()
    frame_daily = frame[['date', 'funding_n', 'funding_mean']].copy()
    frame_daily['funding_n'] = pd.to_numeric(frame_daily['funding_n'], errors='coerce')
    consistency = frame_daily.set_index('date').join(counts.rename('raw_events'), how='left')
    mismatched_counts = int((consistency['funding_n'] != consistency['raw_events']).sum())
    nov = raw[raw['funding_time'].dt.strftime('%Y-%m').eq('2026-11')]
    report = {
        'raw_events': int(len(raw)),
        'raw_days': int(len(counts)),
        'raw_first': raw['funding_time'].iloc[0].isoformat(),
        'raw_last': raw['funding_time'].iloc[-1].isoformat(),
        'duplicate_event_timestamps': dupes,
        'event_count_per_day_distribution': {str(int(k)): int(v) for k, v in counts.value_counts().sort_index().items()},
        'interval_hours_distribution_top10': {str(k): int(v) for k, v in intervals.round(6).value_counts().head(10).items()},
        'events_not_8h_apart': int((~np.isclose(intervals, 8.0)).sum()),
        'feature_funding_n_mismatch_days': mismatched_counts,
        'sources_all': {str(k): int(v) for k, v in raw['source'].value_counts().items()},
        'sources_2026_11': {str(k): int(v) for k, v in nov['source'].value_counts().items()},
        'funding_mean_missing': int(frame['funding_mean'].isna().sum()),
    }
    return report


def model(columns: list[str]) -> Pipeline:
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler()),
        ('regression', Ridge(alpha=RIDGE_ALPHA)),
    ])


def scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        'MAE': float(mean_absolute_error(y_true, y_pred)),
        'RMSE': float(np.sqrt(mean_squared_error(y_true, y_pred))),
    }


def evaluation(train: pd.DataFrame, valid: pd.DataFrame, fold: str):
    y_train = train[TARGET].to_numpy(dtype=float)
    y_valid = valid[TARGET].to_numpy(dtype=float)
    pred = {
        'M0_zero': np.zeros(len(valid), dtype=float),
        'M0_mean': np.full(len(valid), y_train.mean(), dtype=float),
    }
    for label, predictors in [('M1_market', MARKET), ('M2_market_funding', MARKET + FUNDING)]:
        fitted = model(predictors).fit(train[predictors], y_train)
        pred[label] = fitted.predict(valid[predictors])
    rows = []
    for label, predictions in pred.items():
        rows.append({'fold': fold, 'model': label, 'n_train': len(train), 'n_valid': len(valid),
                     'valid_first': str(valid['date'].iloc[0].date()),
                     'valid_last': str(valid['date'].iloc[-1].date()), **scores(y_valid, predictions)})
    per_day = pd.DataFrame({'date': valid['date'].dt.strftime('%Y-%m-%d').to_numpy(),
                            'fold': fold, 'actual': y_valid, **pred})
    return rows, per_day


def experiment(frame: pd.DataFrame, phase: str):
    split = int(len(frame) * (1 - FINAL_TEST_SHARE))
    development = frame.iloc[:split]
    holdout = frame.iloc[split:]
    print(f'Data: {len(frame)} days | development: {len(development)} days '
          f'({development.date.iloc[0].date()} - {development.date.iloc[-1].date()}) | '
          f'final holdout: {len(holdout)} days (left untouched in CV)')
    if phase == 'cv':
        min_train = max(365, int(len(development) * 0.4))
        remainder = len(development) - min_train
        edges = np.linspace(min_train, len(development), N_FOLDS + 1).astype(int)
        all_rows = []
        daily_frames = []
        for i in range(N_FOLDS):
            train = development.iloc[:edges[i]]
            valid = development.iloc[edges[i]:edges[i + 1]]
            if valid.empty:
                raise ValueError('Empty validation fold')
            rows, daily = evaluation(train, valid, f'WF{i + 1}')
            all_rows.extend(rows)
            daily_frames.append(daily)
        daily = pd.concat(daily_frames, ignore_index=True)
        result = pd.DataFrame(all_rows)
        print('\nWALK-FORWARD - mean metrics across folds')
        print(result.groupby('model')[['MAE', 'RMSE']].mean().to_string(float_format=lambda x: f'{x:.8f}'))
        print('\nBy fold:')
        print(result.pivot(index='fold', columns='model', values='MAE').to_string(float_format=lambda x: f'{x:.8f}'))
        delta = (daily['actual'] - daily['M1_market']).abs().mean() - (daily['actual'] - daily['M2_market_funding']).abs().mean()
        print(f'\nPooled daily MAE improvement M2 over M1: {delta:+.8f} '
              '(positive means funding helped)')
        basename = 'cv'
        meta = {'phase': 'cv', 'holdout_evaluated': False, 'pooled_mae_improvement_m2_vs_m1': float(delta)}
    else:
        rows, daily = evaluation(development, holdout, 'FINAL_HOLDOUT')
        result = pd.DataFrame(rows)
        print('\nFINAL HOLDOUT (one-shot):')
        print(result[['model', 'MAE', 'RMSE']].to_string(index=False, float_format=lambda x: f'{x:.8f}'))
        basename = 'final_holdout'
        meta = {'phase': 'final', 'holdout_evaluated': True}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT / f'{basename}_metrics.csv', index=False)
    daily.to_csv(OUTPUT / f'{basename}_predictions.csv', index=False)
    meta.update({
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'data_sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(),
        'n_total': len(frame), 'n_development': len(development), 'n_holdout': len(holdout),
        'target': TARGET, 'features_M1': MARKET, 'features_M2_incremental': FUNDING,
        'ridge_alpha': RIDGE_ALPHA, 'n_walk_forward_folds': N_FOLDS,
        'primary_metric': 'MAE',
        'secondary_metric': 'RMSE',
        'protocol_note': 'All preprocessing fitted on training section only; ordered expanding-window CV.',
        'limitation': 'Funding/positioning source timing is only partially verified for true point-in-time replay.',
    })
    (OUTPUT / f'{basename}_metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print('\nSaved results to:', OUTPUT)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=['audit', 'cv', 'final'], default='audit')
    args = p.parse_args()
    frame = read_features()
    audit = audit_funding(frame)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'funding_audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    print('Funding audit:')
    print(json.dumps(audit, indent=2))
    if audit['duplicate_event_timestamps'] or audit['feature_funding_n_mismatch_days'] or audit['funding_mean_missing']:
        raise RuntimeError('Funding audit FAILED. Resolve issues before modelling.')
    if args.phase != 'audit':
        if args.phase == 'final':
            locked_cv = OUTPUT / 'cv_metadata.json'
            if not locked_cv.exists():
                raise RuntimeError('CV metadata not found. Run --phase cv and lock protocol first.')
            if (OUTPUT / 'final_holdout_metadata.json').exists():
                raise RuntimeError('Final holdout already evaluated; do not repeatedly query it.')
        experiment(frame, args.phase)

if __name__ == '__main__':
    main()
