# E001–E003 report generator

Copy package directories into `quantitative-research-lab` (merge existing folders).

Run from the root project directory:

```powershell
uv run python scripts/generate_research_report.py
```

Open `reports/E001_E003_synthesis/E001_E003_research_report.html` in a browser.
The script also writes a Markdown report, four PNG charts and a JSON SHA-256 manifest.

**Safety and integrity:** It reads only stored *development CV predictions* and experiment metadata and existing audits in `reports/E001_funding_rate`, `reports/E002_range` and `reports/E003_range_nonlinear`. It does not load `data/`, train models, evaluate the 429-row holdout or modify source experiments. It fails on date/fold or shared prediction mismatches. Re-running a report is not equivalent to reproducing the original experiments from raw data; a later end-to-end training replay and independent point-in-time availability audit remain necessary.

The report's p-values are exploratory and should not be promoted as confirmatory evidence. A Holm adjustment is provided across the seven listed tests only, not the full space of explored modeling decisions.
