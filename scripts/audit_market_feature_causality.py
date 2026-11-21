#!/usr/bin/env python3
"""Read-only PIT-oriented audit of all MARKET model inputs for E001-E003.

Reads ONLY the first frozen 1716 development rows from source and raw CSVs.
Reads entire feature CSV bytes solely to verify its frozen SHA256 (not labels).
Checks deterministic reconstruction for OHLCV-derived features. Funding has a
separate completed source->feature audit; this audit does NOT prove exchange
publication timestamps or future realtime data availability.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data/processed/btc_daily_features.csv"
RAW = ROOT / "data/processed/btc_daily_raw.csv"
E002_DEV = ROOT / "data/processed/e002_development_target.csv"
E001_META = ROOT / "reports/E001_funding_rate/cv_metadata.json"
E002_META = ROOT / "reports/E002_range/funding_cv_metadata.json"
E002_PIT_META = ROOT / "reports/E002_range/funding_point_in_time_audit.json"
OUTPUT = ROOT / "reports/pre_holdout_audit/market_feature_causality_audit.json"

MARKET_INPUTS_E001 = [
    "ret_1d", "ret_3d", "ret_7d", "ret_14d", "ret_30d",
    "vol_7d", "vol_14d", "vol_30d", "atr_14_pct",
    "candle_body", "candle_range", "volume_z_30d",
    "taker_buy_imbalance", "dist_ma_30d",
]
RANGE_INPUTS_E002 = ["e002_range_today", "e002_range_mean_7"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconstructed_market(raw: pd.DataFrame) -> pd.DataFrame:
    """Causal formulas as of after UTC day t closes; no future indexing."""
    o = pd.to_numeric(raw["open"], errors="coerce")
    h = pd.to_numeric(raw["high"], errors="coerce")
    l = pd.to_numeric(raw["low"], errors="coerce")
    c = pd.to_numeric(raw["close"], errors="coerce")
    v = pd.to_numeric(raw["volume"], errors="coerce")
    taker = pd.to_numeric(raw["taker_buy_base_volume"], errors="coerce")
    out = pd.DataFrame(index=raw.index)
    for days in (1, 3, 7, 14, 30):
        out[f"ret_{days}d"] = c.pct_change(days)
    logret = np.log(c).diff()
    for days in (7, 14, 30):
        out[f"vol_{days}d"] = logret.rolling(days).std() * np.sqrt(365)
    previous_close = c.shift(1)
    true_range = pd.concat([
        h - l,
        (h - previous_close).abs(),
        (l - previous_close).abs()
    ], axis=1).max(axis=1)
    out["atr_14_pct"] = true_range.rolling(14).mean() / c
    out["candle_body"] = (c - o) / o
    out["candle_range"] = (h - l) / o
    lv = np.log1p(v)
    out["volume_z_30d"] = (lv - lv.rolling(30).mean()) / lv.rolling(30).std().replace(0, np.nan)
    out["taker_buy_imbalance"] = 2 * (taker / v.replace(0, np.nan)) - 1
    out["dist_ma_30d"] = c / c.rolling(30).mean() - 1
    observed = (h - l) / c.shift(1)
    out["e002_range_today"] = observed
    out["e002_range_mean_7"] = observed.rolling(7, min_periods=7).mean()
    return out


def compare_columns(stored: pd.DataFrame, expected: pd.DataFrame, names: list[str]) -> dict:
    result = {}
    for col in names:
        if col not in stored or col not in expected:
            raise ValueError(f"Missing column {col}")
        a = pd.to_numeric(stored[col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(expected[col], errors="coerce").to_numpy(dtype=float)
        if len(a) != len(b):
            raise ValueError(f"Length mismatch in {col}")
        both_missing = np.isnan(a) & np.isnan(b)
        close = np.isclose(a, b, rtol=1e-7, atol=1e-9, equal_nan=False)
        mismatch = ~(close | both_missing)
        finite = np.isfinite(a) & np.isfinite(b)
        max_diff = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else None
        result[col] = {
            "mismatches": int(mismatch.sum()),
            "max_abs_difference": max_diff,
            "matching_missing_values": int(both_missing.sum()),
        }
    return result


def validate_dates(a: pd.DataFrame, b: pd.DataFrame, c: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    dates = []
    for frame in (a, b, c):
        d = pd.to_datetime(frame["date"], utc=True, errors="coerce")
        if d.isna().any() or d.duplicated().any() or not d.is_monotonic_increasing:
            raise ValueError("Missing, duplicate or unordered timestamps")
        if not d.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
            raise ValueError("Non-daily timestamps")
        dates.append(d.reset_index(drop=True))
    if not dates[0].equals(dates[1]) or not dates[0].equals(dates[2]):
        raise ValueError("Development/raw/E002 dates differ")
    return dates[0].iloc[0], dates[0].iloc[-1]


def run() -> dict:
    meta = json.loads(E001_META.read_text(encoding="utf-8"))
    meta2 = json.loads(E002_META.read_text(encoding="utf-8"))
    n = int(meta["n_development"])
    assert n == 1716 and meta["n_holdout"] == 429, "Unexpected frozen split"
    source_sha = sha256(FEATURES)
    if source_sha != meta["data_sha256"] or source_sha != meta2["source_feature_sha256"]:
        raise ValueError("Source feature file hash no longer matches frozen experiments")

    market_cols = ["date", "open", "high", "low", "close", "volume", "taker_buy_base_volume"]
    feature_cols = ["date", "open", "high", "low", "close", "volume", "taker_buy_base_volume",
                    "target_close_ret", "target_range", *MARKET_INPUTS_E001]
    f = pd.read_csv(FEATURES, nrows=n, usecols=feature_cols)
    r = pd.read_csv(RAW, nrows=n, usecols=market_cols)
    d = pd.read_csv(E002_DEV, nrows=n)
    if len(f) != n or len(r) != n or len(d) != n:
        raise ValueError("Incomplete development rows")
    first, last = validate_dates(f, r, d)
    for col in market_cols[1:]:
        if f[col].isna().any() or r[col].isna().any():
            raise ValueError(f"Missing raw market data in {col}")
        if not np.allclose(f[col], r[col], rtol=1e-12, atol=1e-8):
            raise ValueError(f"Raw OHLCV mismatch: {col}")
    valid_candles = (
        (r[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (r["high"] >= r[["open", "close"]].max(axis=1))
        & (r["low"] <= r[["open", "close"]].min(axis=1))
    )
    if not valid_candles.all() or (r["volume"] <= 0).any():
        raise ValueError("Invalid market candles")

    expected = reconstructed_market(r)
    check1 = compare_columns(f, expected, MARKET_INPUTS_E001)
    check2 = compare_columns(d, expected, RANGE_INPUTS_E002)
    # Target checks on development rows 0..n-2 only. Last development row's
    # label requires raw candle t+1 outside this truncated range and was
    # checked in the separate E002 target audit.
    expected_range = ((r["high"].shift(-1) - r["low"].shift(-1)) / r["close"]).iloc[:-1]
    expected_close = (r["close"].shift(-1) / r["close"] - 1).iloc[:-1]
    target_stored = pd.DataFrame({"target_range": d["target_range"].iloc[:-1].reset_index(drop=True),
                                  "target_close_ret": f["target_close_ret"].iloc[:-1].reset_index(drop=True)})
    target_expected = pd.DataFrame({"target_range": expected_range.reset_index(drop=True),
                                    "target_close_ret": expected_close.reset_index(drop=True)})
    targets = compare_columns(target_stored, target_expected, ["target_range", "target_close_ret"])
    counts = {k:v["mismatches"] for k,v in {**check1, **check2, **targets}.items()}
    total_bad = sum(counts.values())

    recorded_pit = json.loads(E002_PIT_META.read_text(encoding="utf-8")) if E002_PIT_META.exists() else None
    report = {
        "status": "PASS" if total_bad == 0 else "FAIL",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "DEV ONLY: 14 E001 market predictors + 2 E002 range predictors + first 1715 labels",
        "n_development": n,
        "n_holdout_reserved": 429,
        "holdout_rows_parsed": False,
        "full_csv_bytes_hashed_for_source_identity": True,
        "source_sha256": source_sha,
        "development_first_feature_day": str(first.date()),
        "development_last_feature_day": str(last.date()),
        "development_last_label_day": str((last + pd.Timedelta(days=1)).date()),
        "first_reserved_holdout_feature_day_derived": str((last + pd.Timedelta(days=1)).date()),
        "model_input_checks": {**check1, **check2},
        "target_checks_excluding_last_development_row": targets,
        "n_total_feature_or_target_mismatches": total_bad,
        "funding_audit_status_from_existing_report": None if recorded_pit is None else recorded_pit.get("status", "see separate report"),
        "label_purge_protocol_E002": meta2.get("label_purge_days", None),
        "boundary_warning": "Last development label day equals first reserved holdout FEATURE day. Before final static fit, conservatively exclude last development label row and use a one-day purge.",
        "remaining_cautions": [
            "Arithmetic reconstruction is not an independent proof of Binance vendor publication times.",
            "Model features assume forecasting after UTC day t close; no same-day intraday forecast is claimed.",
            "All market predictors checked against causal current/past-only OHLCV formulas; ETF and macro are not inputs to E001-E003 tested models.",
            "E001 CV used adjacent train/validation blocks without an explicit purge; review its as-of model refit convention separately.",
            "No holdout labels or forecasts evaluated by this script.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print("=== PRE-HOLDOUT MARKET FEATURE AUDIT (DEVELOPMENT ONLY) ===")
    print("Status:", result["status"])
    print("Market input columns:", len(result["model_input_checks"]))
    print("Mismatches:", result["n_total_feature_or_target_mismatches"])
    print("Development dates:", result["development_first_feature_day"], "to", result["development_last_feature_day"])
    print("Last development label day:", result["development_last_label_day"])
    print("Conservative final fit: 1-day label purge REQUIRED")
    print("Vendor publication-time audit: NOT PROVEN")
    print("Report:", OUTPUT)
    if result["status"] != "PASS":
        raise SystemExit("Audit failed: resolve mismatches before final holdout")
