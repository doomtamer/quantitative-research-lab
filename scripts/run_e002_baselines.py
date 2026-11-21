#!/usr/bin/env python3
"""E002: preregistered daily-range benchmark CV, development data ONLY.

B0: in-sample mean of prior observed target labels (with 1-day purge).
B1: yesterday's completed candle normalized by preceding close, r_t.
B2: mean of last 7 r values, through t.
B3: mean of last 30 r values, exploratory only.

No models are fitted. Never loads or evaluates holdout labels.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data/processed/e002_development_target.csv"
AUDIT = ROOT / "reports/E002_range/target_audit.json"
OUT = ROOT / "reports/E002_range"
N_FOLDS = 5


def folds(n: int, k: int = N_FOLDS) -> list[tuple[int, int, int]]:
    """Return (train_stop_exclusive, valid_start, valid_stop).

    One-row gap keeps every train target label strictly before the first
    validation feature day. Fold dates reproduce E001's boundaries.
    """
    min_train = max(365, int(n * 0.4))
    if min_train >= n or n - min_train < k:
        raise ValueError("Insufficient development data")
    edges = np.linspace(min_train, n, k + 1).astype(int)
    return [(int(edges[i]) - 1, int(edges[i]), int(edges[i + 1])) for i in range(k)]


def load_development() -> pd.DataFrame:
    if not DEV.is_file() or not AUDIT.is_file():
        raise FileNotFoundError("Run scripts/run_e002_target_audit.py first")
    meta = json.loads(AUDIT.read_text(encoding="utf-8"))
    if meta.get("holdout_target_evaluated") is not False:
        raise ValueError("Audit metadata does not guarantee untouched holdout")
    df = pd.read_csv(DEV)
    required = ["date", "target_range", "e002_range_today", "e002_range_mean_7", "e002_range_mean_30"]
    if any(c not in df.columns for c in required):
        raise ValueError("Missing required E002 baseline columns")
    if len(df) != int(meta["n_development"]):
        raise ValueError("Development dataset size mismatch")
    dates = pd.to_datetime(df["date"], utc=True, errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Invalid development dates")
    if not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError("Missing calendar dates")
    if dates.iloc[-1].date().isoformat() != meta["dev_last_feature_day"]:
        raise ValueError("Development end does not match frozen audit")
    df["date"] = dates
    for col in required[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    y = df["target_range"].to_numpy(dtype=float)
    if not np.isfinite(y).all() or (y < 0).any():
        raise ValueError("Target must be finite and nonnegative")
    return df


def evaluate(df: pd.DataFrame):
    predictions = []
    metrics = []
    models = {"B0_train_mean": None, "B1_persistence": "e002_range_today",
              "B2_mean_7": "e002_range_mean_7", "B3_mean_30_exploratory": "e002_range_mean_30"}
    for i, (stop, start, end) in enumerate(folds(len(df)), start=1):
        train = df.iloc[:stop]
        valid = df.iloc[start:end]
        y = valid["target_range"].to_numpy(dtype=float)
        if len(train) < 365:
            raise ValueError("Unexpectedly short training segment")
        p = {"B0_train_mean": np.full(len(valid), train["target_range"].mean())}
        for model_name, col in models.items():
            if col is None:
                continue
            values = valid[col].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError(f"Invalid {col} in {i}-th validation fold")
            p[model_name] = values
        row = {"date": valid["date"].dt.strftime("%Y-%m-%d").to_numpy(),
               "fold": [f"WF{i}"] * len(valid), "actual": y, **p}
        predictions.append(pd.DataFrame(row))
        for name, pred in p.items():
            err = y - pred
            metrics.append({"fold": f"WF{i}", "model": name, "n_train": len(train),
                            "n_valid": len(valid), "MAE": float(np.abs(err).mean()),
                            "RMSE": float(np.sqrt(np.square(err).mean()))})
    result = pd.DataFrame(metrics)
    daily = pd.concat(predictions, ignore_index=True)
    pooled = pd.DataFrame([{
        "model": m, "MAE": float(np.abs(daily["actual"] - daily[m]).mean()),
        "RMSE": float(np.sqrt(np.square(daily["actual"] - daily[m]).mean())),
    } for m in models]).sort_values("MAE")
    return result, daily, pooled


def main():
    df = load_development()
    metrics, daily, pooled = evaluate(df)
    OUT.mkdir(exist_ok=True, parents=True)
    metrics.to_csv(OUT / "baseline_cv_metrics.csv", index=False)
    daily.to_csv(OUT / "baseline_cv_predictions.csv", index=False)
    pooled.to_csv(OUT / "baseline_cv_pooled.csv", index=False)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    metadata = {
        "experiment": "E002_range", "phase": "baseline_cv_development_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "development_file_sha256": hashlib.sha256(DEV.read_bytes()).hexdigest(),
        "source_feature_sha256": audit["source_feature_sha256"],
        "n_development": len(df), "n_holdout_reserved": audit["n_holdout_reserve"],
        "holdout_evaluated": False, "n_folds": N_FOLDS,
        "n_validation_predictions": len(daily),
        "validation_fold_indices": [{"train_stop_exclusive": a, "validation_start": b, "validation_stop_exclusive": c}
                                    for a, b, c in folds(len(df))],
        "training_label_purge_days": 1,
        "primary_models": ["B0_train_mean", "B1_persistence", "B2_mean_7"],
        "exploratory_models": ["B3_mean_30_exploratory"],
        "target": "(high[t+1]-low[t+1])/close[t]",
        "units": "fraction; 0.04 means 4%",
        "methodology": "E001-matched expanding-window validation boundaries; B0 fitted on earlier known labels with 1-row gap; others use observed data through t",
    }
    (OUT / "baseline_cv_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("E002 — BENCHMARK WALK-FORWARD (DEVELOPMENT ONLY)")
    print(f"Development days: {len(df)} | CV predictions: {len(daily)} | final holdout: untouched")
    print("\nPooled errors (lower is better):")
    print(pooled.to_string(index=False, float_format=lambda x: f"{x:.8f}"))
    print("\nMAE by fold:")
    print(metrics.pivot(index="fold", columns="model", values="MAE").to_string(float_format=lambda x: f"{x:.8f}"))
    print("\nReports written to:", OUT)
    print("No machine-learning models trained. No holdout used.")


if __name__ == "__main__":
    main()
