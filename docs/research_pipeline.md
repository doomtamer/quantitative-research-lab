# Automated Research Pipeline

Pierwszy etap obsługuje szkic, walidację, wniosek o zatwierdzenie i dry-run.
Uruchamiaj polecenia z katalogu głównego repozytorium na osobnej gałęzi
danego eksperymentu. Identyfikatory mają format `E004_nazwa` do
`E999_nazwa`. Zaplanuj oddzielne okresy development i nowego holdoutu.
Na tym etapie żadne polecenie nie trenuje modeli ani nie otwiera pliku
z danymi badawczymi.

```powershell
uv run python -m quantlab.research.pipeline scaffold E004_example
# Uzupełnij experiments/E004_example/protocol.json.
uv run python -m quantlab.research.pipeline validate E004_example
uv run python -m quantlab.research.pipeline dry-run E004_example
```

`scaffold` tworzy katalog i szkic bez nadpisywania. `validate` sprawdza
wymagane pola, daty UTC, odstęp na granicy development–holdout co najmniej
równy horyzontowi etykiety, wykluczenie cech `target_*` i deklaracje wejść.
Każde wejście development wymaga ścieżki CSV lub Parquet bezpośrednio
w `data/research/<eksperyment>/development/`, opisu pochodzenia i
deklarowanej sumy SHA-256. Można zaplanować brakujący jeszcze plik.
`dry-run` pokazuje stan zatwierdzenia, parametry walidacji, wejścia i ścieżki
artefaktów. Można podać `--run-id` z 32 małymi znakami szesnastkowymi.
Planowanie odrzuca zajęty katalog, a sam plan katalogu nie rezerwuje.

## Podpis a autoryzacja

1. Po przeczytaniu pełnego protokołu i sprawdzeniu pochodzenia danych
   kierownik samodzielnie porównuje wersję i SHA-256 pliku z wnioskiem.
   Następnie sam podpisuje wniosek na swoim stanowisku. W przykładzie
   `$reviewerKey` wskazuje klucz prywatny pod wyłączną kontrolą kierownika.
   CLI tworzy wyłącznie wniosek.

   ```powershell
   $approvalRequest = Join-Path $env:TEMP 'quantlab-E004-example-v1.json'
   uv run python -m quantlab.research.pipeline approval-request E004_example --output $approvalRequest
   Get-FileHash -Algorithm SHA256 experiments/E004_example/protocol.json
   Get-Content $approvalRequest
   ssh-keygen -Y sign -f $reviewerKey -n quantlab-research-approval-v1 $approvalRequest
   Copy-Item -LiteralPath "$approvalRequest.sig" -Destination experiments/E004_example/approval.sig
   ```

2. Dry-run pokazuje dwa osobne wyniki. `signature: valid` oznacza, że
   lokalny OpenSSH potwierdził podpis dla klucza zawartego w podpisie,
   identyfikatora eksperymentu, wersji, SHA-256 aktualnych bajtów i domeny
   `quantlab-research-approval-v1`. `missing` oznacza brak podpisu,
   `not_validated` nieudaną kontrolę, a `unavailable` brak możliwości
   uruchomienia kontroli lub przekroczenie czasu. Zmiana choćby formatowania
   zmienia SHA-256 i dotychczasowy podpis przestaje pasować.
