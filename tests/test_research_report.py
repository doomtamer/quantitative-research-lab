"""Sanity checks for standalone CV report generator."""
from __future__ import annotations
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'generate_research_report.py'
spec = importlib.util.spec_from_file_location('qrl_report_generator', MODULE)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def test_metric_computation():
    m = report.metric(np.array([0.0, 2.0]), np.array([1.0, 0.0]))
    assert np.isclose(m['mae'], 1.5)
    assert np.isclose(m['rmse'], np.sqrt(2.5))


def test_paired_gain_sign_and_count():
    df = pd.DataFrame({'actual':[1.0, 1.0, 1.0, 1.0, 1.0],
                       'ref':[0.0]*5, 'candidate':[0.5]*5})
    v = report.hac_comparison(df, 'ref', 'candidate')
    assert v['n']==5
    assert v['winning_days']==5
    assert np.isclose(v['delta_mae'], 0.5)


def test_sha256(tmp_path):
    import hashlib
    p=tmp_path/'a.txt'
    p.write_bytes(b'abc')
    assert report.sha256(p) == hashlib.sha256(b'abc').hexdigest()
