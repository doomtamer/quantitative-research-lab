from pathlib import Path
import pandas as pd

TIMESTAMP_CANDIDATES = ["timestamp", "date", "datetime", "open_time"]

def load_table(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku: {path}")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError("Obsługiwane formaty: CSV i Parquet.")

def inspect_table(df):
    ts_col = next((c for c in TIMESTAMP_CANDIDATES if c in df.columns), None)
    out = {
        "rows": int(len(df)), "columns_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "duplicate_rows": int(df.duplicated().sum()),
        "missing_cells": int(df.isna().sum().sum()),
        "missing_by_column": {str(k): int(v) for k, v in df.isna().sum().items() if v},
        "timestamp_column": ts_col,
    }
    if ts_col:
        ts = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
        valid = ts.dropna()
        out.update({
            "invalid_timestamps": int(ts.isna().sum()),
            "duplicate_timestamps": int(ts.duplicated().sum()),
            "first_timestamp_utc": valid.min().isoformat() if len(valid) else None,
            "last_timestamp_utc": valid.max().isoformat() if len(valid) else None,
        })
    return out
