#!/usr/bin/env python3
"""E002 M2 funding CV on FROZEN M1 folds and 1716 development rows only.

Usage: uv run python scripts/run_e002_funding.py
Never opens the final 429 holdout labels. Writes separate M2 report files.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from quantlab.research.e002_funding import FUNDING_FEATURES, M2_FEATURES, fit_fold_predict_m2
from quantlab.research.e002_ridge import ALPHA, FEATURES, cv_folds

# Import the already-tested M1 loader: it freezes source hashes, the
# development-only target, B2 predictions and all walk-forward fold boundaries.
from run_e002_ridge import (  # noqa: E402
    BASELINE_PRED_PATH,
    DEV_PATH,
    OUT_DIR,
    ROOT,
    SOURCE_PATH,
    load_and_verify,
    sha256,
)

M1_PRED_PATH = OUT_DIR / "ridge_cv_predictions.csv"
M1_META_PATH = OUT_DIR / "ridge_cv_metadata.json"
PRED_OUT = OUT_DIR / "funding_cv_predictions.csv"
METRIC_OUT = OUT_DIR / "funding_cv_metrics.csv"
POOLED_OUT = OUT_DIR / "funding_cv_pooled.csv"
META_OUT = OUT_DIR / "funding_cv_metadata.json"


def load_frozen_research() -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[int, int, int]]]:
    # source checks via M1 loader; source nrows=len(dev), so holdout is never
    # loaded into the model frame or its target summary.
    frame, baseline, frozen = load_and_verify()
    if not M1_PRED_PATH.is_file() or not M1_META_PATH.is_file():
        raise FileNotFoundError("Missing frozen Ridge M1 results; run E002 M1 first")
    meta = json.loads(M1_META_PATH.read_text(encoding="utf-8"))
    if meta.get("holdout_evaluated") is not False:
        raise ValueError("M1 metadata does not verify untouched holdout")
    if meta.get("source_feature_sha256") != sha256(SOURCE_PATH):
        raise ValueError("Source CSV changed since M1")
    if meta.get("development_file_sha256") != sha256(DEV_PATH):
        raise ValueError("Development CSV changed since M1")
    if meta.get("baseline_prediction_sha256") != sha256(BASELINE_PRED_PATH):
        raise ValueError("B2 prediction CSV changed since M1")
    if meta.get("feature_list") != list(FEATURES) or float(meta.get("ridge_alpha", -1)) != ALPHA:
        raise ValueError("M1 specification changed since CV")
    fold_indices = [(int(f["train_stop_exclusive"]), int(f["validation_start"]), int(f["validation_stop_exclusive"]))
                    for f in meta.get("validation_folds", [])]
    if fold_indices != frozen["folds"] or fold_indices != cv_folds(1716):
        raise ValueError("M1 folds differ from frozen E002 folds")

    m1 = pd.read_csv(M1_PRED_PATH)
    required = {"date", "fold", "actual", "B2_mean_7", "M1_market_ridge"}
    if len(m1) != 1030 or not required.issubset(m1.columns) or m1["date"].duplicated().any():
        raise ValueError("M1 prediction file invalid")
    if not m1[["actual", "B2_mean_7", "M1_market_ridge"]].apply(pd.to_numeric, errors="coerce").notna().all().all():
        raise ValueError("Missing or malformed M1 predictions")
    m1_dates = m1[["date", "fold", "actual", "B2_mean_7"]].reset_index(drop=True)
    b2_dates = baseline[["date", "fold", "actual", "B2_mean_7"]].reset_index(drop=True)
    if not m1_dates[["date", "fold"]].equals(b2_dates[["date", "fold"]]):
        raise ValueError("M1 / baseline validation dates or folds do not match")
    if not np.allclose(m1_dates[["actual", "B2_mean_7"]].to_numpy(dtype=float),
                       b2_dates[["actual", "B2_mean_7"]].to_numpy(dtype=float),
                       rtol=1e-10, atol=1e-10):
        raise ValueError("M1 / B2 target or baseline values disagree")

    source = pd.read_csv(SOURCE_PATH, nrows=len(frame), usecols=["date", *FUNDING_FEATURES])
    dates = pd.to_datetime(source["date"], utc=True, errors="coerce")
    if dates.isna().any() or not dates.dt.strftime("%Y-%m-%d").equals(frame["date"]):
        raise ValueError("Funding feature dates are not aligned to development")
    for col in FUNDING_FEATURES:
        frame[col] = pd.to_numeric(source[col], errors="coerce").to_numpy()
    if set(M2_FEATURES) - set(frame.columns):
        raise ValueError("Some M2 features unavailable")
    return frame, m1, fold_indices


def run_cv(frame: pd.DataFrame, m1: pd.DataFrame, folds: list[tuple[int, int, int]]):
    predictions, metrics = [], []
    for fold_no, (train_stop, valid_start, valid_stop) in enumerate(folds, start=1):
        valid = frame.iloc[valid_start:valid_stop]
        reference = m1.loc[m1["fold"] == f"WF{fold_no}"].reset_index(drop=True)
        if len(reference) != len(valid) or not np.array_equal(reference["date"].to_numpy(), valid["date"].to_numpy()):
            raise ValueError(f"M1 validation alignment failure in WF{fold_no}")
        target = valid["target_range"].to_numpy(dtype=float)
        if not np.allclose(target, reference["actual"].to_numpy(dtype=float), rtol=1e-10, atol=1e-10):
            raise ValueError(f"M1 target changed for WF{fold_no}")
        pred_m2, negatives = fit_fold_predict_m2(frame, train_stop, valid_start, valid_stop)
        this = pd.DataFrame({
            "date": valid["date"].to_numpy(), "fold": f"WF{fold_no}",
            "actual": target,
            "B2_mean_7": reference["B2_mean_7"].to_numpy(dtype=float),
            "M1_market_ridge": reference["M1_market_ridge"].to_numpy(dtype=float),
            "M2_market_funding_ridge": pred_m2,
        })
        predictions.append(this)
        for model in ("B2_mean_7", "M1_market_ridge", "M2_market_funding_ridge"):
            err = target - this[model].to_numpy(dtype=float)
            metrics.append({"fold": f"WF{fold_no}", "model": model,
                            "n_train_candidate": train_stop, "n_valid": len(valid),
                            "MAE": float(np.abs(err).mean()),
                            "RMSE": float(np.sqrt(np.square(err).mean())),
                            "negative_m2_raw_pred_count": negatives if model == "M2_market_funding_ridge" else 0})
    out = pd.concat(predictions, ignore_index=True)
    metric = pd.DataFrame(metrics)
    pooled = pd.DataFrame([
        {"model": model,
         "MAE": float(np.abs(out["actual"] - out[model]).mean()),
         "RMSE": float(np.sqrt(np.square(out["actual"] - out[model]).mean()))}
        for model in ("B2_mean_7", "M1_market_ridge", "M2_market_funding_ridge")
    ]).sort_values("MAE")
    return out, metric, pooled


def main() -> None:
    frame, m1, folds = load_frozen_research()
    predictions, metrics, pooled = run_cv(frame, m1, folds)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(PRED_OUT, index=False)
    metrics.to_csv(METRIC_OUT, index=False)
    pooled.to_csv(POOLED_OUT, index=False)
    improvement = float(
        np.abs(predictions["actual"] - predictions["M1_market_ridge"]).mean()
        - np.abs(predictions["actual"] - predictions["M2_market_funding_ridge"]).mean()
    )
    metadata = {
        "experiment": "E002_range",
        "phase": "M2_market_plus_funding_cv_development_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_evaluated": False,
        "n_development": len(frame),
        "n_holdout_reserved": 429,
        "n_cv_predictions": len(predictions),
        "source_feature_sha256": sha256(SOURCE_PATH),
        "development_file_sha256": sha256(DEV_PATH),
        "m1_prediction_sha256": sha256(M1_PRED_PATH),
        "m1_metadata_sha256": sha256(M1_META_PATH),
        "baseline_prediction_sha256": sha256(BASELINE_PRED_PATH),
        "target": "(high[t+1] - low[t+1]) / close[t]",
        "m1_features": list(FEATURES),
        "m2_incremental_funding_features": list(FUNDING_FEATURES),
        "m2_total_features": len(M2_FEATURES),
        "ridge_alpha": ALPHA,
        "training_preprocessing": "SimpleImputer(median) + StandardScaler fit only on each fold's training rows",
        "prediction_constraint": "clip negative Ridge predictions to 0 (same as M1)",
        "label_purge_days": 1,
        "cv_folds": [{"train_stop_exclusive": a, "validation_start": b, "validation_stop_exclusive": c}
                     for a, b, c in folds],
        "primary_metric": "pooled daily MAE",
        "primary_comparison": "M2_market_funding_ridge versus M1_market_ridge",
        "secondary_comparison": "M2_market_funding_ridge versus B2_mean_7",
        "pooled_mae_improvement_m2_vs_m1": improvement,
        "caution": "Exploratory development CV after prior E002 results were seen; no holdout inspected. "
                   "Feature publication timing requires a separate point-in-time audit.",
    }
    META_OUT.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("E002 — M2 FUNDING VS M1 AND B2 (DEVELOPMENT ONLY)")
    print("Development:", len(frame), "| CV predictions:", len(predictions), "| holdout untouched: 429")
    print("Models: M1 Ridge alpha", ALPHA, "| M2: identical Ridge +", len(FUNDING_FEATURES), "frozen funding features")
    print("Pooled errors (lower is better):")
    print(pooled.to_string(index=False, float_format=lambda n: f"{n:.8f}"))
    print("\nMAE by fold:")
    print(metrics.pivot(index="fold", columns="model", values="MAE").to_string(float_format=lambda n: f"{n:.8f}"))
    print(f"\nPooled MAE improvement M2 over M1: {improvement:+.8f} (positive = funding helped)")
    print("Raw negative M2 Ridge forecasts clipped:",
          metrics.loc[metrics.model == "M2_market_funding_ridge", "negative_m2_raw_pred_count"].sum())
    print("Reports:", OUT_DIR)
    print("No holdout used. No hyperparameter tuning performed.")


if __name__ == "__main__":
    main()
