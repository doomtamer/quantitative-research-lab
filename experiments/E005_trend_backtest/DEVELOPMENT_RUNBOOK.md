# E005 — przygotowanie development i walidacji

Ten etap obejmuje snapshot i testy syntetyczne. Protokół v1.1 obowiązuje
w dokładnie tych bajtach, które mają SHA-256
`816fee84d30a33500b69361fffa754f9b557626ef474ff2b465366c255a5a827`.
Zmiana pliku, w tym kodowania lub końców linii, unieważnia kontrolę.

## Dane i granice

Snapshot zajmuje nowy katalog
`data/research/E005_trend_backtest/development/<snapshot-id>/`.
Zawiera osobne pliki 1D, 1h development i 1h walidacji. Dzienny
zakres zaczyna się 2019-12-14 i kończy 2023-12-30 włącznie. To ostatnia
świeca dzienna potrzebna do sygnału z 31 grudnia. Godziny są ograniczone
do okresów z protokołu od 01:00 pierwszego dnia do 23:00 ostatniego.
Pominięte godziny 00:00 na początku każdego etapu są elementem planu.
Każde żądanie i odpowiedź mieści się przed 2024-01-01 UTC.
Skrypt zapisuje czasy zapytań UTC, parametry stron, hasze odpowiedzi,
hasze CSV i braki. Niepoprawna świeca lub duplikat zatrzymują zapis.
Luki otrzymują osobny status i blokują wykonanie. Dane oraz manifest
pozostają lokalnie.

## Ograniczona interpretacja

