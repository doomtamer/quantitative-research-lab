#!/usr/bin/env python3
"""Audit E002 funding source->features on DEVELOPMENT dates; no holdout labels read.

Run from project root: uv run python scripts/run_e002_pit_audit.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quantlab.research.e002_pit import FUNDING_COLS, compare_funding, reconstruct_funding

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/processed/btc_daily_features.csv"
RAW = ROOT / "data/raw/binance_funding_events.csv"
META = ROOT / "reports/E002_range/funding_cv_metadata.json"
OUT = ROOT / "reports/E002_range/funding_point_in_time_audit.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    for p in (SOURCE, RAW, META):
        if not p.is_file():
            raise FileNotFoundError(f"Missing required file: {p}")
    meta = json.loads(META.read_text(encoding="utf-8"))
    if meta.get("holdout_evaluated") is not False or int(meta.get("n_holdout_reserved", -1)) != 429:
        raise ValueError("Holdout boundary inconsistent with frozen E002 metadata")
    if sha256(SOURCE) != meta.get("source_feature_sha256"):
        raise ValueError("Source data changed since E002 CV. Do not silently replace it.")
    n = int(meta["n_development"])
    if n != 1716:
        raise ValueError("Unexpected development-set size")
    if list(meta["m2_incremental_funding_features"]) != list(FUNDING_COLS):
        raise ValueError("Funding feature specification changed")
    if int(meta["n_cv_predictions"]) != 1030:
        raise ValueError("Unexpected CV prediction count")
    frame = pd.read_csv(SOURCE, usecols=["date", *FUNDING_COLS], nrows=n)
    dates = pd.to_datetime(frame["date"], utc=True, format="mixed", errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Invalid development dates")
    if not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError("Development dates not contiguous")
    dates_idx = pd.DatetimeIndex(dates)
    if str(dates_idx[-1].date()) != "2025-09-12":
        raise ValueError("Unexpected frozen development cutoff")
    raw = pd.read_csv(RAW, usecols=["funding_time", "funding_rate", "source"])
    raw["funding_time"] = pd.to_datetime(raw["funding_time"], utc=True, format="mixed", errors="coerce")
    if raw["funding_time"].isna().any():
        raise ValueError("Invalid funding timestamps")
    subset = raw.loc[(raw["funding_time"] >= dates_idx[0]) &
                     (raw["funding_time"] < dates_idx[-1] + pd.Timedelta(days=1))].copy()
    reconstructed = reconstruct_funding(subset, dates_idx)
    details = compare_funding(reconstructed, frame)
    source_counts = {str(k): int(v) for k, v in subset["source"].value_counts().items()}
    result = {
        "experiment": "E002_range",
        "phase": "funding_source_to_feature_audit_development_only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_feature_sha256": sha256(SOURCE),
        "n_development_days": n,
        "n_raw_events_dev": len(subset),
        "development_first": str(dates_idx[0].date()),
        "development_last": str(dates_idx[-1].date()),
        "source_counts_dev": source_counts,
        "feature_comparisons": details,
        "reconstruction_passed": True,
        "holdout_labels_read": False,
        "limitations": [
            "Timestamp checks verify that source events are attributed to days <= feature day t, not independently that vendor publication occurred on time.",
            "This script does not verify exchange-source payload authenticity or intraday ingestion timestamps.",
            "Code-level chronological CV and fold-local preprocessing were audited separately."
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("E002 FUNDING SOURCE->FEATURE AUDIT PASSED (DEVELOPMENT ONLY)")
    print("Development days:", n, "| events:", len(subset), "| expected:", n * 3)
    print("Sources:", source_counts)
    print("Funding columns verified:", len(details))
    print("All feature reconstruction mismatches:", sum(v["mismatch_count"] for v in details.values()))
    print("Holdout labels not read.")
    print("Report:", OUT)
    print("Caution: true vendor publication time is not proven by timestamps alone.")


if __name__ == "__main__":
    main()
