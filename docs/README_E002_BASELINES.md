# E002 benchmark CV

From project root in VS Code PowerShell:

```powershell
uv run python -m pytest tests/test_e002_target.py tests/test_e002_baselines.py -v
uv run python scripts/run_e002_baselines.py
```

Prerequisite: `scripts/run_e002_target_audit.py` was run successfully and generated `data/processed/e002_development_target.csv` and the E002 target audit JSON.

The script does not read the 429-day final holdout or train machine-learning models. Five expanding folds have the same validation ranges as E001: 206 days each (1030 validation days total). B0 uses an additional one-day training-label gap so the last training label cannot rely on the first validation day.

Outputs in `reports/E002_range/`:
- `baseline_cv_pooled.csv`
- `baseline_cv_metrics.csv`
- `baseline_cv_predictions.csv`
- `baseline_cv_metadata.json`

B0 is the mean of training labels; B1 is persistence of the most recently observed range, and B2 is the 7-day rolling mean. B3 (30-day rolling mean) is **exploratory**; it was not part of the primary preregistered comparison.
