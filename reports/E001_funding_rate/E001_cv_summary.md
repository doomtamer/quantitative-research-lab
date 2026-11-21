# E001 - Funding Rate Predictive Power

Status: CV completed; holdout untouched.

## Research question
Does funding rate improve next-day BTCUSDT return forecasts?

## Dataset
2145 observations; 1716 development; 429 final holdout.
Five expanding-window CV folds; 1030 validation forecasts.

## Main findings
M0 Zero Return MAE: 0.01699913
M1 Market Ridge MAE: 0.01732900
M2 Market + Funding Ridge MAE: 0.01754787

M1 vs M2 difference: -0.00021887
HAC(7) p-value: 0.004908
Without WF1: -0.00010130, p-value: 0.163103

## Conclusion
No robust incremental predictive benefit from funding rate
for next-day returns in the tested Ridge specification.

## Limitations
Point-in-time feature availability requires further audit.
HAC inference is approximate; multiple comparisons were made.
The final holdout has not been evaluated.
No trading profitability assessment was conducted.

## Decision
Do not optimize E001 further based on the observed CV results.
Proceed to separately specified volatility research (E002).
