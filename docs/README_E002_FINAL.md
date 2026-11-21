# E002 final holdout: frozen, one-time design

This package contains a safe preflight and a one-time evaluator.

**Run now only**:

```
uv run python -m pytest tests/test_preflight_holdout.py -q
uv run python scripts/preflight_e002_holdout.py
```

The preflight hashes entire files for identity, but parses only the first 1716 development rows of the historical source. It never interprets holdout labels. It writes `reports/pre_holdout_audit/E002_FROZEN_MANIFEST.json` with exclusive-create semantics, so do not rerun to overwrite it.

After reviewing its results, the user can separately approve using the final holdout, and only then run:

```
uv run python scripts/evaluate_e002_holdout_once.py
```

That second script reads the 429 holdout targets and immediately creates a permanent `ATTEMPT_STARTED.json` guard before this read. Do not rerun it or change parameter values after inspecting the results. A failure after creating the guard requires an explicit postmortem; do not remove the marker automatically.

## Limitations

* All forecasts are computed after the UTC close of day t, predicting day t+1.
* Funding source reconstruction has been verified only on development data. Independent vendor publication timestamps have not been proven. Final inference remains conditional.
* Static train-once fit on the first 1715 rows, development row 1716 purged. Predictions for subsequent 429 dates use frozen parameters and each day's completed-candle features.
* M2 uses the 23 feature list and Ridge alpha 10.0 from CV, imputes and scales using *training only*.
* B2 uses last 7 observed normalized daily ranges through t, computed from raw OHLC without future information.
* Holdout evaluation is final and exploratory follow-up analyses must be labeled as post-hoc.
