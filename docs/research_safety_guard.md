# Research Safety Guard

Kontrola chroni archiwa E001–E003 przed zmianami wprowadzanymi przez pull
requesty do `main`. Obejmuje protokoły w katalogach tych eksperymentów, wyniki
i raport zbiorczy, raporty przygotowania danych oraz archiwum audytu holdoutu.
Chronione są m.in. `FINAL_HOLDOUT_PROTOCOL.md`, `E002_FROZEN_MANIFEST.json`,
`ATTEMPT_STARTED.json` i `holdout_summary.json`. Pełny zakres jest zapisany
w [skrypcie kontroli](../scripts/check_research_safety.py). Nowe eksperymenty
mogą dodawać pliki w osobnych katalogach.

## Sprawdzenie lokalne

```powershell
uv run python scripts/check_research_safety.py
uv run python scripts/check_research_safety.py --base main --head HEAD
```

Pierwsze polecenie porównuje indeks i śledzone pliki katalogu roboczego z
lokalnym `main`. Drugie porównuje wskazane commity. Użyj aktualnej lokalnej
bazy, aby wynik odpowiadał stanowi `main` w GitHub. Kody wyjścia to `0`
dla poprawnego wyniku, `1` dla naruszenia i `2` dla błędu kontroli.
Przeniesienie pliku Git przedstawia tu jako usunięcie ze starej ścieżki
i dodanie pod nową. Unika to zależności od progu podobieństwa treści.

## Kontrola w GitHub Actions

Zadanie **Research Safety Guard** w [workflow CI](../.github/workflows/tests.yml)
działa dla PR do `main`. GitHub udostępnia próbny commit scalenia jako
`HEAD`. Checkout z `fetch-depth: 2` pobiera także jego rodziców. Skrypt
porównuje wynik scalenia z `HEAD^1`, czyli stanem gałęzi bazowej użytym w tym
scaleniu, nawet gdy w runnerze brak lokalnej referencji `main`.
[Zdarzenie pull_request](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
· [Pobieranie rodzica w actions/checkout](https://github.com/actions/checkout/blob/v6/README.md#checkout-head).

## Ograniczenia

- Kontrola porównuje końcowe stany drzew Git i dopasowuje ścieżki. Pomija
  pliki nieśledzone lokalnie i przejściowe zmiany cofnięte w obrębie PR.
  Nie sprawdza zawartości nowych raportów ani sum plików przywołanych
  w manifestach. Nie otwiera danych badawczych i nie uruchamia eksperymentów,
  w tym ewaluacji holdoutu E002.
- Autor PR może zmienić workflow albo skrypt i osłabić kontrolę. Bezpośredni
  push na `main` omija to zadanie. Egzekwowanie wymaga osobnej konfiguracji
  ochrony gałęzi lub rulesetu, wymaganego wyniku CI oraz obowiązkowego
  przeglądu zmian w workflow i skrypcie przez właścicieli. Silniejszą
  ochronę zapewni wymagana kontrola utrzymywana poza sprawdzanym PR.
