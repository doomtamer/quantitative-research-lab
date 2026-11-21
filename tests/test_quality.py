import pandas as pd
from quantlab.data.quality import inspect_table

def test_quality_report():
    df = pd.DataFrame({'timestamp': ['2024-01-01', '2024-01-02'], 'x': [1, None]})
    r = inspect_table(df)
    assert r['rows'] == 2
    assert r['missing_cells'] == 1
    assert r['timestamp_column'] == 'timestamp'
