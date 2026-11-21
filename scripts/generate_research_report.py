#!/usr/bin/env python3
"""Generate reproducible DEV-only E001-E003 synthesis; NEVER reads model holdout.

Run from quantitative-research-lab project root:
  uv run python scripts/generate_research_report.py
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'E001_E003_synthesis'
E1 = ROOT / 'reports' / 'E001_funding_rate'
E2 = ROOT / 'reports' / 'E002_range'
E3 = ROOT / 'reports' / 'E003_range_nonlinear'

INPUTS = {
    'E001 predictions': E1 / 'cv_predictions.csv',
    'E001 metadata': E1 / 'cv_metadata.json',
    'E001 funding audit': E1 / 'funding_audit.json',
    'E002 baseline predictions': E2 / 'baseline_cv_predictions.csv',
    'E002 ridge predictions': E2 / 'ridge_cv_predictions.csv',
    'E002 funding predictions': E2 / 'funding_cv_predictions.csv',
    'E002 baseline metadata': E2 / 'baseline_cv_metadata.json',
    'E002 ridge metadata': E2 / 'ridge_cv_metadata.json',
    'E002 funding metadata': E2 / 'funding_cv_metadata.json',
    'E002 PIT audit': E2 / 'funding_point_in_time_audit.json',
    'E002 target audit': E2 / 'target_audit.json',
    'E003 predictions': E3 / 'rf_cv_predictions.csv',
    'E003 metadata': E3 / 'rf_cv_metadata.json',
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_and_check():
    missing = [str(p.relative_to(ROOT)) for p in INPUTS.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError('Missing experiment files:\n' + '\n'.join(missing))
    metas = {}
    for label, path in INPUTS.items():
        if path.suffix == '.json':
            metas[label] = json.loads(path.read_text(encoding='utf-8-sig'))
            obj = metas[label]
            if isinstance(obj, dict) and obj.get('holdout_evaluated') is True:
                raise ValueError(f'Holdout reported as evaluated: {label}. Stop; investigate.')

    def load(path, columns):
        df = pd.read_csv(path)
        miss = sorted(set(columns) - set(df.columns))
        if miss:
            raise ValueError(f'{path.name}: missing columns {miss}')
        if df[['date', 'fold']].isna().any().any():
            raise ValueError(f'{path.name}: missing date/fold')
        if df.duplicated(['date', 'fold']).any() or df['date'].duplicated().any():
            raise ValueError(f'{path.name}: duplicate validation date')
        if df[columns].isna().any().any():
            raise ValueError(f'{path.name}: missing predictions/targets')
        df['date'] = pd.to_datetime(df['date'], utc=True, errors='raise')
        return df.sort_values('date').reset_index(drop=True)

    e1 = load(INPUTS['E001 predictions'], ['actual', 'M0_zero', 'M0_mean', 'M1_market', 'M2_market_funding'])
    b = load(INPUTS['E002 baseline predictions'], ['actual', 'B0_train_mean', 'B1_persistence', 'B2_mean_7', 'B3_mean_30_exploratory'])
    r = load(INPUTS['E002 ridge predictions'], ['actual', 'B2_mean_7', 'M1_market_ridge'])
    f = load(INPUTS['E002 funding predictions'], ['actual', 'B2_mean_7', 'M1_market_ridge', 'M2_market_funding_ridge'])
    rf = load(INPUTS['E003 predictions'], ['actual', 'B2_mean_7', 'M3_market_rf', 'M4_market_funding_rf'])

    if not (len(e1) == len(b) == len(r) == len(f) == len(rf) == 1030):
        raise ValueError('Expected 1030 CV forecasts in every file; investigate before reporting')
    for other in [b, r, f, rf]:
        if not e1[['date', 'fold']].equals(other[['date', 'fold']]):
            raise ValueError('CV date/fold mismatch; cannot pool models')
    for other in [r, f, rf]:
        np.testing.assert_allclose(b['actual'], other['actual'], rtol=0, atol=1e-10)
        np.testing.assert_allclose(b['B2_mean_7'], other['B2_mean_7'], rtol=0, atol=1e-10)
    np.testing.assert_allclose(r['M1_market_ridge'], f['M1_market_ridge'], rtol=0, atol=1e-10)
    if e1['actual'].isna().any():
        raise ValueError('Missing E001 target')

    # Cross-check declared holdout status and source fingerprint where available.
    expected_sources = set()
    for key in ['E001 metadata', 'E002 funding metadata', 'E003 metadata']:
        h = (metas[key].get('source_feature_sha256')
             or metas[key].get('data_sha256') or metas[key].get('source_sha256'))
        if h:
            expected_sources.add(h)
    if len(expected_sources) > 1:
        raise ValueError('Different underlying feature file hashes across experiments')
    e2dev = metas['E002 funding metadata'].get('development_file_sha256')
    e3dev = metas['E003 metadata'].get('development_file_sha256')
    if e2dev and e3dev and e2dev != e3dev:
        raise ValueError('Different development CSV hashes between E002 and E003')

    return e1, b, r, f, rf, metas, next(iter(expected_sources), None)


def metric(y: np.ndarray, pred: np.ndarray):
    err = y - pred
    return {'mae': float(np.abs(err).mean()), 'rmse': float(np.sqrt(np.mean(err**2)))}


def hac_comparison(data: pd.DataFrame, name_a: str, name_b: str, lag: int = 7):
    y = data['actual'].to_numpy()
    d = np.abs(y - data[name_a].to_numpy()) - np.abs(y - data[name_b].to_numpy())
    result = sm.OLS(d, np.ones((len(d), 1))).fit(cov_type='HAC', cov_kwds={'maxlags': lag})
    lower, upper = result.conf_int()[0].tolist()
    return {'reference': name_a, 'candidate': name_b, 'delta_mae': float(d.mean()),
            'p': float(result.pvalues[0]), 't': float(result.tvalues[0]),
            'ci_low': lower, 'ci_high': upper, 'winning_days': int((d > 0).sum()), 'n': len(d), 'hac_lag': lag}


def combined_frames(e1, b, r, f, rf):
    ret = e1[['date', 'fold', 'actual', 'M0_zero', 'M0_mean', 'M1_market', 'M2_market_funding']].copy()
    ranges = b[['date', 'fold', 'actual', 'B0_train_mean', 'B1_persistence', 'B2_mean_7', 'B3_mean_30_exploratory']].copy()
    for frame, col in [(r, 'M1_market_ridge'), (f, 'M2_market_funding_ridge'), (rf, 'M3_market_rf'), (rf, 'M4_market_funding_rf')]:
        ranges[col] = frame[col]
    return ret, ranges


def plot_figures(ret, ranges):
    OUT.mkdir(parents=True, exist_ok=True)
    ret_names = ['M0_zero', 'M0_mean', 'M1_market', 'M2_market_funding']
    range_names = ['B2_mean_7', 'M2_market_funding_ridge', 'M1_market_ridge', 'M4_market_funding_rf', 'M3_market_rf']
    labels = ['B2 / 7D', 'M2 / Ridge + Funding', 'M1 / Ridge', 'M4 / RF + Funding', 'M3 / RF']

    plt.rcParams.update({'font.size': 10, 'figure.dpi': 125})
    fig, ax = plt.subplots(figsize=(8.7, 4.2))
    vals = [100 * metric(ranges['actual'].to_numpy(), ranges[n].to_numpy())['mae'] for n in range_names]
    bars = ax.barh(labels, vals)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.22)
    ax.set_xlabel('MAE (% of prior close)')
    ax.set_title('E002–E003 | Range forecast MAE (lower is better)')
    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + .015, bar.get_y() + bar.get_height()/2, f'{val:.3f}%', va='center')
    fig.tight_layout()
    fig.savefig(OUT / 'range_mae.png')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    folds = sorted(ranges['fold'].unique())
    for n, label in [('B2_mean_7','B2 / 7D'),('M2_market_funding_ridge','M2 / Ridge + funding'),('M4_market_funding_rf','M4 / RF + funding')]:
        values = [100 * np.abs(g['actual'].to_numpy() - g[n].to_numpy()).mean() for fold in folds for _, g in [(fold, ranges[ranges['fold'] == fold])]]
        ax.plot(folds, values, marker='o', label=label)
    ax.set_ylabel('MAE (% of prior close)')
    ax.set_title('E002–E003 | Fold-by-fold MAE')
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / 'range_folds.png')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.7, 4.2))
    rv = [100 * metric(ret['actual'].to_numpy(), ret[n].to_numpy())['mae'] for n in ret_names]
    ax.bar(['Zero', 'Historical mean', 'Market Ridge', 'Market + funding Ridge'], rv)
    ax.set_ylabel('MAE (percentage points of daily return)')
    ax.set_ylim(0, max(rv)*1.2)
    ax.tick_params(axis='x', labelrotation=15)
    ax.set_title('E001 | Next-day return forecast MAE')
    for i, x in enumerate(rv):
        ax.text(i, x + .02, f'{x:.3f}%', ha='center')
    fig.tight_layout()
    fig.savefig(OUT / 'return_mae.png')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.2, 4.0))
    ax.hist(100 * ranges['actual'].to_numpy(), bins=45, edgecolor='none')
    ax.set_xlabel('Realized next-day high–low range (% prior close)')
    ax.set_ylabel('CV observations')
    ax.set_title('E002–E003 | Observed range distribution (CV only)')
    fig.tight_layout()
    fig.savefig(OUT / 'range_hist.png')
    plt.close(fig)


def make_report(ret, ranges, metas, source_hash):
    ret_models = ['M0_zero', 'M0_mean', 'M1_market', 'M2_market_funding']
    range_models = ['B0_train_mean', 'B1_persistence', 'B2_mean_7', 'B3_mean_30_exploratory',
                    'M1_market_ridge', 'M2_market_funding_ridge', 'M3_market_rf', 'M4_market_funding_rf']
    mr = {name: metric(ret['actual'].to_numpy(), ret[name].to_numpy()) for name in ret_models}
    mg = {name: metric(ranges['actual'].to_numpy(), ranges[name].to_numpy()) for name in range_models}
    comparisons = [
        ('E001: M1 -> M2', hac_comparison(ret, 'M1_market', 'M2_market_funding')),
        ('E001: Zero -> M1', hac_comparison(ret, 'M0_zero', 'M1_market')),
        ('E002: M1 -> M2', hac_comparison(ranges, 'M1_market_ridge', 'M2_market_funding_ridge')),
        ('E002: B2 -> M2', hac_comparison(ranges, 'B2_mean_7', 'M2_market_funding_ridge')),
        ('E003: M3 -> M4', hac_comparison(ranges, 'M3_market_rf', 'M4_market_funding_rf')),
        ('E003: B2 -> M4', hac_comparison(ranges, 'B2_mean_7', 'M4_market_funding_rf')),
        ('E003: M2 -> M4', hac_comparison(ranges, 'M2_market_funding_ridge', 'M4_market_funding_rf')),
    ]
    holm = multipletests([v['p'] for _, v in comparisons], alpha=0.05, method='holm')[1]
    for (_, value), adj in zip(comparisons, holm):
        value['p_holm_exploratory'] = float(adj)

    def fmt(x): return f'{x:.8f}'
    def row_models(table):
        return '\n'.join(f'| `{key}` | {100*value["mae"]:.4f}% | {100*value["rmse"]:.4f}% |' for key,value in sorted(table.items(), key=lambda kv:kv[1]['mae']))
    def cmp_rows():
        return '\n'.join(f'| {label} | {value["delta_mae"]*10000:+.2f} | {value["p"]:.4f} | {value["p_holm_exploratory"]:.4f} | {value["winning_days"]}/{value["n"]} |' for label,value in comparisons)

    fold_rows = []
    for fold, g in ranges.groupby('fold', sort=True):
        values = [100*np.abs(g['actual'] - g[n]).mean() for n in ['B2_mean_7', 'M2_market_funding_ridge', 'M4_market_funding_rf']]
        fold_rows.append(f'| {fold} | '+ ' | '.join(f'{v:.4f}%' for v in values) + ' |')

    asof = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    e1meta=metas['E001 metadata']; e2meta=metas['E002 funding metadata']
    md = f'''# Quantitative Research Lab — Research Synthesis E001–E003

**Status:** DEVELOPMENT-ONLY | EXPLORATORY | **FINAL HOLDOUT NOT EVALUATED**  
**Generated:** {asof}  
**Instrument:** Binance BTCUSDT USD-M futures | **Daily UTC**  
**Development rows:** {e1meta.get('n_development', '1716')} | **CV forecasts:** {len(ret)} | **Reserved holdout:** {e1meta.get('n_holdout', '429')}  
**Source feature SHA-256:** `{source_hash or 'unavailable'}`

## Executive summary

- **E001 (next-day return):** Funding features do not help Ridge in this tested specification; the zero-return baseline outperforms both Ridge variants on pooled MAE. The funding comparison is sensitive to the earliest validation fold.
- **E002 (next-day high–low range):** The simple **7-day trailing range mean (B2)** has the lowest pooled MAE. Adding funding improves Ridge's MAE, but the exploratory HAC(7) comparison is not significant at 5%.
- **E003 (nonlinear range):** Adding funding improves Random Forest, but this model still loses to B2 on pooled MAE. Extra complexity does not demonstrate a robust MAE advantage.
- **Decision:** Freeze models and protocol; audit point-in-time timing, feature pipelines and rerun reproducibility **before any single final holdout evaluation**.

## 1. Research questions and targets

**E001:** Does funding rate incrementally improve next-day signed return forecasts over a market-feature Ridge? The target is `target_close_ret`.  
**E002–E003:** Does funding improve forecasts of the next-day **high–low range**, and does nonlinear modeling beat simple volatility persistence? The target is:

`target_range[t] = (high[t+1] - low[t+1]) / close[t]`

Prediction is made **after the UTC close of day t**. This is a normalized range, not intraday realized variance. The return and range targets **must not be ranked together**.

## 2. Data and evaluation protocol

- Base period: 2021-01-01 through 2026-11-15 feature days; 2145 labeled rows.
- Development: 1716 chronological rows; final reserve: 429 rows. No holdout labels were accessed by this report generator.
- Five expanding-window validation folds; 1030 forecast dates, no duplicated dates. A one-day training/validation label purge is recorded in M2 E002 metadata.
- Preprocessing recorded for Ridge: train-fold-only median imputation and standardization. Ridge `alpha=10` fixed. RF settings fixed: 300 trees, `max_depth=6`, `min_samples_leaf=20`, `max_features=0.8`, `bootstrap=True`, random seed 2026.
- Primary metric: pooled **MAE**; secondary: **RMSE**. Differences use paired absolute losses with indicative HAC(7) inference. Exploratory Holm adjustment across the seven *displayed* comparisons is included; it is **not** a correction for all prior research choices.
- This report reads **only CV prediction files, experiment metadata and past audits**, never the full market dataset or holdout files.

## 3. E001 — return forecasting

![E001 return MAE](return_mae.png)

| Model | MAE | RMSE |
|---|---:|---:|
{row_models(mr)}

**Interpretation.** In this configuration, additional funding features worsen Ridge's pooled MAE. A negative result is a valid experimental finding, but not proof that funding has no predictive information in any model or horizon.

## 4. E002–E003 — daily range forecasting

![Range model MAE](range_mae.png)

| Model | MAE | RMSE |
|---|---:|---:|
{row_models(mg)}

![Range errors across folds](range_folds.png)

| Fold | B2 (7-day mean) | M2 (Ridge + funding) | M4 (RF + funding) |
|---|---:|---:|---:|
{chr(10).join(fold_rows)}

![Observed CV ranges](range_hist.png)

The large realized ranges in the CV distribution should not be removed based on their future size, nor should future realized ranges be used as an ex-ante regime-selection variable.

## 5. Exploratory paired error tests

**Sign:** positive improvement = candidate has lower MAE than reference. Values are in **basis points of normalized daily target** (1 bp = 0.0001).

| Comparison (reference -> candidate) | MAE improvement (bp) | HAC(7) p | Holm-adjusted p* | Candidate wins |
|---|---:|---:|---:|---:|
{cmp_rows()}

*Holm adjustment applies only to the seven reported tests and is for transparent sensitivity analysis, **not** confirmatory inference after the many decisions made on this shared CV sample. HAC asymptotics and comparisons across folds require caution.*

The observed improvement from funding in M2 and M4 is not sufficient evidence for a stable out-of-sample edge. Models share the same development windows, so E002 and E003 are not independent replications.

## 6. Data integrity and point-in-time status

- Previously reported E001 funding audit: 6438 events over 2146 days, 3 events/day, 0 duplicate timestamps, 0 abnormal 8-hour intervals and no feature funding count mismatches.
- Previously reported E002 funding source-to-feature audit: 5148 development events, 7 derived features checked, 0 reconstruction mismatches.
- **Not proven:** Binance historical vendor publication timestamps, true point-in-time availability of every market/macro/positioning series, and full replay reproducibility from an immutable code commit.
- **Known limitations:** missing ETF history prior to spot ETF launches, missing macro series in current dataset, and historical revisions or later publication of some third-party data. No economic backtest or transaction costs were studied.

## 7. Study decisions and risk of bias

1. Development-only results E001–E003 are **exploratory**. Report all attempted models, including worse-performing ones.
2. B2 is the **primary frozen MAE baseline** for a later one-time holdout check. M2 is the **secondary RMSE-oriented candidate**. M4 remains exploratory and should only be included in holdout if explicitly locked in advance.
3. Do **not** tune parameters, swap primary metric, select a model by the final sample, or inspect holdout results to revise the model.
4. Before the final evaluation, verify feature generation and true as-of availability, data ordering, train-only transforms, target/feature lag, and source hashes; record code version (Git commit) and dependency lockfile.
5. If the final holdout fails, report failure rather than using it to fit another model.

## 8. Reproducibility and files

The machine-readable run manifest includes SHA-256 hashes for all source reports consumed by this synthesis. Re-running this script on the same files reproduces the numeric tables and charts (timestamps and environment metadata may change).

**Important:** Reproducing this report from stored predictions does **not** establish end-to-end reproducibility of training. That requires re-running CV from raw data on a frozen code revision and comparing prediction hashes.
'''
    (OUT / 'E001_E003_research_report.md').write_text(md, encoding='utf-8')
    return mr, mg, comparisons, md


def make_html(md):
    # Self-contained HTML narrative using the generated Markdown, without external assets.
    # Minimal Markdown parser sufficient for this document; styled for printing and reviewing.
    lines = md.splitlines()
    out = []
    in_table = False
    def format_inline(s):
        z = html.escape(s)
        # Recreate local figure images as inlined data URLs.
        if z.startswith('![') and '](' in z and z.endswith(')'):
            alt = z[2:z.index('](')]
            path = z[z.index('](')+2:-1]
            data = base64.b64encode((OUT / path).read_bytes()).decode('ascii')
            return f'<figure><img alt="{html.escape(alt)}" src="data:image/png;base64,{data}"><figcaption>{html.escape(alt)}</figcaption></figure>'
        import re
        z = re.sub(r'`([^`]+)`', r'<code>\1</code>', z)
        z = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', z)
        return z
    for line in lines:
        t = line.strip()
        if t.startswith('|'):
            if t.replace('|','').replace(':','').replace('-','').strip()=='' :
                continue
            cells = [c.strip() for c in t.strip('|').split('|')]
            if not in_table:
                out.append('<table>')
                in_table = True
                tag='th'
            else:
                tag='td'
            out.append('<tr>' + ''.join(f'<{tag}>{format_inline(c)}</{tag}>' for c in cells) + '</tr>')
            continue
        if in_table:
            out.append('</table>')
            in_table=False
        if not t:
            continue
        if t.startswith('# '): out.append(f'<h1>{format_inline(t[2:])}</h1>')
        elif t.startswith('## '): out.append(f'<h2>{format_inline(t[3:])}</h2>')
        elif t.startswith('### '): out.append(f'<h3>{format_inline(t[4:])}</h3>')
        elif t.startswith('- '): out.append(f'<p class="bullet">• {format_inline(t[2:])}</p>')
        elif t[0:2].isdigit() and '. ' in t[:4]: out.append(f'<p class="bullet">{format_inline(t)}</p>')
        else: out.append(f'<p>{format_inline(t)}</p>')
    if in_table: out.append('</table>')
    css='''body{font:15px/1.65 system-ui,Segoe UI,Arial,sans-serif;color:#172236;background:#edf2f7;margin:0}main{max-width:950px;margin:30px auto;padding:38px 50px;background:white;box-shadow:0 4px 32px #1a304b18;border-radius:14px}h1{font-size:28px;letter-spacing:-.5px;color:#102841}h2{border-top:1px solid #dce6ed;padding-top:22px;margin-top:28px;font-size:21px;color:#0d3a55}h3{font-size:17px}table{width:100%;border-collapse:collapse;margin:15px 0 25px;font-size:13px}th{text-align:left;color:white;background:#184764}td,th{padding:9px 10px;border-bottom:1px solid #e2e9ee}tr:nth-child(even) td{background:#f4f7f9}code{background:#eef4f8;border-radius:4px;padding:2px 4px;font-size:.91em;overflow-wrap:anywhere}figure{margin:23px 0}img{width:100%;max-height:480px;object-fit:contain}figcaption{color:#678;font-size:12px;text-align:center}.bullet{margin:5px 0 5px 14px}p{margin:10px 0}@media print{body{background:white}main{padding:0;margin:0;box-shadow:none}h2{break-after:avoid}figure{break-inside:avoid}}'''
    doc='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Quantitative Research Lab | E001-E003</title><style>'+css+'</style></head><body><main>'+''.join(out)+'</main></body></html>'
    (OUT / 'E001_E003_research_report.html').write_text(doc,encoding='utf-8')


def main():
    e1, b, r, f, rf, metas, source_hash = load_and_check()
    ret, ranges = combined_frames(e1,b,r,f,rf)
    plot_figures(ret, ranges)
    mr,mg,comp,md = make_report(ret, ranges, metas, source_hash)
    make_html(md)
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'scope':'development CV predictions only; final holdout not read',
                'n_cv_predictions':len(ret), 'n_development':1716,'n_holdout_reserved':429,
                'source_feature_sha256': source_hash,
                'inputs_sha256':{str(p.relative_to(ROOT)): sha256(p) for p in INPUTS.values()},
                'python':platform.python_version(), 'pandas':pd.__version__,
                'numpy':np.__version__,'statsmodels':sm.__version__, 'matplotlib':matplotlib.__version__,
                'return_models':mr, 'range_models':mg,
                'paired_hac_7_exploratory':{label:x for label,x in comp}}
    (OUT / 'report_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print('E001-E003 REPORT GENERATED (CV ONLY; HOLDOUT UNTOUCHED)')
    print(f'Checks: {len(ret)} matching CV dates across 5 files; no mismatched targets or B2 forecasts')
    print(f'Primary range baseline B2 MAE: {mg["B2_mean_7"]["mae"]:.8f}')
    print(f'M2 Ridge+Funding MAE: {mg["M2_market_funding_ridge"]["mae"]:.8f}')
    print(f'M4 RF+Funding MAE: {mg["M4_market_funding_rf"]["mae"]:.8f}')
    for path in ['E001_E003_research_report.html','E001_E003_research_report.md','report_manifest.json']:
        print(f'Saved: {OUT / path}')
    print('Open the HTML report in your browser; it has embedded figures.')

if __name__ == '__main__':
    main()
