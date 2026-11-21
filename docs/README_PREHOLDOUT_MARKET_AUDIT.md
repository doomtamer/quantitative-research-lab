# Before Holdout: Market Feature Causality Audit (E001–E003)

From the repository root:

```powershell
uv run python -m pytest tests/test_market_feature_causality.py -v
uv run python scripts/audit_market_feature_causality.py
```

This read-only audit (except for its new JSON report) **never parses holdout rows**.

Checks the **14 market predictors of E001** and **2 additional range predictors of E002/E003**, recreating them using *only the candles of the current UTC day and previous days*. It reconstructs the first 1715 development targets from development candles. The last development target was separately independently checked in `reports/E002_range/target_audit.json`.

It also checks frozen SHA256 values to detect dataset changes. Hashing the full CSV bytes does not parse or evaluate holdout targets, but the output file should be handled accordingly for strict data governance.

The 7 funding features have already been examined in `reports/E002_range/funding_point_in_time_audit.json`; this new audit does not redo the funding audit. Remaining caveat: it is not sufficient to prove exact Binance publication times, nor is this a full point-in-time replay.

**Boundary warning:** the last development feature date is 2025-09-12, with a label for 2025-09-13. The first reserved holdout feature date is 2025-09-13. Before a strictly pre-holdout static final fit, exclude the last development label row (1-day purge). This ensures the final training targets do not touch the first reserved holdout candle. No final evaluation is included here.

The E001 CV implementation uses adjacent training/validation blocks and needs an explicit statement of the model refit `as_of` instant. It should not be labelled equivalent to the purged E002 protocol.
