# E002 — BTCUSDT: prognozowanie zakresu dziennej świecy

**Stan:** protokół v1.0 (pre-CV); audyt zmiennej docelowej, bez trenowania modeli.  
**Data zamrożenia zbioru:** plik `data/processed/btc_daily_features.csv` powinien mieć SHA256 zgodny z `reports/E001_funding_rate/cv_metadata.json`.  
**Instrument:** Binance BTCUSDT USD-M futures, świece 1D, dni UTC.  
**Moment decyzji:** po zamknięciu świecy dziennej *t*; przewidywany zakres świecy *t+1*.

## 1. Pytanie, hipotezy i zakres

**Pytanie:** czy znane na koniec dnia *t* cechy rynku i funding rate pozwalają przewidzieć bezwzględną szerokość zakresu High–Low następnej świecy, znormalizowaną ceną zamknięcia z dnia *t*, lepiej niż proste prognozy na podstawie historycznych zakresów?

- **H0 (główna):** model z cechami rynkowymi nie obniża MAE względem najlepszego prostego benchmarku ustalonego wyłącznie na CV development.
- **H1 (główna):** model z cechami rynkowymi obniża MAE względem benchmarku w sposób stabilny w oknach walk-forward.
- **H0 (drugorzędna):** dodanie funding rate do identycznego modelu nie obniża MAE.
- **H1 (drugorzędna):** funding rate wnosi dodatkową informację predykcyjną, obniżając MAE.

To badanie prognozuje **zakres**, nie znak zwrotu, poziomy High/Low ani faktyczną wariancję z danych intraday. Sama prognoza zakresu nie mówi, w którą stronę rynek się poruszy.

## 2. Zmienna docelowa — definicja pierwotna

Dla świecy indeksowanej dniem UTC *t*:

\[y_t = \operatorname{target\_range}_t = \frac{H_{t+1}-L_{t+1}}{C_t}\]

- `H_{t+1}` i `L_{t+1}` — maksimum i minimum kolejnego dnia.
- `C_t` — cena zamknięcia bieżącej, już zakończonej świecy.
- Jednostka: **ułamek ceny zamknięcia**; `0.05` = 5% (nie 5 USD).
- `y_t >= 0` i wartość znana **dopiero po zamknięciu t+1**.
- Ostatni dzień OHLCV bez następnej zamkniętej świecy **nie ma targetu** i jest wyłączony z treningu.
- Obecna kolumna `target_range` w CSV powinna być identyczna z `target_high_ret - target_low_ret` i powyższą formułą. Audyt porównuje ją z osobnym plikiem świec surowych.

**Nie mylić z** `candle_range = (H_t-L_t)/O_t` w obecnym pipeline (inny mianownik). Również `log(H/L)` i true range / ATR są innymi definicjami. Nie zmieniamy targetu po zobaczeniu wyników.

### Proste benchmarki w zgodnej skali

Najpierw tworzymy dostępną na koniec dnia *t* serię:

\[r_t = \frac{H_t-L_t}{C_{t-1}}\]

- **B0 — średnia historyczna** `y` w treningu (skalkulowana wyłącznie z przeszłych, dostępnych etykiet).
- **B1 — persistence:** `\hat y_t = r_t` (bieżący już zaobserwowany zakres jako prognoza jutra).
- **B2 — 7-dniowa średnia:** `\hat y_t = mean(r_{t-6},...,r_t)`.
- Dodatkowy sygnał pomocniczy: `mean(r_{t-29},...,r_t)`; 30 dni to odrębny benchmark eksploracyjny, nie zastępuje pierwotnego B2 bez jawnego odnotowania.

`r_t` i kroczące statystyki są znane na końcu dnia *t*; **nie używają dnia t+1**. Podczas braków pierwszych 7/30 dni stosujemy predefiniowany okres rozgrzewki, bez uzupełniania z przyszłości.

## 3. Modele i cechy — przed uruchomieniem CV

- **M1:** Ridge na cechach rynkowych z E001: historyczne stopy zwrotu (1/3/7/14/30), zmienność 7/14/30, ATR14%, geometria bieżącej świecy, aktywność/volume, relacja ceny do średniej; plus zakresy `r_t` i `mean7` jako wyjaśniające, jeśli te dodatkowe cechy dodano identycznie w M1 i M2.
- **M2:** dokładnie M1 **+** 7 cech funding z E001 (`funding_mean`, `funding_std`, średnie 3/7/14/30, `funding_z_30d`).
- **M3 — RandomForestRegressor:** próba nieliniowa, **drugorzędna/eksploracyjna**. Hiperparametry wyłącznie w development; bez wykorzystania holdoutu do wyboru.
- Wszelkie przewidywane ujemne zakresy z modeli regresyjnych obcinamy do `0` **dla wszystkich modeli**, zgodnie z nieujemnym charakterem targetu. Reguła jest ustalona przed CV.
- Wykluczamy wszystkie kolumny `target_*` z wejścia modeli. Dodatkowe cechy muszą pochodzić z informacji dostępnych nie później niż zamknięcie dnia *t*.
- Stosujemy medianową imputację i standaryzację uczoną **osobno wewnątrz każdego folda** dla Ridge. Przed wdrożeniem wymagany jest audyt czasu publikacji danych zewnętrznych i funding.

