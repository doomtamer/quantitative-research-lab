# BTC dataset downloader — ETF rolling-window correction (2026-11-17)

Replace `scripts/download_all_data.py` in the Quantitative Research Lab project
with the attached version (keep a backup if you customized it).

Run from project root:

```powershell
uv run python scripts/download_all_data.py --start-date 2021-01-01 --workers 6 --no-macro
```

Cached Binance ZIPs are reused. The new CSV/Parquet/report is regenerated.
The ETF 3/7/14/30-day feature names now mean **3/7/14/30 ETF reporting
sessions**, not calendar days. They are trailing, use the one-day availability
lag already present in the downloader, and carry forward up to four days.
The report counts `macro_days` based on days with nonmissing macro values
rather than the number of dates in an empty calendar placeholder.

Note: no FRED macro data is downloaded with `--no-macro`.
