# E005 — BTCUSDT perpetual trend backtest

**Protokół v1.1 — do zatwierdzenia przed użyciem danych historycznych.**
Termin portfolio to 6 grudnia 2026. Status i zakres prezentacji zależą
od weryfikacji danych. Etap przygotowawczy obejmuje kod i testy syntetyczne.

## Hipoteza i reguła

Pytanie badawcze dotyczy tego, czy prosta strategia long/flat poprawia
netto relację zwrotu do ryzyka względem stałej ekspozycji na Binance
USD-M BTCUSDT perpetual.

- **H0.** Strategia nie poprawia Sharpe netto względem Buy & Hold lub
  nie ma dodatniej łącznej stopy zwrotu względem cash.
- **H1.** Sharpe netto jest wyższy niż dla Buy & Hold, a łączny zwrot
  netto jest wyższy niż dla cash. Porównanie dotyczy jednego
  zamrożonego okresu w scenariuszu bazowym i ma charakter opisowy.

Long, gdy `close_t > SMA200_t` oraz `close_t / close_{t−20} − 1 > 0`.
SMA obejmuje 200 kolejnych kompletnych świec UTC, łącznie z dniem `t`.
Równość z progiem daje flat. Sygnalizacja następuje po zakończeniu sesji.
Brak wymaganej ceny, luki w kalendarzu lub nieudokumentowana dostępność
w zatwierdzonym wariancie zatrzymują przebieg. Strategia nie dopasowuje
modelu, nie optymalizuje reguł i nie korzysta z funding jako cechy.

## Okresy chronologiczne i granice danych

Daty poniżej zamrożono do przeglądu przed uruchomieniem historycznym,
bez przeglądania rentowności. Każdy okres zaczyna z 10 000 USDT
symulowanego kapitału i zerową pozycją. Oznaczenia godziny obejmują oba
końce siatki wyceny.

| Etap | Pierwszy punkt UTC | Ostatni punkt UTC | Cel |
| --- | --- | --- | --- |
| Development | 2020-07-01 01:00 | 2022-12-31 23:00 | Weryfikacja danych, księgowania i założeń kosztowych. |
| Walidacja | 2023-01-01 01:00 | 2023-12-31 23:00 | Odrębny przegląd stabilności przy tych samych regułach. |
| Jednorazowy test końcowy E005 | 2024-01-01 01:00 | 2025-09-12 23:00 | Jedna ocena po zamrożeniu kodu, źródeł i kosztów oraz osobnej zgodzie. |

Rozgrzewka dziennych cech dla pierwszego okresu zaczyna się
2019-12-14 UTC. Kolejne okresy mogą korzystać wyłącznie z wcześniejszych
zamknięć do rozgrzewki. Pozycje i kapitał między etapami się nie
przenoszą. Pozycję na końcu etapu wyceniamy po ostatniej dopuszczonej
cenie; pozostaje otwarta w księdze i nie zaliczamy fikcyjnej transakcji
zamykającej. Nie ma etykiety przyszłej wymagającej purge. Test końcowy
dotyczy E005 i nie stanowi gwarancji niezależności od całej wcześniejszej
historii badań labu.

Źródła mogą zawierać wyłącznie obserwacje przed
`2025-09-13T00:00:00Z`. Tę granicę należy wymusić w zapytaniu i w
walidacji każdej odpowiedzi. Sygnały, ceny i zlecenia symulowane od
`2025-09-13T00:00:00Z` włącznie są odrzucane. Świece ze znacznikiem końca w części
chronionej, odczyt plików E002 i odtwarzanie jego okna są wyłączone.
Istniejący audytowany snapshot E004 można po zatwierdzeniu użyć jako
źródło 1D w tym zakresie w trybie odczytu, po sprawdzeniu SHA-256.
E005 rejestruje własny snapshot i manifest, niezależnie od źródła 1D.
Żaden plik E004 nie jest plikiem wyjściowym E005.

