# E002 — M2 Market + Funding Ridge

This package adds **one fixed model comparison**, without tuning after seeing CV:

- B2: trailing 7-session daily range mean, previously frozen.
- M1: previously frozen Ridge market-only forecasts.
- M2: Ridge with the **same** 16 M1 market features, **same** `alpha=10`, **same** folds, imputation, scaling, clipping and 1-day label purge **plus exactly seven funding features** taken from E001.

Funding features: `funding_mean`, `funding_std`, `funding_mean_3d`, `funding_mean_7d`, `funding_mean_14d`, `funding_mean_30d`, `funding_z_30d`.

### How to run (Windows PowerShell, from project root)

Unzip contents directly into `quantitative-research-lab` (merge folders, do not nest).

```powershell
uv run python -m pytest tests/test_e002_funding.py -v
uv run python scripts/run_e002_funding.py
```

Requires these already-produced E002 artifacts:

- `data/processed/e002_development_target.csv`
- `reports/E002_range/target_audit.json`
- `reports/E002_range/baseline_cv_metadata.json`
- `reports/E002_range/baseline_cv_predictions.csv`
- `reports/E002_range/ridge_cv_metadata.json`
- `reports/E002_range/ridge_cv_predictions.csv`
- `scripts/run_e002_ridge.py` and module `src/quantlab/research/e002_ridge.py`

### Outputs

- `reports/E002_range/funding_cv_predictions.csv`
- `reports/E002_range/funding_cv_metrics.csv`
- `reports/E002_range/funding_cv_pooled.csv`
- `reports/E002_range/funding_cv_metadata.json`

### Safeguards

The script loads the **first 1716** feature rows, never reads holdout target labels for estimation or evaluation, verifies prior source / development / B2 hashes, verifies frozen M1 CV folds and compares every M1 and B2 prediction and target to its previous file. M2 fits training-only median imputation and scaling independently in each fold. Target `target_range[t] = (high[t+1]-low[t+1])/close[t]` is **not** included in model features. This remains exploratory development CV; M2 may or may not beat M1. Validate publication availability timing before calling anything production-ready.
