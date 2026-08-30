# Strelok FS25 Mod Updater

Graficzny aktualizator modów do Farming Simulator 25 wydawanych przez
[StrelokPL](https://github.com/StrielokPL). Program jest projektowany dla Windowsa i Linuksa.

> Wersja `0.0.1a3` jest pierwszym wydaniem alfa. Projekt jest na wczesnym etapie rozwoju
> i nie jest jeszcze przeznaczony do codziennego użycia bez testów oraz kopii zapasowych.

## Co już obsługuje

- oficjalny, wersjonowany katalog modów StrelokPL;
- osobne i wyraźnie oznaczone zewnętrzne repozytoria użytkownika;
- pełne wydania oraz prerelease'y GitHub Releases;
- kanał stabilny lub testowy wybierany osobno dla każdego moda;
- wybór konkretnego wydania, również świadoma instalacja starszej wersji z ostrzeżeniem;
- odczyt wersji bezpośrednio z `modDesc.xml` w archiwum ZIP;
- ścisłe rozpoznawanie moda po niezmienionej nazwie archiwum;
- automatyczne wykrywanie typowych folderów FS25 oraz ręczny wybór ścieżki;
- instalowanie wielu zaznaczonych modów;
- sprawdzenie ZIP-a, wersji i sumy SHA-256 przed podmianą;
- kopie poprzednich wersji i cofanie aktualizacji;
- migracje typu „kilka starych modów → jedna nowa paczka”;
- kopie savegame'ów przed migracją oznaczoną jako ryzykowna;
- blokadę aktualizacji podczas działania Farming Simulator 25;
- wyświetlanie opisu wydania i changelogu z GitHuba.
- automatyczną aktualizację samej aplikacji z podmianą i ponownym uruchomieniem.

## Ważna zasada

Nie należy zmieniać nazw pobranych archiwów ZIP. Nazwa pliku jest częścią identyfikacji moda.
Archiwum o zmienionej nazwie zostanie potraktowane jako niezarządzane i może pozostać obok
ponownie pobranej oficjalnej wersji.

## Uruchomienie ze źródeł

Wymagany jest Python 3.10 lub nowszy.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m strelok_fs25_mod_updater
```

W PowerShellu aktywacja środowiska wygląda tak:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m strelok_fs25_mod_updater
```

## Testy

Rdzeń nie wymaga Qt, dzięki czemu testy można uruchomić samym Pythonem:

```bash
PYTHONPATH=src python -m unittest discover -v
```

Na Windowsie:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -v
```

## Wydania programu

Tag `vX.Y.Z` uruchamia budowę:

- `StrelokFS25ModUpdater-Windows-x64.exe`;
- `StrelokFS25ModUpdater-Linux-x64.tar.gz`.

Buildy powstają natywnie na odpowiednim systemie przez GitHub Actions.

Workflow można również uruchomić ręcznie bez tworzenia wydania. Commit zawierający w opisie
`[build]` przygotuje oba pliki jako prywatne artefakty testowe GitHub Actions. Commit z
`[release]` zbuduje pliki, utworzy tag z wersji zapisanej w `pyproject.toml` i opublikuje
wydanie. Wersje z literowym sufiksem są automatycznie oznaczane jako prerelease.

Na typowym systemie Linux Mint wymagane biblioteki graficzne są już obecne. Jeżeli ręczne
uruchomienie zgłosi brak `libEGL.so.1`, należy doinstalować systemowy pakiet `libegl1`.

Od wersji `0.0.1a3` program sprawdza również własne wydania. Aktualizacja jest pobierana do
folderu aplikacji, bezpiecznie podmieniana po weryfikacji rozmiaru i dostępnej sumy SHA-256,
a następnie program uruchamia się ponownie. Ustawienia i folder modów nie są zmieniane.

## Oficjalny katalog

Katalog startowy znajduje się w
`src/strelok_fs25_mod_updater/resources/official_catalog.json`.

Program sprawdza w tym repozytorium wydania o tagach `catalog-vN` i szuka assetu
`strelok-mod-catalog.json`. Gdy numer katalogu jest wyższy, użytkownik otrzymuje mały monit
i sam decyduje o pobraniu.

Repozytorium updatera oraz oficjalne repozytoria modów muszą być publiczne przed
udostępnieniem programu użytkownikom. W aplikacji nie będzie umieszczany żaden prywatny token.

Pełny opis formatu i migracji znajduje się w [docs/CATALOG.md](docs/CATALOG.md).

## Bezpieczeństwo

- aplikacja pobiera wyłącznie assety dołączone do GitHub Releases, nigdy automatyczne archiwa
  „Source code”;
- nowe archiwum jest najpierw pobierane pod nazwą tymczasową i walidowane;
- stary plik jest kopiowany do katalogu kopii przed podmianą;
- błędne pobranie nie powinno naruszyć istniejącego moda;
- zewnętrzne źródła nie mogą nadać sobie statusu oficjalnego;
- aktualizacja oficjalnego katalogu nie usuwa ustawień ani zewnętrznych repozytoriów użytkownika.