Binance dokumentuje `fundingTime`, `fundingRate` i powiązany
`markPrice` w historii rozliczeń oraz osobny endpoint świec mark.
`fundingInfo` dokumentuje korekty parametrów, lecz nie potwierdza
niezależnie historycznego harmonogramu BTCUSDT dla całego okresu.
W tym snapshocie funding i mark nie są pobierane ani rozliczane.
Scenariusz nosi etykiety `funding_excluded` i `traded_open_proxy`.
Nie jest pełnym zweryfikowanym backtestem perpetual futures.
[Dane Binance USD-M](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

Rejestrowana później cena `open` nie gwarantuje wykonania o 01:00.
Archiwum 1D nie dowodzi godziny publikacji. W zatwierdzonym wariancie
retrospektywnym przyszły runner jawnie modeluje dostępność o
00:59:59 UTC następnego dnia i oznacza każdy taki rekord
jako `simulation_assumption`. `historical_verified` jest odrębnym
typem dowodu i nie jest nadawany temu snapshotowi. Dziennik
przebiegu utrwala rodzaj założenia.
To założenie do odrębnego zatwierdzenia. Brak dowodu dostępności
historycznej ogranicza twierdzenia o jakości wyniku.

## Pakiet do niezależnego przeglądu

Do autoryzacji użyj bieżącego zamrożonego pakietu w katalogu
`build/e005-frozen/17c1fab191c4aedb45c09a5be184288c0d82b82029cf4712164027a9201a42e7/`.
Poprzednie manifesty kodu i wnioski nie obejmują tej wersji. Wymagana jest nowa decyzja.
W nim `code_manifest.json` wiąże bajty runnera, weryfikatora, loadera,
silnika, raportowania, pipeline, dwóch plików inicjalizacyjnych, protokołu,
szablonu workflow, `pyproject.toml` i `uv.lock`. Sprawdź także niniejszą instrukcję,
oficjalny GitHub CLI i zaufane środowisko Python 3.12 używane do wykonania.

SHA-256 `approval_request.json` to
`6423c11718109c0d0a62bb37fd130e14a1d1c4cec081847f6e7e5913a0d0a269`.
Wniosek wskazuje protokół v1.1, snapshot
`6325fd41c48040c6bdf17db2c5683bdb`, SHA-256 jego manifestu
`6b2b486e90cd58b2e5a342bcafe801332aa21fa3e92de67b76b7812ca0226866`,
manifest kodu i dokładne godziny otwarcia ostatnich świec w każdym zakresie.
Development obejmuje 2020-07-01 01:00 do 2022-12-31 23:00 UTC,
walidacja 2023-01-01 01:00 do 2023-12-31 23:00 UTC.
Parametry to long/flat SMA200 + momentum20, 10 000 USDT na start,
90% alokacji i 5/8/16 bps na stronę.

## Checkout na Windows

Manifest kodu wiąże surowe bajty zgodne z blobami Git, w tym końce linii.
Po publikacji operator może odtworzyć je w nowej kopii poza zasięgiem
zapisu agenta. W PowerShell przypina zatwierdzony pełny SHA commita
i wyłącza konwersję przed pierwszym checkoutem.

```powershell
$reviewedCommit = Read-Host 'Reviewed full Git commit SHA'
if ($reviewedCommit -cnotmatch '^[a-f0-9]{40}$') { throw 'Expected a full Git SHA' }
git clone --no-checkout https://github.com/doomtamer/quantitative-research-lab.git e005-review-checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone failed' }
git -C e005-review-checkout config --local core.autocrlf false
if ($LASTEXITCODE -ne 0) { throw 'Git configuration failed' }
git -C e005-review-checkout config --local core.eol lf
if ($LASTEXITCODE -ne 0) { throw 'Git configuration failed' }
git -C e005-review-checkout checkout --detach $reviewedCommit
if ($LASTEXITCODE -ne 0) { throw 'Checkout failed' }
```

Operator porównuje wszystkie 12 SHA-256 z zatwierdzonym manifestem przed
skopiowaniem plików do katalogu wykonawczego z kroku 4. Manifest i wniosek
bierze z zatwierdzonego pakietu. Przy rozbieżności przerywa operację.
Weryfikator oblicza SHA-256 bez normalizacji końców linii.

## Wdrożenie i kontrola decyzji

1. **Administrator GitHub** po odrębnej zgodzie na publikację umieszcza
   [dokładny szablon](e005-approval.workflow.template.yml) jako
   `.github/workflows/e005-approval.yml` na chronionym `main`.
   Tworzy środowisko `e005-research-approval` dla `main`, wyznacza kierownika
   badań jako jedynego wymaganego recenzenta, włącza **Prevent self-review**
   i wyłącza omijanie reguł przez administratorów. Konto recenzenta,
   reguły repozytorium i prawo do edycji workflow muszą pozostać poza
   kontrolą agenta. Zweryfikuj dostępność wymaganych recenzentów w planie
   repozytorium.
   [Konfiguracja środowisk GitHub](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
2. **Administrator Windows** po audycie ustawia dwa wpisy typu `REG_SZ`
   w 64-bitowym `HKLM\SOFTWARE\QuantLab\E005`: `ReviewerId` to numeryczny
   identyfikator konta kierownika odczytany z API GitHub, a `WorkflowCommit`
   to 40-znakowy SHA commita z przejrzanym workflow na `main` w chwili
   dispatchu. Jeśli `main` przesunie się przed dispatch, administrator
   ponownie sprawdza workflow w aktualnym commicie przed zmianą wpisu.
   Użytkownik agenta nie może mieć praw administratora ani zapisu do tego
   klucza, binariów wykonawczych, konfiguracji GitHub CLI lub profilu operatora.
   Zmienne środowiskowe i ścieżki CLI nie wybierają polityki.
   Przed wdrożeniem administratorzy potwierdzają rozdział uprawnień.
   Operator Windows nie ma dostępu do konta, sesji ani tokenów recenzenta
   GitHub i nie może zmienić recenzenta ani reguł GitHub. Recenzent
   GitHub nie ma praw zapisu do kopii wykonawczej, profilu operatora
   ani polityki HKLM. Brak potwierdzenia blokuje uruchomienie.
3. **Operator GitHub** z osobnego konta uruchamia workflow z `main`, wybierając
   `request_sha256` równy skrótowi wniosku powyżej. **Kierownik badań**
   porównuje przejrzany wniosek z wejściem zadania i zatwierdza wdrożenie
   z dokładnym komentarzem
   `E005 approve sha256:6423c11718109c0d0a62bb37fd130e14a1d1c4cec081847f6e7e5913a0d0a269`.
   Operator zapisuje numeryczne ID przebiegu z URL. Przy nieudanym przebiegu
   potrzebny jest nowy dispatch i nowa decyzja. Workflow po przejściu
   bramki środowiska podpisuje domenę decyzji, ID przebiegu i hash wniosku.
   Nie przesyła danych ani całego wniosku.
4. **Operator Windows** tworzy czysty katalog z osobnego konta, poza zasięgiem
   zapisu agenta. Weryfikuje SHA-256 manifestu kodu i wszystkich wpisanych
   plików **przed uruchomieniem Pythona**. Kopiuje wyłącznie te pliki,
   `code_manifest.json`, `approval_request.json` i wskazany snapshot
   pod tą samą ścieżką względną. Konto wykonujące nie może mieć odczytu
   danych testu końcowego E005 ani E002. Używa zaufanych instalacji Python,
   uv i aktualnej, załatanej wersji oficjalnego GitHub CLI (co najmniej
   2.102.0) z `C:/Program Files/GitHub CLI/gh.exe`. Operator
   przed autoryzacją sprawdza wersję przez `gh --version` dla tej binarki.
   GitHub CLI musi być zalogowanego w niezależnym profilu Windows do GitHub.com z dostępem do
   odczytu Actions i poświadczeń. Nie używa środowiska Pythona z worktree agenta.
5. **Operator Windows** z katalogu zweryfikowanej kopii wykonuje poniższe
   polecenia. Najpierw używa `authorize`, aby sprawdzić całą ścieżkę
   autoryzacji bez otwierania snapshotu. Gdy zwróci decyzję `approved`,
   może wykonać komendę `run` z tymi samymi argumentami. Runner wymaga
   ukończonego, udanego pierwszego przebiegu z przypiętego commita `main`,
   dokładnie jednej decyzji dla wymaganego środowiska od przypiętego recenzenta
   oraz różnych identyfikatorów recenzenta i inicjatorów przebiegu.
   GitHub CLI sprawdza kryptograficznie poświadczenie dla tego przebiegu
   i wniosku oraz tożsamość podpisującego workflow. Działanie zależy od
   niezależności kont ludzkich, ustawień repozytorium i systemu Windows.
   [Historia decyzji GitHub](https://docs.github.com/en/rest/actions/workflow-runs#get-the-review-history-for-a-workflow-run),
   [weryfikacja GitHub CLI](https://cli.github.com/manual/gh_attestation_verify).

```powershell
$approvalRunId = Read-Host 'Approved GitHub Actions run ID'
$e005Args = @(
    '6325fd41c48040c6bdf17db2c5683bdb',
    '6b2b486e90cd58b2e5a342bcafe801332aa21fa3e92de67b76b7812ca0226866',
    '--code-sha256', '17c1fab191c4aedb45c09a5be184288c0d82b82029cf4712164027a9201a42e7',
    '--approval-run-id', $approvalRunId
)
uv run --locked --link-mode copy python -E -s -B -m scripts.run_e005_development authorize @e005Args
```

Po potwierdzeniu decyzji:

```powershell
uv run --locked --link-mode copy python -E -s -B -m scripts.run_e005_development run @e005Args
```

Przed odczytem snapshotu runner ponownie sprawdza kod i autoryzację. Po
sprawdzeniu manifestu, CSV i siatek UTC zapisuje osobne wyniki development
i walidacji, metryki i equity curve w
`reports/research_pipeline/E005_trend_backtest/<run-id>/`.
`ATTEMPT_STARTED.json` rejestruje GitHub run ID, identyfikator recenzenta,
commit workflow, SHA-256 wniosku i wejść oraz moment uruchomienia.
`COMPLETED` pojawia się po obu etapach. Workflow pozostaje w przeglądzie,
a weryfikacja online prawdziwej decyzji jest do wykonania po wdrożeniu.
Planowanie nadal raportuje `execution_allowed: false`.
