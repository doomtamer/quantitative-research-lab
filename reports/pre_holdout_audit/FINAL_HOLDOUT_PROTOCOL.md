# FINAL HOLDOUT PROTOCOL — E002

Status: FROZEN BEFORE HOLDOUT EVALUATION

Instrument: Binance BTCUSDT Futures
Frequency: Daily UTC
Target: (high[t+1] - low[t+1]) / close[t]

Development: 1716 observations
Final training: first 1715 observations
Purged development row: 2025-09-12
Final holdout: 429 observations
Holdout feature dates: 2025-09-13 to 2026-11-15

PRIMARY MODEL:
B2 — trailing 7-day mean of normalized historical range

SECONDARY MODEL:
M2 — Ridge + Funding
Features: 16 market + 7 funding
Ridge alpha: 10
Preprocessing: train-only median imputation and scaling
Negative predictions: clipped to zero

PRIMARY METRIC: MAE
SECONDARY METRIC: RMSE
STATISTICAL COMPARISON: paired absolute-loss difference
HAC maxlags: 7
Sensitivity: HAC maxlags 14 and 30

Model selection and hyperparameters are frozen.
No tuning or model reselection using holdout results.
Holdout must be evaluated once using this protocol.

LIMITATIONS:
Vendor publication-time audit remains unproven.
E001 and E003 are exploratory research.
