# Pobieranie danych BTCUSDT (Quantitative Research Lab)

## Uruchomienie w VS Code / PowerShell (Windows 11)

Rozpakuj archiwum ZIP **wewnątrz katalogu głównego** `quantitative-research-lab`, tak aby powstał plik `scripts/download_all_data.py`. Nie rozpakowuj całej paczki do dodatkowego folderu.

W terminalu w katalogu projektu uruchom:

```powershell
uv run python scripts/download_all_data.py --start-date 2021-01-01 --workers 6
```

Domyślna data końcowa: **wczoraj UTC**, czyli ostatnia pełna dzienna świeca. Można też podać `--end-date YYYY-MM-DD`.

Skrypt wykorzystuje istniejące biblioteki projektu: `pandas`, `numpy`, `requests`, `beautifulsoup4`, `pyarrow`. Nie wymaga kluczy API.

## Gdzie zapisuje dane?

- `data/raw/binance_btcusdt_1d.csv` — OHLCV 1D futures BTCUSDT.
- `data/raw/binance_funding_events.csv` oraz `binance_funding_daily.csv` — wszystkie odnalezione zdarzenia funding i agregaty 1D.
- `data/raw/binance_metrics_daily.csv`, `binance_metrics_missing.csv` — dzienne snapshoty pozycji i status braków.
- `data/raw/farside_btc_etf_flows.csv` — oficjalnie raportowane przepływy ETF (mln USD).
- `data/raw/fred_macro_observations.csv` — obserwacje makro bez sztucznego uzupełniania.
- `data/raw/macro_available_lagged_proxy.csv` — dane makro przesunięte kalendarzowo.
- `data/raw/binance_vision_cache/` — pobrane archiwa ZIP do wznowienia po przerwaniu.
- `data/processed/btc_daily_raw.csv` — złączone dane z przesunięciami dostępności.
- `data/processed/btc_daily_features.csv` i `.parquet` — cechy oraz targety dla t+1.
- `reports/data_download_report.md` i `.json` — zasięg, kompletność, luki i ostrzeżenia.

## Istotne uwagi badawcze

- Dane historyczne Binance Vision nie zawsze są dostępne za najnowsze dni; świeże OHLCV/funding są uzupełniane API Binance, gdy to możliwe. Może istnieć ograniczenie geograficzne API.
- Binance `/futures/data/openInterestHist` ma ograniczoną historię. Skrypt korzysta z archiwów dziennych `metrics` na Binance Vision.
- Binance zmieniał konwencję znakowania czasu metryk futures w 2026 r.; metryki do badań są opóźnione o **1 dzień UTC** względem daty z pliku. To rozwiązanie ostrożne, nie dokładny timestamp publikacji.
- Przepływy spot Bitcoin ETF z Farside są dostępne od 2024 r. i także opóźnione o **1 dzień UTC** w scalonym zbiorze. Nie wypełniamy dni bez odczytu ETF zerami.
- FRED pokazuje **dzisiejsze wartości historyczne**, w tym rewizje. Makro jest opóźnione o 1 dzień; `M2SL` i `FEDFUNDS` o 45 dni. To przybliżenie, **nie** poprawna baza point-in-time. Do backtestu makro potrzebne będą daty publikacji i serie ALFRED.
- Złoto pobierane jest ze Stooq (XAUUSD). Jeśli dostawca ograniczy automatyczny dostęp, kolumna `gold` zostanie `NaN` i w raporcie pojawi się ostrzeżenie. Nie zastępuj braków wymyślonymi cenami.
- `target_*` zależą od świecy następnego dnia; ostatni wiersz bez przyszłego targetu jest odrzucany.
- 3 istniejące testy projektu testują tylko podstawowe funkcje, nie kompletność pobranych źródeł. Sprawdź raport zanim rozpoczniesz E001.

## Szybkie sprawdzenie po zakończeniu

```powershell
uv run python -c "import pandas as pd; p='data/processed/btc_daily_features.parquet'; d=pd.read_parquet(p); print(d.shape); print(d.index.min(), d.index.max()); print(d[['close','funding_mean']].tail())"
```

## Źródła

- Binance Vision: https://data.binance.vision/
- Binance USD-M Futures: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api
- Farside all ETF flows: https://farside.co.uk/bitcoin-etf-flow-all-data/
- FRED graph CSV: https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS
- Stooq gold XAUUSD: https://stooq.com/q/d/l/?s=xauusd&i=d
