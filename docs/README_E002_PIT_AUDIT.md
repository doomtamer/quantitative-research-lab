# E002 — Funding source-to-feature audit

Unpack into the root `quantitative-research-lab` folder, merging `src`, `scripts`, `tests`, `docs`.

Run unit tests:

```powershell
uv run python -m pytest tests/test_e002_pit.py -v
```

Run actual **development-only** audit:

```powershell
uv run python scripts/run_e002_pit_audit.py
```

The audit compares seven funding features on the frozen development period (2021-01-01 through 2025-09-12) against reconstructions from `data/raw/binance_funding_events.csv`, including weekend days and rolling windows. It checks the scheduled settlement hours (00, 08 and 16 UTC) and counts. It reads only the first 1716 source-feature rows (without any target or holdout labels). The source CSV hash must match the E002 CV metadata. It does not download new data, retrain models, or overwrite E002 predictions.

Output: `reports/E002_range/funding_point_in_time_audit.json`.

**Important limitation:** Archived funding settlement timestamps are not independent evidence of the precise time each datum was accessible to a real trading system. A true point-in-time audit also needs documented source delivery conventions and, ideally, ingestion timestamps. Results remain development/exploratory until independently verified.
