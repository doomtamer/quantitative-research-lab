# E001–E003: final report assembler

This package produces a **new final portfolio report** from the E001–E003
historical development report and the **saved, already evaluated** E002 holdout
summary. It does **not** run the one-time holdout evaluator or retrain models.

## Installation

Extract `scripts/`, `tests/`, and `docs/` from the ZIP into the root of
`quantitative-research-lab` (merge folders).

## Run

From the project root in PowerShell:

```powershell
uv run python -m pytest tests/test_finalize_research_report.py -v
uv run python scripts/finalize_research_report.py
Start-Process .\reports\E001_E003_synthesis\E001_E003_FINAL_research_report.html
```

## Outputs

- `reports/E001_E003_synthesis/E001_E003_FINAL_research_report.html` (standalone HTML, embedded earlier figures)
- `reports/E001_E003_synthesis/E001_E003_FINAL_research_report.md` (Markdown; image references to existing PNG figures)
- `reports/E001_E003_synthesis/E001_E003_FINAL_report_manifest.json` (input and output SHA-256 hashes)

## Safety and lineage

1. The original `E001_E003_research_report.html` / `.md` and all evaluation artifacts are left **unchanged**.
2. The one-time evaluator is **never** imported or called; only `holdout_summary.json` is read from the evaluation directory.
3. The recorded frozen-manifest digest must agree with both `ATTEMPT_STARTED.json` and `holdout_summary.json`.
4. The frozen source-data hash must agree with the earlier CV report manifest.
5. The old CV report is appended as a labelled **historical pre-holdout appendix**, preserving its original contemporaneous wording.
6. Vendor release-time proof remains unavailable; the final report explicitly marks the result as conditional.
7. A new, independent validation period is required for new hypotheses or model selection after this final holdout.

If the script reports a provenance mismatch, **stop and investigate** instead of editing frozen artifacts or recomputing the one-time holdout.
