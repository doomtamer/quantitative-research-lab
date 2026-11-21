import argparse, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quantlab.data.quality import load_table
from quantlab.research.baseline import regression_baselines

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/raw/btc_daily_features.csv")
    p.add_argument("--target", default="target_close_ret")
    p.add_argument("--train-fraction", type=float, default=0.8)
    a = p.parse_args()
    df = load_table(a.input)
    if a.target not in df.columns:
        raise SystemExit(f"Brak targetu {a.target}. Dostępne kolumny: {', '.join(map(str, df.columns))}")
    y = df[a.target].dropna()
    split = int(len(y) * a.train_fraction)
    for name, m in regression_baselines(y, split).items():
        print(f"{name}: MAE={m['mae']:.8f}, RMSE={m['rmse']:.8f}, n={m['test_observations']}")
if __name__ == "__main__":
    main()