## 4. Walidacja i zamrożenie eksperymentu

- Zachowujemy **ten sam podział co E001**: 1716 wierszy rozwojowych i ostatnie 429 jako *holdout*; podstawowy audyt E002 nie czyta etykiet holdoutu.
- **5 rosnących foldów walk-forward** w rozwoju (jak E001). Zbiór końcowy jest nietknięty przy audycie, wyborze cech i tuningowaniu.
- W jednym foldzie preprocessory i modele dopasowujemy wyłącznie na treningu; predykcja dla każdego dnia dotyczy *t+1*. Dla re-treningu online na koniec dnia *t* etykieta dnia *t-1* jest już znana; dla batchowej walidacji stosujemy trening sprzed początku folda.
- **Metryka główna:** MAE prognozowanego zakresu, interpretacja w punktach procentowych; **wtórna:** RMSE. Zapisujemy liczbę prognoz, wyniki każdego folda, pooled MAE, predykcje dzienne i SHA256 źródła.
- Porównania modeli: sparowane różnice bezwzględnych strat z HAC (np. 7 lagów), testy odporności na wybór liczby lagów, proporcja wygranych foldów; p-value traktujemy jako diagnostyczne przy wielu porównaniach.
- **Warunek sukcesu:** spójna redukcja MAE wobec prostych benchmarków na CV i brak wyraźnej niestabilności między foldami. Nie selekcjonujemy modelu wyłącznie po jednym p-value.
- Finalny holdout można uruchomić **tylko raz po spisaniu decyzji o modelu i przeglądzie metodologii**. Dodatkowe iteracje po obejrzeniu holdoutu wymagają nowego niezależnego okresu danych.

## 5. Pułapki, ograniczenia i decyzje

1. **`target_large_range` nie nadaje się w obecnej postaci do eksperymentu klasyfikacyjnego.** W skrypcie jego próg to `rolling(30).median()` już na `target_range[t]`, więc próg na dzień *t* uwzględnia przyszłą, przewidywaną etykietę *t*. Jeśli kiedyś potrzebny będzie label binarny, definiujemy **na koniec t** próg `median(r_{t-29},...,r_t)` i porównujemy z `y_t`; na razie pozostajemy przy regresji.
2. Target `y_t` może rosnąć przy skokach zmienności, ale to nie jest miara dziennej wariancji z intraday returns. Rozszerzenie o realized volatility wymaga nowych danych intraday, nowej definicji targetu i nowego eksperymentu.
3. Świeca końcowa w 2026-11-16 jest znana przy tworzeniu etykiety dla wiersza 2026-11-15; w walidacji development nie analizujemy rozkładu targetu holdout.
4. Cechy ETF i futures positioning mają opóźnienia przybliżone; przed modelami wymagamy dodatkowego audytu point-in-time. Zmiennych ETF/makro nie używamy w pierwszej prerejestrowanej próbie E002.
5. Inne testy targetu (np. `log(H/L)` lub targety High/Low osobno) to **oddzielne eksperymenty**, nie korekta E002 po zobaczeniu wyników.

## 6. Kryterium zakończenia fazy konstrukcji targetu

- [ ] Zgodność `target_range` z raw OHLC z tolerancją numeryczną.
- [ ] Brak ujemnych, `NaN` i niefinitywnych etykiet w development.
- [ ] Potwierdzenie, że target z `t+1` i cechy z `<= t` są prawidłowo wyrównane po UTC.
- [ ] Bazowe cechy `r_t`, średnia7 i średnia30 stworzone **wyłącznie z danych dostępnych do t**.
- [ ] Raport `reports/E002_range/target_audit.json` i `data/processed/e002_development_target.csv` zapisane.
- [ ] E001 i końcowe 429 etykiet nienaruszone; nie uruchomiono E002 CV ani finalnego testu.

## Uruchomienie audytu

```powershell
uv run python scripts/run_e002_target_audit.py
uv run python -m pytest tests/test_e002_target.py -v
```
