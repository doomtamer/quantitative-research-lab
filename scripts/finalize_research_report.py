#!/usr/bin/env python3
"""Append verified one-time E002 holdout evidence to E001-E003 research synthesis.

Reads existing reports and provenance only; no training, fitting, prediction,
feature construction, or computation of additional holdout statistics.
Run from QRL root: uv run python scripts/finalize_research_report.py
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / 'reports' / 'E001_E003_synthesis'
PRE = ROOT / 'reports' / 'pre_holdout_audit'
HOLD = ROOT / 'reports' / 'E002_final_holdout'
INPUT = {
    'development_markdown': SYN / 'E001_E003_research_report.md',
    'development_html': SYN / 'E001_E003_research_report.html',
    'development_manifest': SYN / 'report_manifest.json',
    'frozen_manifest': PRE / 'E002_FROZEN_MANIFEST.json',
    'one_time_marker': HOLD / 'ATTEMPT_STARTED.json',
    'holdout_summary': HOLD / 'holdout_summary.json',
}
OUTPUT_MD = SYN / 'E001_E003_FINAL_research_report.md'
OUTPUT_HTML = SYN / 'E001_E003_FINAL_research_report.html'
OUTPUT_PROVENANCE = SYN / 'E001_E003_FINAL_report_manifest.json'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(obj, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return obj


def validate_data(base: Path = ROOT) -> tuple[dict, dict, dict, dict]:
    paths = {k: base / p.relative_to(ROOT) for k, p in INPUT.items()}
    for label, p in paths.items():
        if not p.is_file():
            raise FileNotFoundError(f'Missing {label}: {p}')
    dev = load_json(paths['development_manifest'])
    frozen = load_json(paths['frozen_manifest'])
    marker = load_json(paths['one_time_marker'])
    result = load_json(paths['holdout_summary'])

    expected = digest(paths['frozen_manifest'])
    if marker.get('frozen_manifest_sha256') != expected:
        raise ValueError('ATTEMPT_STARTED marker hash differs from frozen manifest')
    if result.get('evaluation_manifest_sha256') != expected:
        raise ValueError('Holdout result is not tied to frozen manifest hash')
    if frozen.get('status') != 'PREFLIGHT_PASSED':
        raise ValueError('Preflight did not pass')
    if frozen.get('publication_time_proven') is not False:
        raise ValueError('Unexpected data publication-time status; investigate')
    if frozen.get('holdout_labels_parsed_during_preflight') is not False:
        raise ValueError('Preflight claims holdout labels were parsed')
    if result.get('status') != 'FINAL_HOLDOUT_EVALUATED_ONCE':
        raise ValueError('Holdout result not marked as one-time final')
    if (result.get('n_training'), result.get('n_holdout'), result.get('purged_day')) != (1715, 429, '2025-09-12'):
        raise ValueError('Holdout split differs from frozen protocol')
    if (frozen.get('n_training'), frozen.get('n_holdout'), frozen.get('purged_feature_date')) != (1715, 429, '2025-09-12'):
        raise ValueError('Frozen split differs from agreed protocol')
    if (result.get('first_date'), result.get('last_date')) != ('2025-09-13', '2026-11-15'):
        raise ValueError('Unexpected holdout feature dates')
    if (result.get('model_primary'), result.get('model_secondary')) != ('B2_mean_7', 'M2_market_funding_ridge'):
        raise ValueError('Unexpected primary/secondary models')
    if result.get('target') != '(high[t+1]-low[t+1])/close[t]':
        raise ValueError('Unexpected holdout target')
    if result.get('model_alpha') != 10 or result.get('n_features') != 23:
        raise ValueError('Model parameters not frozen as expected')
    dev_src = dev.get('source_feature_sha256')
    frozen_src = frozen.get('files_sha256', {}).get('data/processed/btc_daily_features.csv')
    if not dev_src or dev_src != frozen_src:
        raise ValueError('CV source data digest does not match frozen data digest')
    if (dev.get('n_cv_predictions'), dev.get('n_development'), dev.get('n_holdout_reserved')) != (1030, 1716, 429):
        raise ValueError('Development report data counts differ from protocol')
    cv = dev.get('range_models', {})
    for name in ('B2_mean_7', 'M2_market_funding_ridge'):
        if name not in cv:
            raise ValueError(f'Missing {name} in original CV report')
        if name not in result.get('metrics', {}):
            raise ValueError(f'Missing {name} in holdout summary')
        for v in [cv[name].get('mae'), cv[name].get('rmse'), result['metrics'][name].get('MAE'), result['metrics'][name].get('RMSE')]:
            if not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0:
                raise ValueError('Invalid model metric')
    tests = result.get('paired_absolute_loss_HAC', {})
    for lag in ('7', '14', '30'):
        t = tests.get(lag, {})
        if not (isinstance(t.get('ci95'), list) and len(t['ci95']) == 2):
            raise ValueError(f'Missing HAC interval for lag {lag}')
        if not 0 <= t.get('p_two_sided', -1) <= 1:
            raise ValueError(f'Invalid p-value for HAC({lag})')
    observed_delta = result['metrics']['B2_mean_7']['MAE'] - result['metrics']['M2_market_funding_ridge']['MAE']
    if abs(observed_delta - tests['7']['mean_improvement_M2_over_B2']) > 1e-10:
        raise ValueError('Holdout reported mean difference inconsistent with holdout metrics')
    return dev, frozen, marker, result


def sections(dev: dict, result: dict) -> tuple[str, str]:
    cv = dev['range_models']
    metrics = result['metrics']
    b2, m2 = metrics['B2_mean_7'], metrics['M2_market_funding_ridge']
    b2cv, m2cv = cv['B2_mean_7'], cv['M2_market_funding_ridge']
    p7 = result['paired_absolute_loss_HAC']['7']
    p14 = result['paired_absolute_loss_HAC']['14']
    p30 = result['paired_absolute_loss_HAC']['30']
    d = b2['MAE'] - m2['MAE']
    rmse_gain = 100 * (b2['RMSE'] - m2['RMSE']) / b2['RMSE']
    created = result['created_utc']
    def pc(v: float) -> str:
        return f'{100*v:.4f}%'
    def ci(v):
        return f'[{100*v[0]:+.4f}; {100*v[1]:+.4f}] p.p.'
    rows = [
        ('B2 — trailing mean 7D', b2cv, b2),
        ('M2 — Ridge + funding', m2cv, m2),
    ]
    markdown_rows = '\n'.join(
        f'| {name} | {pc(vcv["mae"])} | {pc(vcv["rmse"])} | {pc(vh["MAE"])} | {pc(vh["RMSE"])} |'
        for name, vcv, vh in rows
    )
    md = f'''# Quantitative Research Lab — E001–E003 Final Research Report

**Status:** Final one-time E002 holdout evaluated; E001–E003 development studies exploratory.  
**Holdout evaluation timestamp (UTC):** {created}  
**Instrument:** Binance BTCUSDT USD-M futures | Daily UTC  
**Main target:** `(high[t+1] - low[t+1]) / close[t]`  
**Holdout:** 429 daily predictions ({result["first_date"]} to {result["last_date"]}, feature dates)

## Final executive conclusion

The **pre-specified primary model, B2 (seven-day trailing range mean), retains a marginally lower MAE** than the secondary M2 Ridge + funding model on the one-time final holdout. The difference is **{d*10000:+.4f} basis points** in favour of M2 (negative means M2 is worse), effectively negligible in point estimate, but **absence of evidence is not proof of equivalence**.

M2 yields a **{rmse_gain:.2f}% lower RMSE** than B2. This is a descriptive secondary-metric observation and does **not** isolate the incremental causal or predictive contribution of funding, because B2 and M2 differ in many features and their modeling method. No confirmatory inference for RMSE was pre-specified.

## Development versus one-time holdout

| Model | Development CV MAE | Development CV RMSE | Final holdout MAE | Final holdout RMSE |
|---|---:|---:|---:|---:|
{markdown_rows}

**Holdout design:** 1715 training observations; one training-label purge at feature date 2025-09-12; final 429 features from 2025-09-13 through 2026-11-15. The preprocessing for M2 was fit on training rows only. Ridge alpha = 10; 23 frozen features; negative predictions clipped to zero (0 such predictions occurred).

## Primary confirmatory comparison: paired absolute error

- Definition of MAE difference: `|actual − B2| − |actual − M2|`; positive values favour M2.
- Observed holdout mean difference: `{d:+.10f}` normalized units; **{d*100:+.6f} percentage points** of prior close.
- HAC(7) two-sided p-value: **{p7["p_two_sided"]:.6f}**; 95% CI for the difference: **{ci(p7["ci95"])}**.
- Sensitivity: HAC(14) p = {p14["p_two_sided"]:.6f}; HAC(30) p = {p30["p_two_sided"]:.6f}.
- **Conclusion:** There is no statistical evidence of an MAE difference in this test. This is **not a formal equivalence test**.

## How to interpret the final evidence

1. The development-only CV studies E001, E002 and E003 were exploratory, with repeated model comparisons on the same historical windows. Their nominal significance tests are not independent confirmation.
2. **B2 remains the primary choice under the pre-registered MAE criterion.** M2's smaller RMSE may warrant a separate, independently designed study on new future data; it does not change the primary result.
3. No post-holdout tuning, model selection, evaluator rerun or reuse of this holdout for a new confirmatory comparison is permitted. Any new hypothesis needs a **fresh future evaluation period** and separately frozen protocol.
4. The study is conditional: the **true availability/publication times of all vendor observations have not been independently verified**, so point-in-time correctness cannot be fully claimed.
5. High–low range is a normalized candle range, not intraday realized variance. This is forecasting research, not evidence that a live trading strategy is profitable; fees, spread, slippage and live execution are out of scope.

## Provenance and scope

- Results are sourced from the saved one-time `holdout_summary.json`, and development metrics from `report_manifest.json`.
- The one-time marker and the recorded evaluation manifest hash are checked against the frozen preflight manifest before report creation.
- This report generator **does not read holdout predictions, compute new holdout diagnostics, train a model, or call the evaluator**.
- Appendix below preserves the original CV report **exactly as it was generated before the holdout was opened**; its historical wording (e.g. “holdout not evaluated”) describes that earlier stage, not the present status.

---

# Appendix — Original pre-holdout E001–E003 development report (historical snapshot)

'''
    # HTML: prepared with existing original HTML's embedded charts and CSS.
    def h(x): return html.escape(str(x))
    hrows = ''.join(
        f'<tr><td>{h(name)}</td><td>{pc(vcv["mae"])}</td><td>{pc(vcv["rmse"])}</td>'
        f'<td>{pc(vh["MAE"])}</td><td>{pc(vh["RMSE"])}</td></tr>'
        for name, vcv, vh in rows
    )
    content = f'''<section class="final-section" id="final-outcome">
    <p class="final-tag">FINAL HOLDOUT · ONE-TIME ASSESSMENT · NOV 2026</p>
    <h1>E001–E003 | Final Research Report</h1>
    <p><b>BTCUSDT USD-M futures, daily UTC.</b> The E002 high–low range target is <code>(high[t+1] − low[t+1])/close[t]</code>. Final holdout: {result["n_holdout"]} dates ({h(result["first_date"])} to {h(result["last_date"])}).</p>
    <div class="final-kpis"><div><small>Primary holdout MAE · B2</small><strong>{pc(b2["MAE"])}</strong></div><div><small>Secondary holdout MAE · M2</small><strong>{pc(m2["MAE"])}</strong></div><div><small>M2 reduction in RMSE</small><strong>{rmse_gain:.2f}%</strong></div></div>
    <h2>Final executive conclusion</h2>
    <p>The pre-specified primary benchmark <b>B2 (trailing seven-day mean)</b> retains a marginally lower <b>MAE</b> than the secondary Ridge + funding model M2. The difference is {d*10000:+.4f} basis points when expressed as M2 improvement over B2 (negative means M2 is worse). There is <b>no statistical evidence of a difference in MAE</b>, but this is not a proof of equivalence.</p>
    <p>M2 achieved <b>{rmse_gain:.2f}% lower RMSE</b> on the one-time holdout. This is descriptive and does not by itself isolate the incremental contribution of funding, as model families differ.</p>
    <h2>Development CV vs. one-time holdout</h2><table><tr><th>Model</th><th>CV MAE</th><th>CV RMSE</th><th>Holdout MAE</th><th>Holdout RMSE</th></tr>{hrows}</table>
    <p><b>Frozen design:</b> 1715 training observations; 2025-09-12 purged; 429 holdout observations; Ridge alpha 10; 23 frozen inputs. No post-holdout tuning.</p>
    <h2>Paired absolute-loss test</h2>
    <p>Mean improvement (B2 loss − M2 loss): <b>{d:+.10f}</b> normalized units. HAC(7) p = <b>{p7["p_two_sided"]:.6f}</b>; 95% CI: <b>{ci(p7["ci95"])}</b>. Sensitivity: HAC(14) p = {p14["p_two_sided"]:.6f}; HAC(30) p = {p30["p_two_sided"]:.6f}. This fails to reject equal expected MAE under the chosen approximation; it is not a formal equivalence test.</p>
    <h2>Interpretation and limitations</h2>
    <p>The CV studies E001–E003 were exploratory and used shared development periods. B2 remains the preferred primary model according to pre-specified MAE. M2 has a descriptively lower RMSE but no proven MAE advantage. A new hypothesis would require a <b>fresh, future validation period</b>, not a repeated use of this holdout.</p>
    <p>The true availability timestamps of Binance observations have not been independently established. All conclusions are <b>conditional on historical publication timing</b>. This is normalized daily high–low range forecasting, not a live trading strategy or profit claim.</p>
    <p class="final-small">Generated from locked research summaries. No holdout predictions were parsed and no models were re-trained by the final report generator. Holdout evaluation UTC: {h(created)}.</p>
    </section>
    <section class="original-snapshot"><h2>Appendix — original pre-holdout development synthesis</h2><p><b>Historical snapshot:</b> the report below was written before the one-time holdout evaluation. Its statements about an “untouched holdout” refer to that earlier date only.</p>
    '''
    return md, content


def finalize(base: Path = ROOT) -> tuple[Path, Path, Path]:
    dev, frozen, marker, result = validate_data(base)
    syn = base / SYN.relative_to(ROOT)
    oldmd = (syn / 'E001_E003_research_report.md').read_text(encoding='utf-8-sig')
    oldhtml = (syn / 'E001_E003_research_report.html').read_text(encoding='utf-8-sig')
    md, head = sections(dev, result)
    finalmd = md + oldmd + '\n'
    if '<main>' not in oldhtml or '</main>' not in oldhtml:
        raise ValueError('Original HTML structure is unexpected; cannot preserve figures safely')
    # Keep original report/embedded figures unchanged as historical appendix.
    finalhtml = oldhtml.replace('<main>', '<main>\n' + head, 1).replace('</main>', '</section></main>', 1)
    finalhtml = re.sub(r'<title>.*?</title>', '<title>Quantitative Research Lab | Final E001–E003 Report</title>', finalhtml, count=1, flags=re.S)
    finalhtml = finalhtml.replace('</style>', '''
        .final-section {border-bottom:2px solid #d7e2ed;padding-bottom:30px;margin-bottom:32px}
        .final-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:20px 0}
        .final-kpis>div{background:#edf4f7;border:1px solid #dce6ed;border-radius:10px;padding:16px}
        .final-kpis small{color:#506277;font-size:12px;display:block}
        .final-kpis strong{display:block;color:#123450;font-size:24px;margin-top:4px}
        .final-tag{letter-spacing:.12em;color:#24617e;font-weight:700;font-size:11px}
        .final-small{font-size:12px;color:#5b6a76}
        .original-snapshot{border-top:1px solid #dae1e9}
        @media(max-width:700px){.final-kpis{grid-template-columns:1fr}}
        </style>''', 1)

    outmd = syn / OUTPUT_MD.name
    outhtml = syn / OUTPUT_HTML.name
    outmanifest = syn / OUTPUT_PROVENANCE.name
    # Overwrite generated final presentation only; originals and model artifacts are NEVER modified.
    outmd.write_text(finalmd, encoding='utf-8')
    outhtml.write_text(finalhtml, encoding='utf-8')
    sourcehash = {k: digest(base / p.relative_to(ROOT)) for k,p in INPUT.items()}
    report_manifest = {
        'status': 'FINAL_REPORT_POST_HOLDOUT; PRESENTATION_ONLY',
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'CV report and saved final summary; no holdout predictions or labels read by this tool',
        'n_cv_dates': 1030, 'n_holdout_dates': result['n_holdout'],
        'model_primary': result['model_primary'], 'model_secondary': result['model_secondary'],
        'frozen_manifest_sha256': digest(base / INPUT['frozen_manifest'].relative_to(ROOT)),
        'source_file_sha256': sourcehash,
        'generated_file_sha256': {outmd.name: digest(outmd), outhtml.name: digest(outhtml)},
        'vendor_publication_time_verified': False,
        're_evaluation_performed': False,
    }
    outmanifest.write_text(json.dumps(report_manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    return outmd, outhtml, outmanifest


if __name__ == '__main__':
    mdpath, htmlpath, manifestpath = finalize()
    print('E001-E003 FINAL REPORT CREATED (PRESENTATION ONLY)')
    print('Frozen manifest, marker and summary match; source feature SHA matches development synthesis.')
    print('No model fit, no prediction computation, no holdout analysis or re-evaluation performed.')
    for file in (htmlpath, mdpath, manifestpath):
        print('Saved:', file)
