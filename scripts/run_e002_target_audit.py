#!/usr/bin/env python3
"""Audit E002 target against raw OHLC, prepare ONLY development-set target/baselines.

No network access, no training, and no final-holdout label inspection.
Run from project root: uv run python scripts/run_e002_target_audit.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from quantlab.research.e002_target import next_day_range, observed_range_features

ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = ROOT / "data/processed/btc_daily_features.csv"
RAW_PATH = ROOT / "data/processed/btc_daily_raw.csv"
E001_METADATA = ROOT / "reports/E001_funding_rate/cv_metadata.json"
OUT_DIR = ROOT / "reports/E002_range"
DEV_OUT = ROOT / "data/processed/e002_development_target.csv"


def load_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    frame = pd.read_csv(path, usecols=columns)
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise ValueError(f"Invalid/duplicate UTC dates: {path.name}")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError(f"Nonchronological dates: {path.name}")
    if not frame["date"].dt.strftime("%H:%M:%S").eq("00:00:00").all():
        raise ValueError(f"Expected UTC daily candle-start dates: {path.name}")
    if not frame["date"].diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError(f"Gaps in calendar days: {path.name}")
    for col in columns:
        if col != "date":
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def audit() -> dict:
    if not E001_METADATA.is_file():
        raise FileNotFoundError("E001 CV metadata missing: cannot freeze development/holdout boundary")
    meta = json.loads(E001_METADATA.read_text(encoding="utf-8"))
    sha = hashlib.sha256(FEATURES_PATH.read_bytes()).hexdigest()
    if sha != meta.get("data_sha256"):
        raise ValueError("Feature CSV SHA256 differs from E001; stop to avoid changing the holdout split")
    feature_cols = ["date", "close", "high", "low", "target_range", "target_high_ret", "target_low_ret"]
    features = load_frame(FEATURES_PATH, feature_cols)
    n_total, n_dev, n_holdout = int(meta["n_total"]), int(meta["n_development"]), int(meta["n_holdout"])
    if len(features) != n_total or n_total != n_dev + n_holdout:
        raise ValueError("Development and holdout sizes do not match E001")
    # Ignore holdout target values entirely. Use E001's fixed development cutoff.
    dev = features.iloc[:n_dev].copy().reset_index(drop=True)
    end_day = dev["date"].iloc[-1]
    raw_all = load_frame(RAW_PATH, ["date", "open", "high", "low", "close"])
    # Only raw candles through the day AFTER the last development date are needed.
    raw = raw_all.loc[raw_all["date"] <= end_day + pd.Timedelta(days=1)].copy().reset_index(drop=True)
    if len(raw) != n_dev + 1 or not dev["date"].equals(raw["date"].iloc[:-1].reset_index(drop=True)):
        raise ValueError("Raw/development dates not aligned or next-day raw candle missing")
    if raw[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Raw OHLC contains NaNs in development/label window")
    if not raw[["open", "high", "low", "close"]].gt(0).all().all():
        raise ValueError("Raw OHLC contains nonpositive values")
    if ((raw["high"] < raw[["open", "close"]].max(axis=1)) |
        (raw["low"] > raw[["open", "close"]].min(axis=1)) |
        (raw["high"] < raw["low"])).any():
        raise ValueError("Raw OHLC high/low inconsistent with open/close")

    reconstructed = next_day_range(raw["high"], raw["low"], raw["close"]).iloc[:-1].reset_index(drop=True)
    stored = dev["target_range"]
    from_return_columns = dev["target_high_ret"] - dev["target_low_ret"]
    if stored.isna().any() or (stored < 0).any() or not np.isfinite(stored).all():
        raise ValueError("Development target contains null, negative or infinite values")
    discrepancies = ~np.isclose(stored.to_numpy(), reconstructed.to_numpy(), atol=1e-10, rtol=1e-8)
    discrepancies_ret = ~np.isclose(stored.to_numpy(), from_return_columns.to_numpy(), atol=1e-10, rtol=1e-8)
    if discrepancies.any() or discrepancies_ret.any():
        raise ValueError(f"Target mismatch! raw formula={discrepancies.sum()}, high/low returns={discrepancies_ret.sum()}")
    if not np.allclose(dev["close"].to_numpy(), raw["close"].iloc[:-1].to_numpy(), atol=1e-8, rtol=1e-10):
        raise ValueError("Feature close prices differ from raw closes")
    observed = observed_range_features(raw["high"], raw["low"], raw["close"]).iloc[:-1]
    dev_out = pd.DataFrame({"date": dev["date"].dt.strftime("%Y-%m-%d"),
                            "target_range": reconstructed,
                            **{name: observed[name].to_numpy() for name in observed.columns}})
    # We never write/review labels or statistics from the reserved 429-day holdout.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DEV_OUT.parent.mkdir(parents=True, exist_ok=True)
    dev_out.to_csv(DEV_OUT, index=False)
    report = {
        "experiment": "E002_range",
        "phase": "target_audit_development_only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_feature_sha256": sha,
        "target_definition": "(high[t+1] - low[t+1]) / close[t]",
        "target_units": "fraction of close[t] (0.05 = 5%)",
        "not_a_direction_or_realized_variance_target": True,
        "n_total": n_total,
        "n_development": n_dev,
        "n_holdout_reserve": n_holdout,
        "holdout_target_evaluated": False,
        "dev_first": str(dev["date"].iloc[0].date()),
        "dev_last_feature_day": str(end_day.date()),
        "dev_last_label_day": str(raw["date"].iloc[-1].date()),
        "target_mismatches": int(discrepancies.sum()),
        "target_mismatches_high_low_ret": int(discrepancies_ret.sum()),
        "dev_target_percentiles": {
            key: float(value) for key, value in {
                "min": stored.min(), "median": stored.median(), "p90": stored.quantile(.90),
                "p95": stored.quantile(.95), "max": stored.max()
            }.items()
        },
        "available_baseline_features": list(observed.columns),
        "baseline_missing_dev": {c: int(dev_out[c].isna().sum()) for c in observed.columns},
        "warning": "Do not use existing target_large_range: threshold includes target[t] itself; classification needs a past-only cutoff.",
        "models_trained": False,
    }
    (OUT_DIR / "target_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = audit()
    print("E002 TARGET AUDIT PASSED (DEVELOPMENT ONLY)")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("Development target/baselines:", DEV_OUT)
    print("Report:", OUT_DIR / "target_audit.json")