Snapshot development i walidacji ma osobny lokalny katalog
`data/research/E005_trend_backtest/development/<snapshot-id>/`
z `snapshot_manifest.json`. Zestaw końcowy i jego manifest pozostają
w oddzielnej lokalizacji objętej kontrolą dostępu kierownika. Zatwierdzone
wyniki trafiają do nowego katalogu
`reports/research_pipeline/E005_trend_backtest/<run-id>/`.
Katalogi wejściowe i wynikowe są ignorowane przez Git.

## Egzekucja, kapitał i funding

- Zlecenie symulowane wyłącznie przy następnym otwarciu 01:00 UTC,
  z wykorzystaniem `open` świecy transakcyjnej 1h opisanej jako
  `traded_open_proxy`. To cena transakcyjna, nie cena mid. Dane z tej świecy
  poza `open` nie wchodzą do decyzji ani ceny zlecenia. Świeca 1h nie
  dowodzi ceny wykonalnej, kolejki, płynności czy chwili pierwszej
  transakcji. Zamknięcie 1D nie dowodzi dostępności pliku przed 01:00.
  Bez niezależnego dowodu dostępności stosujemy jawny wariant
  retrospektywny z założeniem dostępności przed 01:00. Opóźniona rzeczywista
  publikacja nie jest automatycznie zrównywana z tym założeniem.
- Po wejściu kupujemy stałą ilość o budżecie 90% wolnego kapitału wraz
  z kosztami. Pozostałe 10% stanowi bufor. Pozycja pozostaje bez zmian
  do przejścia na flat. Ekspozycja brutto ma limit 1x. Brak shortów,
  dodatkowej dźwigni, dopłat i fikcyjnego rebalansowania. Jeżeli debit
  funding wyczerpie rezerwę, scenariusz jest przerwany z powodu
  niemożności utrzymania limitu. Model nie symuluje likwidacji.
- Ledger równoważny P&L kontraktu linearnego używa salda resztowego i
  wyceny ilości BTC. Preferowane są potwierdzone ceny mark point-in-time.
  Bez nich open transakcyjny jest oznaczony jako proxy wyceny.
- Dla zweryfikowanego rozliczenia quote cash flow pozycji long wynosi
  `−quantity × markPrice × fundingRate`. Uwzględniamy wszystkie
  rzeczywiste czasy rozliczeń, znaki i przypisane mark prices. Finansowanie
  pomiędzy punktami godzinowymi przypada na pozycję utrzymywaną wtedy.
  Rozliczenie dokładnie w czasie symulowanego wejścia/wyjścia należy
  do pozycji sprzed transakcji. Takie kolizje wymagają osobnego przeglądu
  przed uznaniem wyniku za reprezentatywny. Kompletność wymaga niezależnie
  uzgodnionego kalendarza funding, a nie tylko braku duplikatów w jednym
  pliku. [Historia funding Binance](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-history).
- Prowizja jest naliczana raz od przesuniętej ceny wykonania. Niekorzystne
  przesunięcie to różnica między ceną wykonania a `traded_open_proxy`.
  Zmienia cenę w księdze i jest raportowane informacyjnie, bez drugiego
  obciążenia salda. Osobny półspread nie jest naliczany. Poniższe wartości
  to założenia, bez założenia obserwowalności rzeczywistych kosztów.

| Scenariusz | Prowizja na stronę | Niekorzystne przesunięcie ceny | Nominalny koszt na stronę |
| --- | ---: | ---: | ---: |
| Bazowy | 5 bps | 3 bps | 8 bps |
| Niski | 5 bps | 0 bps | 5 bps |
| Stresowy | 5 bps | 11 bps | 16 bps |

Koszt nominalny to suma założeń. Koszt w USDT wynika z przesunięcia
ceny i prowizji od nominału po przesunięciu. Raport obejmuje każdy
scenariusz. Stawki i harmonogram funding są wspólne, a kwoty zależą
od symulowanej wielkości pozycji.

