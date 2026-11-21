# E003 package: use from `quantitative-research-lab` root (VS Code PowerShell)

1. Extract the ZIP **into the existing project folder**, merging directories.
2. Check files: `Test-Path .\scripts\run_e003_rf.py` (True expected).
3. Run tests: `uv run python -m pytest tests/test_e003_rf.py -v`.
4. Read `experiments/E003_range_nonlinear/PROTOCOL.md` before running the experiment.
5. Execute: `uv run python scripts/run_e003_rf.py`.
6. Send the terminal result for interpretation. It will write `reports/E003_range_nonlinear/rf_cv_predictions.csv`, `rf_cv_metrics.csv`, `rf_cv_pooled.csv`, and `rf_cv_metadata.json`.

**Prerequisites:** E002 development target, baseline, Ridge M1, funding M2, and successfully passed E002 source-to-feature funding PIT audit. The script validates hashes and fails on missing or changed files rather than silently changing the experiment. No original E002 file is overwritten.

**Data safety:** Only 1716 development rows are loaded as model data, using the tested E002 loader, with frozen folds and a one-label-day purge. No holdout target accessed. Only development CV, which is exploratory.
