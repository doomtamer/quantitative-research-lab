# Zasady pracy agentów w Quantitative Research Lab — BTCUSDT

## Zatwierdzanie eksperymentów

- Dla każdego nowego eksperymentu przygotuj osobny protokół zgodny z
  `docs/experiment_protocol.md`. Przed jakimkolwiek treningiem, także próbnym,
  uzyskaj jawne zatwierdzenie konkretnej wersji protokołu przez kierownika badań.
- Każdy nowy eksperyment realizuj na osobnej gałęzi Git i zapisuj jego wyniki
  w odrębnym katalogu.
- Zapisz pytanie, H0/H1, instrument, źródła, moment prognozy, target i jego
  horyzont, listę cech, benchmarki, modele, zakres strojenia, podział danych,
  metrykę główną, metryki dodatkowe oraz kryteria sukcesu.
- Zmiany metodologii wymagają nowej wersji protokołu i ponownego zatwierdzenia
  przed następnym treningiem. Oddaj wyniki do niezależnego audytu i zatwierdzenia
  przez człowieka.

## Walidacja chronologiczna i data leakage

- Ustal granice development i holdoutu przed treningiem. W development stosuj
  chronologiczną walidację walk-forward bez losowego mieszania obserwacji.
- W każdym foldzie dopasowuj imputację, skalowanie, selekcję cech i model
  wyłącznie na treningu. Porównuj modele i benchmarki na tych samych datach.
- Dobierz odstęp na granicach zbiorów do horyzontu i czasu dostępności etykiet.
  Sprawdź, że wszystkie etykiety treningowe były dostępne przed rozpoczęciem
  walidacji lub holdoutu.
- Dla każdej cechy sprawdź dostępność w momencie prognozy. Rozróżniaj czas
  zdarzenia i czas publikacji. Zapisuj niezweryfikowane założenia o opóźnieniach.
  Wyklucz `target_*` z wejść modelu oraz sprawdź przesunięcia, złączenia czasowe
  i okna kroczące pod kątem użycia przyszłych danych.
- Cechy, modele, hiperparametry i metryki wybieraj w development. Dane holdoutu
  otwieraj wyłącznie po zamrożeniu specyfikacji i po osobnej zgodzie człowieka.
  Do niezależnego potwierdzenia wyników użyj nowego okresu danych.

## Zamknięcie E002 i ochrona historii

- Nigdy nie uruchamiaj ponownie jednorazowej ewaluacji holdoutu E002. Zakaz
  obejmuje `scripts/evaluate_e002_holdout_once.py`, bezpośrednie wywołanie
  `evaluate()` oraz odtworzenie tej samej ewaluacji innym sposobem.
  Obowiązuje także w CI, w kopiach roboczych i po przerwaniu wykonania.
- Nie wykorzystuj końcowego holdoutu E002 do ponownej ewaluacji, strojenia ani
  wyboru modeli. Zakaz strojenia i wyboru modeli obejmuje również opublikowane
  wyniki tego holdoutu.
- Zachowaj `ATTEMPT_STARTED.json` i `E002_FROZEN_MANIFEST.json`. Korzystaj
  z opublikowanego podsumowania E002 w trybie odczytu.
- Nie zmieniaj historycznych wyników, manifestów ani zamrożonych protokołów.
  Nie nadpisuj surowych danych. Przed uruchomieniem skryptu sprawdź ścieżki
  zapisu. Zatwierdzone nowe przebiegi zapisuj w osobnym katalogu, a uwagi
  do wcześniejszych badań dokumentuj osobno.

## Reprodukowalność i publikacja

- Używaj Python 3.12 i środowiska z `uv.lock` (`uv sync --locked`).
  Zapisuj wersję kodu i protokołu, komendę, wersje zależności, konfigurację
  modelu, ziarna losowe, granice foldów oraz pochodzenie i SHA-256 wejść.
- Raportuj główną metrykę, wyniki per fold, wyniki łączne, liczebności
  i ograniczenia. Nowy snapshot danych dokumentuj pod osobnym identyfikatorem.
  Wnioski o jakości prognoz oddzielaj od wniosków o rentowności.
- Do rutynowej weryfikacji kodu używaj `uv run python -m pytest -q`.
  Testy i CI korzystają z danych syntetycznych i nie uruchamiają badań
  na historycznych danych.
- Po zakończeniu każdego zadania przedstaw raport obejmujący zmiany,
  przeprowadzone testy i ich wyniki, ograniczenia oraz decyzje wymagające
  zatwierdzenia.

## Uprawnienia

- Nie składaj, nie zmieniaj ani nie anuluj zleceń giełdowych. Nie wykonuj
  transakcji ani nie uruchamiaj automatycznego handlu.
- Nie wykonuj `git commit` ani `git push` bez jawnej zgody użytkownika
  na daną operację.
- Nie udostępniaj lokalnych danych, plików predykcji ani sekretów. Nie przenoś
  ich do Git, logów, artefaktów CI ani usług zewnętrznych. W raportach używaj
  zatwierdzonych agregatów i metadanych.
