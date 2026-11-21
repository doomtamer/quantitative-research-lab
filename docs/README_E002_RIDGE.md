# E002: M1 Ridge vs B2 mean-7

## Zamrożone zasady (przed uruchomieniem E002 Ridge CV)

- Cel: `target_range[t] = (high[t+1] - low[t+1]) / close[t]`.
- Dane: tylko 1716 dni development z istniejącego E002, bez ładowania 429 etykiet holdoutu.
- Walidacja: dokładnie 5 dotychczasowych okien E002 (po 206 prognoz), ekspandujący trening, odstęp 1 dnia między ostatnim trenowanym targetem a pierwszą obserwacją walidacyjną.
- Główna metryka: pooled MAE. Dodatkowo RMSE i MAE per fold.
- Punkt odniesienia: `B2_mean_7` z niezmienionego pliku `baseline_cv_predictions.csv`.
- Model: Ridge(alpha=10.0), bez strojenia na CV, z medianową imputacją i standaryzacją dopasowywanymi WYŁĄCZNIE na treningu każdego folda. Prognozy ujemne obcinane do 0.
- Cechy M1: 14 oryginalnych rynkowych cech E001 + `e002_range_today` i `e002_range_mean_7`. Bez funding, ETF, danych makro i wszystkich `target_*`.
- Najpierw test modelu rynkowego; dopiero później osobno ocena inkrementalnej wartości funding (M2), po przeglądzie metodologii i zamrożeniu specyfikacji.
- Całość CV jest analizą rozwojową. Ponieważ B2 wybrano po obejrzeniu CV benchmarków, nie przedstawiamy tego porównania jako niezależnego potwierdzenia efektu. Końcowy holdout pozostaje nienaruszony.

## Instalacja

Rozpakuj ZIP do katalogu głównego `quantitative-research-lab`, scalając foldery.

```powershell
uv run python -m pytest tests/test_e002_ridge.py -v
uv run python scripts/run_e002_ridge.py
```

## Wyniki

- `reports/E002_range/ridge_cv_predictions.csv`
- `reports/E002_range/ridge_cv_metrics.csv`
- `reports/E002_range/ridge_cv_pooled.csv`
- `reports/E002_range/ridge_cv_metadata.json`

Nie edytuj plików źródłowych BTC między audytem i CV; skrypt porównuje SHA256. Skrypt wymaga ukończonych kroków audytu targetu i B0/B1/B2/B3.
