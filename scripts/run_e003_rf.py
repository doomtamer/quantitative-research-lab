#!/usr/bin/env python3
"""E003 nonlinear range CV, frozen E002 development and folds, untouched holdout.

Run from project root: uv run python scripts/run_e003_rf.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from quantlab.research.e003_rf import (
    RF_KWARGS, RF_FEATURES_MARKET, RF_FEATURES_FUNDING, predict_fold,
)
from run_e002_funding import load_frozen_research
from run_e002_ridge import sha256, SOURCE_PATH, DEV_PATH, BASELINE_PRED_PATH, OUT_DIR as E002_DIR

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "E003_range_nonlinear"
PIT_PATH = E002_DIR / "funding_point_in_time_audit.json"
FUNDING_PATH = E002_DIR / "funding_cv_predictions.csv"
FUNDING_META_PATH = E002_DIR / "funding_cv_metadata.json"
RIDGE_PATH = E002_DIR / "ridge_cv_predictions.csv"


def verify_prerequisites(frame: pd.DataFrame, ref: pd.DataFrame,
                         folds: list[tuple[int, int, int]]) -> dict:
    for p in (PIT_PATH, FUNDING_META_PATH, FUNDING_PATH):
        if not p.is_file():
            raise FileNotFoundError(f"Missing frozen E002 prerequisite: {p}")
    pit = json.loads(PIT_PATH.read_text(encoding="utf-8"))
    m2_meta = json.loads(FUNDING_META_PATH.read_text(encoding="utf-8"))
    if not (pit.get("reconstruction_passed") is True and pit.get("holdout_labels_read") is False):
        raise ValueError("Funding source-to-feature audit not verified")
    if pit.get("source_feature_sha256") != sha256(SOURCE_PATH):
        raise ValueError("PIT audit source hash differs from frozen dataset")
    if m2_meta.get("holdout_evaluated") is not False or int(m2_meta.get("n_holdout_reserved", -1)) != 429:
        raise ValueError("Final holdout status uncertain")
    for key, path in [("source_feature_sha256", SOURCE_PATH),
                      ("development_file_sha256", DEV_PATH),
                      ("m1_prediction_sha256", RIDGE_PATH),
                      ("baseline_prediction_sha256", BASELINE_PRED_PATH)]:
        if m2_meta.get(key) != sha256(path):
            raise ValueError(f"Frozen E002 hash changed: {key}")
    frozen_folds = [(x["train_stop_exclusive"], x["validation_start"], x["validation_stop_exclusive"])
                    for x in m2_meta.get("cv_folds", [])]
    if folds != frozen_folds:
        raise ValueError("Walk-forward folds changed")
    if len(frame) != 1716 or len(ref) != 1030:
        raise ValueError("Unexpected development size or validation count")
    if len(RF_FEATURES_MARKET) != 16 or len(RF_FEATURES_FUNDING) != 23:
        raise ValueError("Changed frozen features")
    if m2_meta.get("m1_features") != list(RF_FEATURES_MARKET) or m2_meta.get("m2_incremental_funding_features") != list(RF_FEATURES_FUNDING[16:]):
        raise ValueError("E002 feature set changed")
    e2pred = pd.read_csv(FUNDING_PATH, usecols=["date", "fold", "actual", "B2_mean_7", "M1_market_ridge", "M2_market_funding_ridge"])
    if len(e2pred) != len(ref) or e2pred["date"].duplicated().any():
        raise ValueError("E002 M2 predictions invalid")
    if not e2pred[["date", "fold"]].equals(ref[["date", "fold"]]):
        raise ValueError("M2/M1 fold dates do not align")
    for col in ["actual", "B2_mean_7", "M1_market_ridge"]:
        if not np.allclose(e2pred[col].to_numpy(dtype=float), ref[col].to_numpy(dtype=float), rtol=0, atol=1e-10):
            raise ValueError(f"E002 predictions differ: {col}")
    return {"funding_pit_sha256": sha256(PIT_PATH), "e002_m2_predictions_sha256": sha256(FUNDING_PATH),
            "e002_m2_metadata_sha256": sha256(FUNDING_META_PATH)}


def evaluate(frame: pd.DataFrame, ref: pd.DataFrame,
             folds: list[tuple[int, int, int]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_pred = []
    all_metrics = []
    for i, (train_stop, start, stop) in enumerate(folds, 1):
        label = f"WF{i}"
        ref_fold = ref.loc[ref["fold"] == label].reset_index(drop=True)
        valid = frame.iloc[start:stop]
        if len(ref_fold) != len(valid) or not np.array_equal(ref_fold["date"].to_numpy(), valid["date"].to_numpy()):
            raise ValueError("Frozen fold dates mismatch")
        true_y = valid["target_range"].to_numpy(dtype=float)
        if not np.allclose(true_y, ref_fold["actual"].to_numpy(dtype=float), rtol=0, atol=1e-10):
            raise ValueError("Frozen targets mismatch")
        m3, neg3 = predict_fold(frame, RF_FEATURES_MARKET, train_stop, start, stop)
        m4, neg4 = predict_fold(frame, RF_FEATURES_FUNDING, train_stop, start, stop)
        rows = pd.DataFrame({
            "date": ref_fold["date"], "fold": label, "actual": true_y,
            "B2_mean_7": ref_fold["B2_mean_7"],
            "M1_market_ridge": ref_fold["M1_market_ridge"],
            "M3_market_rf": m3,
            "M4_market_funding_rf": m4,
        })
        all_pred.append(rows)
        for model in ("B2_mean_7", "M1_market_ridge", "M3_market_rf", "M4_market_funding_rf"):
            err = true_y - rows[model].to_numpy(dtype=float)
            all_metrics.append({"fold": label, "model": model,
                "MAE": float(np.mean(np.abs(err))),
                "RMSE": float(np.sqrt(np.mean(np.square(err)))),
                "n_train": train_stop, "n_validation": len(valid),
                "n_negative_raw_clipped": neg3 if model == "M3_market_rf" else neg4 if model == "M4_market_funding_rf" else 0})
    daily = pd.concat(all_pred, ignore_index=True)
    metrics = pd.DataFrame(all_metrics)
    pooled_rows = []
    for model in ("B2_mean_7", "M1_market_ridge", "M3_market_rf", "M4_market_funding_rf"):
        err = (daily["actual"] - daily[model]).to_numpy(dtype=float)
        pooled_rows.append({"model": model, "MAE": float(np.abs(err).mean()),
                            "RMSE": float(np.sqrt(np.square(err).mean()))})
    pooled = pd.DataFrame(pooled_rows).sort_values("MAE")
    return daily, metrics, pooled


def main() -> None:
    frame, ref, folds = load_frozen_research()  # reads first 1716 source rows only
    provenance = verify_prerequisites(frame, ref, folds)
    preds, metrics, pooled = evaluate(frame, ref, folds)
    if len(preds) != 1030 or preds["date"].duplicated().any():
        raise ValueError("Unexpected E003 CV output")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    preds.to_csv(OUT_DIR / "rf_cv_predictions.csv", index=False)
    metrics.to_csv(OUT_DIR / "rf_cv_metrics.csv", index=False)
    pooled.to_csv(OUT_DIR / "rf_cv_pooled.csv", index=False)
    meta = {
        "experiment": "E003_range_nonlinear", "phase": "exploratory_cv_development_only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_evaluated": False, "n_development": len(frame), "n_holdout_reserved": 429,
        "n_cv_predictions": len(preds),
        "target": "(high[t+1] - low[t+1]) / close[t]",
        "source_sha256": sha256(SOURCE_PATH),
        "development_file_sha256": sha256(DEV_PATH),
        "baseline_prediction_sha256": sha256(BASELINE_PRED_PATH),
        "m1_prediction_sha256": sha256(RIDGE_PATH),
        **provenance,
        "market_features": list(RF_FEATURES_MARKET),
        "funding_features_added": list(RF_FEATURES_FUNDING[16:]),
        "rf_parameters": RF_KWARGS,
        "preprocessing": "Median imputer fitted only on each training fold; no scaler for RF",
        "label_purge_days": 1,
        "folds": [{"train_stop_exclusive": a, "validation_start": b, "validation_stop_exclusive": c}
                  for a, b, c in folds],
        "primary_metric": "pooled MAE",
        "primary_comparison": "M3_market_rf vs B2_mean_7",
        "secondary_comparison": "M4_market_funding_rf vs M3_market_rf",
        "research_limitation": "Exploratory: E002 development CV results were seen before E003 architecture chosen; "
                               "same CV dates reused. No independent confirmation or holdout evaluation.",
        "pit_limitation": "Funding event timestamps and feature reconstruction checked; actual vendor availability not independently verified.",
    }
    (OUT_DIR / "rf_cv_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("E003 — RANDOM FOREST RANGE (DEVELOPMENT ONLY)")
    print(f"Development: {len(frame)} | CV predictions: {len(preds)} | holdout untouched: 429")
    print("Fixed RF hyperparameters:", RF_KWARGS)
    print("\nPooled errors (lower is better):")
    print(pooled.to_string(index=False, float_format=lambda x: f"{x:.8f}"))
    print("\nMAE by fold:")
    print(metrics.pivot(index="fold", columns="model", values="MAE").to_string(float_format=lambda x: f"{x:.8f}"))
    print("\nExploratory E003 CV only. No holdout used. No hyperparameter tuning performed.")
    print("Reports:", OUT_DIR)

if __name__ == "__main__":
    main()
