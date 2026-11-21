#!/usr/bin/env python3
"""Read-only final E002 preregistration checks. No holdout labels parsed.

After PASS, writes a frozen SHA256 manifest. Requires existing E001-E003 audits.
"""
from __future__ import annotations
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from quantlab.research.e002_ridge import ALPHA, FEATURES
from quantlab.research.e002_funding import FUNDING_FEATURES, M2_FEATURES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/pre_holdout_audit/E002_FROZEN_MANIFEST.json'
PROTOCOL = ROOT / 'reports/pre_holdout_audit/FINAL_HOLDOUT_PROTOCOL.md'
EVAL_DIR = ROOT / 'reports/E002_final_holdout'

FILE_LIST = [
    'data/processed/btc_daily_features.csv',
    'data/processed/btc_daily_raw.csv',
    'data/processed/e002_development_target.csv',
    'reports/E001_funding_rate/cv_metadata.json',
    'reports/E002_range/target_audit.json',
    'reports/E002_range/baseline_cv_metadata.json',
    'reports/E002_range/ridge_cv_metadata.json',
    'reports/E002_range/funding_cv_metadata.json',
    'reports/E002_range/funding_point_in_time_audit.json',
    'reports/pre_holdout_audit/market_feature_causality_audit.json',
    'reports/pre_holdout_audit/FINAL_HOLDOUT_PROTOCOL.md',
    'src/quantlab/research/e002_ridge.py',
    'src/quantlab/research/e002_funding.py',
    'src/quantlab/research/e002_target.py',
    'scripts/evaluate_e002_holdout_once.py',
    'scripts/preflight_e002_holdout.py',
    'uv.lock',
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def checks_from_metadata(meta: dict, target: dict, market: dict, funding: dict) -> None:
    if meta.get('holdout_evaluated') is not False:
        raise ValueError('Metadata does not assert holdout untouched')
    if (meta.get('n_development'), meta.get('n_holdout_reserved'), meta.get('n_cv_predictions')) != (1716, 429, 1030):
        raise ValueError('Frozen split or CV row count changed')
    if list(meta.get('m1_features', [])) != list(FEATURES):
        raise ValueError('M1 feature list changed')
    if list(meta.get('m2_incremental_funding_features', [])) != list(FUNDING_FEATURES):
        raise ValueError('Funding feature list changed')
    if meta.get('m2_total_features') != len(M2_FEATURES) or float(meta.get('ridge_alpha', -1)) != ALPHA:
        raise ValueError('M2 specification changed')
    if meta.get('label_purge_days') != 1:
        raise ValueError('1-day purge missing in metadata')
    if target.get('n_development') != 1716 or target.get('n_holdout_reserve') != 429 or target.get('holdout_target_evaluated') is not False:
        raise ValueError('Target audit disagreement')
    if market.get('status') != 'PASS' or market.get('n_total_feature_or_target_mismatches') != 0 or market.get('holdout_rows_parsed') is not False:
        raise ValueError('Market feature audit is not clean')
    if funding.get('reconstruction_passed') is not True or funding.get('holdout_labels_read') is not False:
        raise ValueError('Funding source audit is not clean')
    if sum(int(v['mismatch_count']) for v in funding.get('feature_comparisons', {}).values()) != 0 or len(funding.get('feature_comparisons', {})) != 7:
        raise ValueError('Funding feature reconstruction incomplete')
    if market.get('source_sha256') != meta.get('source_feature_sha256') or funding.get('source_feature_sha256') != meta.get('source_feature_sha256'):
        raise ValueError('Source SHA mismatch across audits')


def read_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))


def load_development_inputs(source_path: Path, derived_path: Path, n: int = 1716) -> pd.DataFrame:
    """Read only development rows, joining E002-derived features by UTC date.

    The base BTC feature CSV intentionally does not contain e002_range_* columns;
    those were frozen separately in e002_development_target.csv.
    Neither file's holdout targets are loaded here.
    """
    derived_cols = ('e002_range_today', 'e002_range_mean_7')
    source_cols = ['date', *[c for c in FEATURES if c not in derived_cols], *FUNDING_FEATURES]
    dev = pd.read_csv(source_path, nrows=n, usecols=source_cols)
    derived = pd.read_csv(derived_path, nrows=n, usecols=['date', *derived_cols])
    if len(dev) != n or len(derived) != n:
        raise ValueError('Incomplete development inputs')
    base_dates = pd.to_datetime(dev['date'], utc=True, errors='coerce')
    derived_dates = pd.to_datetime(derived['date'], utc=True, errors='coerce')
    if base_dates.isna().any() or derived_dates.isna().any() or not base_dates.equals(derived_dates):
        raise ValueError('E002 derived features do not align with base development dates')
    for col in derived_cols:
        dev[col] = pd.to_numeric(derived[col], errors='coerce').to_numpy()
    return dev


