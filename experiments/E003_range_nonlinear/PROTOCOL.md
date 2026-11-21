# E003 — Nonlinear Forecasting of BTCUSDT Next-Day High–Low Range

**Status:** Protocol frozen in the provided package, before E003 model runs.  
**Category:** Exploratory development research, NOT an independent confirmation.  
**Instrument:** Binance BTCUSDT USD-M futures, daily UTC.  
**Human approval:** No model or hypothesis is automatically promoted.

## Hypotheses
- H0 (primary): A fixed-market-features Random Forest (M3) has no improvement in next-day range MAE over the frozen B2 seven-calendar-day range baseline.
- H1 (primary): M3 improves MAE over B2 in development CV.
- Secondary: M4 (same RF + 7 previously frozen funding features) improves MAE over M3.

## Target and timing
`target_range[t] = (high[t+1]-low[t+1])/close[t]` where the decision is made **after the UTC close of t**. Models must not use next-day observations as inputs. `e002_range_today` uses the day-t high–low range scaled by close[t-1]; this is known after t closes, with a different denominator from target, so interpret carefully.

## Data boundaries
- 2145 source rows (last date t 2026-11-15) with first 1716 rows DEVELOPMENT ONLY.
- Last 429 rows remain a separate sealed holdout.
- Five E002 walk-forward validation blocks retained exactly: 206 days each, 1030 development validation observations.
- One day label purge between training targets and first validation feature date.
- Pipeline median imputation is fitted independently on training rows only.
- E003 code imports the E002 frozen loader and SHA256 provenance checks; it does not load holdout labels.

## Frozen model hyperparameters
RandomForestRegressor:
`n_estimators=300; max_depth=6; min_samples_leaf=20; max_features=0.8; bootstrap=True; random_state=2026; n_jobs=1`

- M3 market RF: exactly E002 M1's 16 market/range input features.
- M4 market+funding RF: exactly M3's 16 + E002 M2's 7 funding features.
- No ETF or macro input; no scaling; no parameter search; nonnegative output clipping.
- Prespecified evaluation: pooled daily MAE primary; RMSE secondary; per-fold MAE and MAE difference versus B2; M4 versus M3 secondary.

## Interpretation and limits
- E003 uses the same development CV dates observed in E002: any p-values on these dates are **exploratory** and do not constitute independent confirmatory evidence.
- For formal claims consider block bootstrap / HAC sensitivity, multiple testing correction, and an external future dataset. No post-hoc metric or threshold changes.
- Do NOT invoke an E003 final/holdout phase; this package does not implement one.
- Funding event timestamps/values reconstructed successfully in E002; real vendor publication latency not independently verified.
- No financial performance, execution/slippage, or economic profitability claims.
