from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'finalize_research_report.py'
spec = importlib.util.spec_from_file_location('finalize_research_report', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def put_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding='utf-8')


def make_files(root):
    folder = root / 'reports' / 'E001_E003_synthesis'
    folder.mkdir(parents=True)
    original_md = '# Old CV only report\n\n**Status:** HOLDOUT NOT EVALUATED\n'
    original_html = '<!doctype html><html><head><title>Old</title><style>body{color:black}</style></head><body><main><h1>Old report</h1><p>CV ONLY</p></main></body></html>'
    (folder / 'E001_E003_research_report.md').write_text(original_md)
    (folder / 'E001_E003_research_report.html').write_text(original_html)
    put_json(folder / 'report_manifest.json', {
        'source_feature_sha256': 'abc123',
        'n_cv_predictions': 1030,
        'n_development': 1716,
        'n_holdout_reserved': 429,
        'range_models': {
            'B2_mean_7': {'mae': 0.01590324,'rmse':0.02236505},
            'M2_market_funding_ridge':{'mae':0.01633891,'rmse':0.02193867},
        },
    })
    manifest_path = root / 'reports' / 'pre_holdout_audit' / 'E002_FROZEN_MANIFEST.json'
    put_json(manifest_path, {'status':'PREFLIGHT_PASSED',
        'publication_time_proven':False,
        'holdout_labels_parsed_during_preflight':False,
        'n_training':1715, 'n_holdout':429, 'purged_feature_date':'2025-09-12',
        'files_sha256':{'data/processed/btc_daily_features.csv':'abc123'},
    })
    manifest_hash = module.digest(manifest_path)
    holdout = root / 'reports' / 'E002_final_holdout'
    put_json(holdout / 'ATTEMPT_STARTED.json', {'frozen_manifest_sha256':manifest_hash})
    a=0.01379781150348301
    b=0.013804715136463735
    put_json(holdout / 'holdout_summary.json', {
        'status':'FINAL_HOLDOUT_EVALUATED_ONCE',
        'created_utc':'2026-11-21T13:36:09.945970+00:00',
        'n_training':1715,'n_holdout':429,'purged_day':'2025-09-12',
        'first_date':'2025-09-13','last_date':'2026-11-15',
        'target':'(high[t+1]-low[t+1])/close[t]',
        'model_primary':'B2_mean_7','model_secondary':'M2_market_funding_ridge',
        'model_alpha':10.0,'n_features':23,
        'metrics':{'B2_mean_7':{'MAE':a,'RMSE':0.019973740598893907},
                   'M2_market_funding_ridge':{'MAE':b,'RMSE':0.019023506140199854}},
        'paired_absolute_loss_HAC':{
            '7':{'mean_improvement_M2_over_B2':a-b,'p_two_sided':0.9879916008384967,'ci95':[-0.0009059132455268597,0.0008921059795654122]},
            '14':{'mean_improvement_M2_over_B2':a-b,'p_two_sided':0.9882591479813162,'ci95':[-0.0009264011465229719,0.0009125938805615244]},
            '30':{'mean_improvement_M2_over_B2':a-b,'p_two_sided':0.988573113076969,'ci95':[-0.0009516670555328215,0.000937859789571374]},
        },
        'evaluation_manifest_sha256':manifest_hash,
    })
    return original_md, original_html


def test_presentation_only_preserves_originals(tmp_path):
    oldmd,oldhtml = make_files(tmp_path)
    md, html, provenance = module.finalize(tmp_path)
    assert md.exists() and html.exists() and provenance.exists()
    assert '4.76%' in md.read_text(encoding='utf-8')
    assert '0.987992' in md.read_text(encoding='utf-8')
    assert 'Appendix' in md.read_text(encoding='utf-8')
    assert md.read_text(encoding='utf-8').endswith(oldmd+'\n')
    assert 'Old report' in html.read_text(encoding='utf-8')
    assert html.read_text(encoding='utf-8').count('</main>') == 1
    assert (tmp_path/'reports/E001_E003_synthesis/E001_E003_research_report.md').read_text() == oldmd
    assert (tmp_path/'reports/E001_E003_synthesis/E001_E003_research_report.html').read_text() == oldhtml
    assert not (tmp_path/'reports/E002_final_holdout/holdout_predictions.csv').exists()
    assert json.loads(provenance.read_text())['re_evaluation_performed'] is False


def test_detects_broken_marker_link(tmp_path):
    make_files(tmp_path)
    path = tmp_path / 'reports' / 'E002_final_holdout' / 'ATTEMPT_STARTED.json'
    put_json(path, {'frozen_manifest_sha256':'bad'})
    with pytest.raises(ValueError, match='marker hash'):
        module.finalize(tmp_path)


def test_detects_source_change(tmp_path):
    make_files(tmp_path)
    path=tmp_path/'reports/E001_E003_synthesis/report_manifest.json'
    info=json.loads(path.read_text())
    info['source_feature_sha256']='wrong'
    put_json(path, info)
    with pytest.raises(ValueError, match='source data digest'):
        module.finalize(tmp_path)


def test_detects_metric_conflict(tmp_path):
    make_files(tmp_path)
    path=tmp_path/'reports/E002_final_holdout/holdout_summary.json'
    info=json.loads(path.read_text())
    info['paired_absolute_loss_HAC']['7']['mean_improvement_M2_over_B2']=0.123
    put_json(path, info)
    with pytest.raises(ValueError, match='inconsistent'):
        module.finalize(tmp_path)