Raport rozdziela oznaczony `funding_excluded` i wariant ze zweryfikowanymi
rozliczeniami. Przy niepełnym funding wykonanie może ograniczyć się
do jawnej diagnostyki price-only z kosztami. Bez wiarygodnej
egzekucji obydwa warianty pozostają symulacją z proxy świecy 1h.
Określenie „pełny backtest futures” wymaga zweryfikowanego funding,
wyceny i audytu dostępności oraz wykonalności wejść i wyjść. Brak
potwierdzenia jest ograniczeniem komunikowanym także w portfolio.

## Benchmarki i raport

Buy & Hold kupuje przy pierwszym 01:00 i utrzymuje pozycję do ostatniej
wyceny, z takim samym budżetem 90%, kosztami, funding i limitem.
Cash ma zerową pozycję, koszty i odsetki. Wszystkie porównania używają
tej samej godzinowej siatki. Wyniki obejmują wykres i CSV krzywej
kapitału, transakcje, CAGR według czasu kalendarzowego, Sharpe i
Sortino z dziennych wycen przy zerowej stopie odniesienia i skali
365, max drawdown z wycen godzinowych, obrót brutto zdefiniowany jako
suma nominałów obu stron podzielona przez średnią wartość kapitału,
liczbę filli i zamkniętych cykli, czas w rynku, średnią i maksymalną
ekspozycję oraz stopy zwrotu per rok, w tym niepełne lata.
Wskaźniki bez zmienności lub bez odpowiednich obserwacji pozostają
niewyznaczone. Wyniki netto pokazujemy w każdym z trzech
z góry ustalonych scenariuszy. Dla portfela raportujemy również warunki, liczby transakcji
i wyraźny status funding i egzekucji. Brak korzystnego wyniku
nie upoważnia do ponownego wyboru parametrów na końcowym teście.

## Autoryzacja i harmonogram

1. Kierownik zatwierdza konkretny hash tej wersji, okresy, bufor 10%,
   kryterium wyniku i kosztowe założenia. Niezależny weryfikator musi
   potwierdzić decyzję zgodnie z repozytorium. Obecny pipeline pozostaje
   fail-closed. Plik lokalny ani pozytywny test CI nie zastępują decyzji.
   Proponowany wykonawca działa na koncie kierownika lub w chronionej
   infrastrukturze poza worktree agenta. Musi poświadczyć zgodność hashy
   i zakresu ze zweryfikowaną decyzją oraz utrwalić komendę i identyfikator
   autoryzacji w dzienniku przebiegu. Do uzgodnienia pozostaje sposób
   przekazania tej decyzji przez docelowy chroniony workflow.
2. Po autoryzacji zarejestrować audytowany manifest E005 z hashami
   1D, 1h, funding i mark, jeśli używane. Osoba kontrolująca dostęp
   dostarcza programowi wyłącznie zakres dozwolony do danego etapu.
   Osobno zatwierdzić dopuszczalny poziom twierdzeń o egzekucji.
3. Przeprowadzić development i walidację bez dostępu do końcowego
   zestawu E005. Zamrozić hash kodu, protokołu, wejść i kosztów.
   W zaufanym wykonawcy przed pierwszym odczytem końcowym utworzyć
   wyłączny znacznik rozpoczęcia z identyfikatorem niezależnej decyzji.
   Ocenę wykonać raz po odrębnym zatwierdzeniu i zapisać w nowym,
   nieistniejącym katalogu. Zgłosić awarię lub brak możliwości wykonania.
4. Cel harmonogramu to decyzja i weryfikacja źródeł do 24 listopada,
   development oraz walidacja do 29 listopada, niezależny przegląd
   testu końcowego do 3 grudnia i raport do 6 grudnia. Jeśli źródła
   lub autoryzacja nie będą gotowe, do portfolio można przedstawić
   zatwierdzony zakres diagnostyczny i jawnie udokumentowane braki.

Na obecnym etapie niedostępne są zweryfikowane wejścia E005, ich hasze,
dowód historycznej dostępności 1D przed 01:00 i ceny wykonalnej,
kompletny kalendarz funding i mark, niezależna autoryzacja oraz
wyniki historyczne. [Szablon manifestu](snapshot_manifest.template.json).
