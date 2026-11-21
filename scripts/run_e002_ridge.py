#!/usr/bin/env python3
"""E002 CV: predefined market-feature Ridge versus B2 7-day range baseline.

Run: uv run python scripts/run_e002_ridge.py
Development only; never opens holdout labels. Reads the audited E002 dataset,
its benchmark CV predictions and metadata, and the first development features.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from quantlab.research.e002_ridge import ALPHA, FEATURES, cv_folds, fit_fold_predict

ROOT = Path(__file__).resolve().parents[1]
DEV_PATH = ROOT / "data/processed/e002_development_target.csv"
SOURCE_PATH = ROOT / "data/processed/btc_daily_features.csv"
AUDIT_PATH = ROOT / "reports/E002_range/target_audit.json"
BASELINE_META_PATH = ROOT / "reports/E002_range/baseline_cv_metadata.json"
BASELINE_PRED_PATH = ROOT / "reports/E002_range/baseline_cv_predictions.csv"
OUT_DIR = ROOT / "reports/E002_range"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def load_and_verify() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    for path in (DEV_PATH, SOURCE_PATH, AUDIT_PATH, BASELINE_META_PATH, BASELINE_PRED_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"Missing prerequisite: {path}")
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    base_meta = json.loads(BASELINE_META_PATH.read_text(encoding="utf-8"))
    if audit.get("holdout_target_evaluated") is not False or base_meta.get("holdout_evaluated") is not False:
        raise ValueError("Metadata does not confirm intact holdout")
    if audit.get("n_development") != 1716 or audit.get("n_holdout_reserve") != 429:
        raise ValueError("Unexpected research split; review before running")
    if base_meta.get("n_development") != 1716 or base_meta.get("n_holdout_reserved") != 429:
        raise ValueError("Baseline split differs from target audit")
    if sha256(SOURCE_PATH) != audit.get("source_feature_sha256") or sha256(SOURCE_PATH) != base_meta.get("source_feature_sha256"):
        raise ValueError("Source CSV has changed since E002 target/baseline audit")
    if sha256(DEV_PATH) != base_meta.get("development_file_sha256"):
        raise ValueError("Development target changed since baseline CV")

    dev = pd.read_csv(DEV_PATH)
    if len(dev) != 1716 or not {"date", "target_range", "e002_range_today", "e002_range_mean_7"}.issubset(dev):
        raise ValueError("Malformed development target dataset")
    # Reading nrows explicitly prevents accidental use of final holdout rows.
    source_cols = ["date"] + [c for c in FEATURES if not c.startswith("e002_")]
    source = pd.read_csv(SOURCE_PATH, nrows=len(dev), usecols=source_cols)
    dev_dates = pd.to_datetime(dev["date"], utc=True, errors="coerce")
    src_dates = pd.to_datetime(source["date"], utc=True, errors="coerce")
    if (dev_dates.isna().any() or src_dates.isna().any() or dev_dates.duplicated().any()
            or not dev_dates.is_monotonic_increasing or not dev_dates.equals(src_dates)):
        raise ValueError("Development dates do not match frozen source rows")
    if not dev_dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError("Missing development dates")
    if str(dev_dates.iloc[-1].date()) != audit.get("dev_last_feature_day"):
        raise ValueError("Development cutoff changed")
    frame = dev[["date", "target_range", "e002_range_today", "e002_range_mean_7"]].copy()
    for col in source_cols[1:]:
        frame[col] = source[col].to_numpy()
    if not set(FEATURES).issubset(frame):
        raise ValueError("Missing predefined M1 features")
    for col in ["target_range", *FEATURES]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    y = frame["target_range"].to_numpy(dtype=float)
    if not np.isfinite(y).all() or (y < 0).any():
        raise ValueError("Invalid development labels")
    frame["date"] = dev_dates.dt.strftime("%Y-%m-%d")

    baseline = pd.read_csv(BASELINE_PRED_PATH)
    required = {"date", "fold", "actual", "B2_mean_7"}
    if not required.issubset(baseline) or len(baseline) != 1030:
        raise ValueError("Baseline predictions do not match expected CV")
    if baseline["date"].duplicated().any():
        raise ValueError("Duplicated baseline validation dates")
    expected = cv_folds(len(frame))
    prev_folds = [(int(x["train_stop_exclusive"]), int(x["validation_start"]), int(x["validation_stop_exclusive"]))
                  for x in base_meta.get("validation_fold_indices", [])]
    if prev_folds != expected:
        raise ValueError("Baseline fold boundaries are not identical")
    if str(base_meta.get("n_validation_predictions")) != "1030":
        raise ValueError("Unexpected number of validation days")
    return frame, baseline, {"audit": audit, "baseline_meta": base_meta, "folds": expected}


def evaluate(frame: pd.DataFrame, baseline: pd.DataFrame, frozen: dict):
    rows, metrics = [], []
    for fold_i, (train_stop, valid_start, valid_stop) in enumerate(frozen["folds"], start=1):
        valid = frame.iloc[valid_start:valid_stop]
        expected_b = baseline.loc[baseline["fold"] == f"WF{fold_i}"].reset_index(drop=True)
        if len(expected_b) != len(valid) or not np.array_equal(expected_b["date"].to_numpy(), valid["date"].to_numpy()):
            raise ValueError(f"Baseline dates do not match fold WF{fold_i}")
        if not np.allclose(expected_b["actual"], valid["target_range"], rtol=1e-10, atol=1e-10):
            raise ValueError(f"Target mismatch against baseline predictions in WF{fold_i}")
        pred, n_negative = fit_fold_predict(frame, train_stop, valid_start, valid_stop)
        target = valid["target_range"].to_numpy(dtype=float)
        b2 = expected_b["B2_mean_7"].to_numpy(dtype=float)
        if not np.isfinite(b2).all():
            raise ValueError("NaN baseline prediction")
        rows.append(pd.DataFrame({"date": valid["date"].to_numpy(), "fold": f"WF{fold_i}",
                                  "actual": target, "B2_mean_7": b2, "M1_market_ridge": pred}))
        for model, forecast in (("B2_mean_7", b2), ("M1_market_ridge", pred)):
            err = target - forecast
            metrics.append({"fold": f"WF{fold_i}", "model": model,
                            "n_train_candidate": train_stop, "n_valid": len(target),
                            "MAE": float(np.mean(np.abs(err))),
                            "RMSE": float(np.sqrt(np.mean(np.square(err)))),
                            "negative_ridge_raw_pred_count": n_negative if model == "M1_market_ridge" else 0})
    daily = pd.concat(rows, ignore_index=True)
    metric = pd.DataFrame(metrics)
    pooled = pd.DataFrame([{"model": m,
                           "MAE": float(np.abs(daily["actual"] - daily[m]).mean()),
                           "RMSE": float(np.sqrt(np.square(daily["actual"] - daily[m]).mean()))}
                           for m in ("B2_mean_7", "M1_market_ridge")]).sort_values("MAE")
    return daily, metric, pooled


def main() -> None:
    frame, baseline, frozen = load_and_verify()
    daily, metric, pooled = evaluate(frame, baseline, frozen)
    OUT_DIR.mkdir(exist_ok=True, parents=True)
    daily.to_csv(OUT_DIR / "ridge_cv_predictions.csv", index=False)
    metric.to_csv(OUT_DIR / "ridge_cv_metrics.csv", index=False)
    pooled.to_csv(OUT_DIR / "ridge_cv_pooled.csv", index=False)
    b2_error = float(np.abs(daily["actual"] - daily["B2_mean_7"]).mean())
    ridge_error = float(np.abs(daily["actual"] - daily["M1_market_ridge"]).mean())
    info = {
        "experiment": "E002_range", "phase": "M1_ridge_cv_development_only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_evaluated": False, "n_development": len(frame),
        "n_holdout_reserved": int(frozen["audit"]["n_holdout_reserve"]),
        "n_cv_predictions": len(daily), "source_feature_sha256": sha256(SOURCE_PATH),
        "development_file_sha256": sha256(DEV_PATH),
        "baseline_prediction_sha256": sha256(BASELINE_PRED_PATH),
        "target": frozen["audit"]["target_definition"],
        "feature_list": list(FEATURES), "ridge_alpha": ALPHA,
        "preprocessing": "SimpleImputer(median) and StandardScaler both fit ONLY on each training fold",
        "prediction_constraint": "clip Ridge forecasts to zero when negative; rule fixed before CV",
        "validation_folds": [{"train_stop_exclusive": a, "validation_start": b, "validation_stop_exclusive": c}
                             for a, b, c in frozen["folds"]],
        "label_purge_days": 1,
        "primary_baseline": "B2_mean_7",
        "primary_metric": "pooled daily MAE",
        "mae_improvement_ridge_over_b2": b2_error - ridge_error,
        "note": "Exploratory CV after reviewing benchmark CV; not independent confirmation. Do not tune on holdout.",
    }
    (OUT_DIR / "ridge_cv_metadata.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("E002 — RIDGE VS B2 (DEVELOPMENT ONLY)")
    print(f"Development: {len(frame)} | CV predictions: {len(daily)} | holdout untouched: 429")
    print("Fixed Ridge alpha:", ALPHA, "| features:", len(FEATURES))
    print("\nPooled errors (lower is better):")
    print(pooled.to_string(index=False, float_format=lambda x: f"{x:.8f}"))
    print("\nMAE by fold:")
    print(metric.pivot(index="fold", columns="model", values="MAE").to_string(float_format=lambda x: f"{x:.8f}"))
    print(f"\nPooled MAE improvement M1 over B2: {b2_error - ridge_error:+.8f} (positive means Ridge helped)")
    print("Raw negative Ridge forecasts, clipped to zero:", metric.loc[metric.model == "M1_market_ridge", "negative_ridge_raw_pred_count"].sum())
    print("Reports:", OUT_DIR)
    print("No holdout was used. No funding features included yet.")


if __name__ == "__main__":
    main()
