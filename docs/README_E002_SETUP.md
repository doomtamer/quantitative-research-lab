# E002 — instalacja i audyt targetu

1. Rozpakuj ZIP do folderu `quantitative-research-lab` (scalaj foldery).
2. Skrypt **nie pobiera nowych danych** i **nie trenuje** żadnego modelu.
3. W projekcie muszą istnieć `data/processed/btc_daily_raw.csv`, `data/processed/btc_daily_features.csv` oraz `reports/E001_funding_rate/cv_metadata.json`.
4. Uruchom `uv run python scripts/run_e002_target_audit.py`.
5. Raport: `reports/E002_range/target_audit.json`; dane tylko z części development: `data/processed/e002_development_target.csv`.
6. Testy: `uv run python -m pytest tests/test_e002_target.py -v`.

Jeśli SHA256 CSV nie zgadza się z E001, audyt zatrzyma się celowo: nie wolno po cichu zmienić zbioru i finalnego holdoutu. Jeśli raw ma inną nazwę, najpierw sprawdź zawartość `data/processed`.