def preflight() -> dict:
    if EVAL_DIR.exists() and any(EVAL_DIR.iterdir()):
        raise RuntimeError('A final holdout evaluation exists or was attempted. Do not rerun.')
    if OUT.exists():
        raise RuntimeError('Frozen manifest already exists. Do not silently replace it.')
    for rel in FILE_LIST:
        if not (ROOT / rel).is_file():
            raise FileNotFoundError(f'Missing prerequisite: {rel}')
    protocol = PROTOCOL.read_text(encoding='utf-8-sig')
    expected = [
        'FROZEN BEFORE HOLDOUT EVALUATION',
        'Final training: first 1715 observations',
        'Purged development row: 2025-09-12',
        'Final holdout: 429 observations',
        'Holdout feature dates: 2025-09-13 to 2026-11-15',
        'HAC maxlags: 7',
    ]
    if any(item not in protocol for item in expected):
        raise ValueError('Frozen protocol content differs from agreed specification')

    meta = read_json('reports/E002_range/funding_cv_metadata.json')
    target = read_json('reports/E002_range/target_audit.json')
    market = read_json('reports/pre_holdout_audit/market_feature_causality_audit.json')
    funding = read_json('reports/E002_range/funding_point_in_time_audit.json')
    checks_from_metadata(meta, target, market, funding)

    files = {rel: sha256(ROOT / rel) for rel in FILE_LIST}
    if files['data/processed/btc_daily_features.csv'] != meta.get('source_feature_sha256'):
        raise ValueError('Source hash differs from frozen CV input')
    if files['data/processed/e002_development_target.csv'] != meta.get('development_file_sha256'):
        raise ValueError('Development hash differs from CV input')

    # DEV ONLY: intentionally parse first 1716 rows; never parse holdout labels.
    dev = load_development_inputs(
        ROOT / 'data/processed/btc_daily_features.csv',
        ROOT / 'data/processed/e002_development_target.csv',
        n=1716,
    )
    if len(dev) != 1716:
        raise ValueError('Too few development rows')
    dates = pd.to_datetime(dev['date'], utc=True, errors='coerce')
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('Development dates invalid')
    if dates.iloc[-1].date().isoformat() != '2025-09-12' or dates.iloc[-2].date().isoformat() != '2025-09-11':
        raise ValueError('Development cutoff differs')
    if not dates.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError('Development dates not continuous')
    x = dev.iloc[:1715][list(M2_FEATURES)].apply(pd.to_numeric, errors='coerce')
    if x.isna().all(axis=0).any():
        raise ValueError('Training feature entirely missing; M2 will not fit')
    if not x.replace([float('inf'), -float('inf')], float('nan')).notna().all().all():
        # allow missing values on training; reject infinities only
        if (x.abs() == float('inf')).any().any():
            raise ValueError('Infinite training features')
    result = {
        'status': 'PREFLIGHT_PASSED',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'n_development': 1716,
        'n_training': 1715,
        'purged_feature_date': '2025-09-12',
        'n_holdout': 429,
        'first_holdout_feature_date': '2025-09-13',
        'last_holdout_feature_date': '2026-11-15',
        'feature_names_M2': list(M2_FEATURES),
        'model_alpha': ALPHA,
        'label_definition': '(high[t+1]-low[t+1])/close[t]',
        'primary_metric': 'MAE', 'secondary_metric': 'RMSE',
        'reference': 'B2 trailing 7 observed completed candles through day t',
        'publication_time_proven': False,
        'holdout_labels_parsed_during_preflight': False,
        'full_data_hashed_but_holdout_labels_not_parsed': True,
        'files_sha256': files,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create ensures that running twice cannot overwrite a frozen manifest.
    with OUT.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result


if __name__ == '__main__':
    report = preflight()
    print('E002 FINAL HOLDOUT PREFLIGHT PASSED (NO HOLDOUT LABELS PARSED)')
    print('Training:', report['n_training'], '| purged:', report['purged_feature_date'], '| holdout reserved:', report['n_holdout'])
    print('Vendor publication-time proof: NOT AVAILABLE; results will be conditional')
    print('Manifest:', OUT)
    print('Do not launch the one-time evaluator until we review this output.')
