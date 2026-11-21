import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quantlab.data.quality import load_table, inspect_table

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/raw/btc_daily_features.csv")
    p.add_argument("--output", default="reports/data_quality_report.json")
    a = p.parse_args()
    df = load_table(a.input)
    report = inspect_table(df)
    out = ROOT / a.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wiersze: {report['rows']:,}; kolumny: {report['columns_count']}")
    print(f"Braki: {report['missing_cells']}; duplikaty wierszy: {report['duplicate_rows']}")
    print(f"Kolumna czasu: {report['timestamp_column']}")
    if report['timestamp_column']:
        print(f"Zakres UTC: {report.get('first_timestamp_utc')} — {report.get('last_timestamp_utc')}")
        print(f"Niepoprawne daty: {report.get('invalid_timestamps')}; duplikaty czasu: {report.get('duplicate_timestamps')}")
    print(f"Raport: {out}")
if __name__ == "__main__":
    main()
