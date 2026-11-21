# E001 — incremental predictive value of funding rate

## Installation

Copy `scripts/run_e001.py` into the existing project `quantitative-research-lab/scripts/`.

No additional packages required after `uv sync`.

## Run in order

1. Raw funding event audit (does not train models):

   `uv run python scripts/run_e001.py --phase audit`

2. Walk-forward development only (does not evaluate final 20%):

   `uv run python scripts/run_e001.py --phase cv`

3. FINAL holdout — run once, only AFTER freezing features, metrics, methodology and reviewing CV:

   `uv run python scripts/run_e001.py --phase final`

Results are written to `reports/E001_funding_rate/`.

## Pre-specified protocol

- Target: next-day BTCUSDT close-to-close return.
- M0-zero: always predicts 0; M0-mean: mean training return.
- M1: Ridge on daily price/volume features available after close of day t.
- M2: same estimator and features as M1 plus funding-level and trailing funding features.
- Same rows, folds, preprocessing and hyperparameter for both models.
- Chronological split: initial 80% development; final 20% frozen holdout.
- Five chronological expanding-window validation folds in development.
- Primary metric: MAE; secondary metric: RMSE. A lower metric is better.
- No trading profitability claim, no forward-fill of future values, no use of ETF/macro columns.

## Cautions

- Funding data is sourced from Binance archives/API. Audit checks timestamp duplicates, gaps and sources. It does NOT establish full point-in-time correctness or publication latency for every archived feature.
- M2 improvement on limited folds may be sampling noise; do not infer significance or strategy profitability without further analyses.
- Do not tune predictors or hyperparameters on the final holdout.