3. `authorization.status: unverified` z powodem
   `independent_verifier_not_configured` oraz `execution_allowed: false`
   obowiązują dla każdego planu, również przy poprawnym podpisie. Kod wyjścia
   `0` oznacza wygenerowanie planu. CLI nie ustanawia zaufania na podstawie
   katalogu domowego, środowiska procesu, argumentu CLI ani lokalnego pliku.
   Wynik lokalnej kontroli zależy od integralności lokalnego narzędzia
   OpenSSH. Ma charakter diagnostyczny. Podpisy z testów syntetycznych nie są
   dowodem zatwierdzenia. Podpisy lokalne, dane i wyniki przebiegów są ignorowane
   przez Git. [Sprawdzanie podpisów w OpenSSH](https://man.openbsd.org/ssh-keygen.1).

## Docelowa autoryzacja w GitHub Actions

Wybrany mechanizm to osobny workflow autoryzacji z chronionym środowiskiem
GitHub Actions. Obecna wersja nie konfiguruje tego workflow ani wykonawcy.
Lokalny CLI pozostaje w trybie fail-closed.

1. **Zaufany kod i polityka.** Właściciel utrzymuje workflow na chronionej
   referencji oraz kontroluje konfigurację środowiska, zaufany klucz
   publiczny kierownika i zasady unieważniania kluczy. Agent i gałąź
   eksperymentu nie mogą zmieniać tych elementów. Workflow pobiera zgłoszenie
   z konkretnego commita i odczytuje je jako dane. Nie uruchamia kodu,
   akcji ani skryptów z gałęzi eksperymentu.
2. **Osobna zgoda kierownika.** Środowisko wymaga przeglądu przez
   wyznaczonego kierownika badań z konta niedostępnego dla agenta.
   Konfiguracja musi blokować samozatwierdzanie i omijanie reguł.
   Kierownik zatwierdza konkretny identyfikator eksperymentu, wersję
   i SHA-256 protokołu. Zwykłe zielone CI, przegląd PR i lokalny status
   `signature: valid` nie nadają autoryzacji.
3. **Weryfikacja podpisu i decyzja.** Workflow sam liczy SHA-256 dokładnych
   bajtów protokołu i odtwarza wniosek z identyfikatorem oraz wersją.
   Sprawdza podpis w domenie `quantlab-research-approval-v1` za pomocą
   zaufanego klucza kierownika. Po uzyskaniu wymaganej zgody wystawia
   uwierzytelnioną decyzję związaną z repozytorium, commitem zgłoszenia,
   domeną, identyfikatorem, wersją, SHA-256 i zakresem development.
4. **Odmowa wykonania.** Przyszły wykonawca musi uwierzytelnić decyzję
   wybranego workflow niezależnie od danych z checkoutu i ponownie
   sprawdzić zgodność identyfikatora, wersji i SHA-256. Brak decyzji,
   nieznany wystawca, odwołanie zgody, błąd weryfikacji lub zmiana
   protokołu blokują wykonanie. PR ani zatwierdzenie w GitHub Actions
   nie uruchamiają automatycznie treningu, historycznych badań E001–E003
   ani holdoutu E002.

Przed wdrożeniem właściciel musi skonfigurować wymaganych recenzentów,
ograniczyć dozwolone referencje i potwierdzić dostępność tych zabezpieczeń.
Brak wymaganych reguł blokuje włączenie autoryzacji. Do ustalenia pozostają
kanał przekazywania podpisu i sposób uwierzytelnienia decyzji. Lokalne dane,
podpisy i klucze prywatne nie trafiają do Git ani do logów CI.
[Chronione środowiska i wymagani recenzenci w GitHub Actions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

## Kontrakt przyszłego wykonawcy

1. Tuż przed wykonaniem ponownie waliduj protokół i wymagaj aktualnej
   decyzji niezależnego weryfikatora związanej z jego dokładnymi bajtami.
   Przypnij tę wersję, utrwal tożsamość wykonującego kodu oraz wersje Pythona
   i zależności. Rejestracja nowego źródła wymaga
   niezależnego potwierdzenia przez kierownika, że zawiera wyłącznie dane
   development, bez historycznego holdoutu.
2. Zweryfikuj rzeczywiste SHA-256 wejść względem zatwierdzonych deklaracji
   i korzystaj dalej z tych samych zweryfikowanych bajtów. Przed
   dopasowaniem sprawdź daty, dostępność etykiet i cech oraz granice foldów.
3. Zarezerwuj katalog `reports/research_pipeline/<eksperyment>/<run-id>/`
   atomowym utworzeniem końcowego katalogu z `exist_ok=False`. Pierwszy
   `manifest.json` zapisuj z wyłącznym utworzeniem. Zawiera wersję i hash
   protokołu, dane dowodu zatwierdzenia, wersję kodu i środowiska, sumy
   i pochodzenie wejść, seed, konfigurację i granice foldów, status
   przebiegu, znaczniki czasu i ścieżki artefaktów. Oznacz zakończenie
   manifestu atomową aktualizacją wewnątrz tego samego przebiegu.
   Nieudany przebieg zachowaj ze statusem błędu. Kolejna próba ma nowy ID.
4. Ucz transformacje i modele wewnątrz foldów, tylko na treningu. Zapisz
   `report.md` z benchmarkami, metrykami per fold i łącznie, liczebnościami,
   stabilnością oraz ograniczeniami. Raport podlega niezależnemu audytowi
   i decyzji człowieka. Etap rozwojowy nie wykonuje żadnego holdoutu.

## Granice obecnej wersji

Dry-run sprawdza metadane ścieżek i deklaracje sum. Odrzuca historyczne
ścieżki, dowiązania i znane sumy zamrożonych wejść E002. Nie wykryje
skopiowanych i przemianowanych danych z błędną deklaracją pochodzenia
lub sumy. Sprawdzenie rzeczywistych bajtów, kontrola pochodzenia, odporność
na podmianę pliku podczas wykonania, rezerwacja katalogu i zapis manifestu
to zadania opisane w kontrakcie przyszłego wykonawcy. Plik treningowy i
zarezerwowany okres holdoutu pozostają rozdzielone. Otwarcie nowego
holdoutu wymaga odrębnej decyzji, a holdout E002 pozostaje zamknięty.
