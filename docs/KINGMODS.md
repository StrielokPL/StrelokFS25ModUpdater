# Obserwowanie modów KingMods

Główna zakładka **KingMods** zawiera obserwowane strony FS25 (na start C-330
oraz C355–C360). Nie przeszukuje całego serwisu. **Moje mody i edity** zachowuje
katalog i instalację wydań z GitHub Releases, w tym zewnętrzne repozytoria.

- **Dodaj link KingMods…** dodaje pojedynczy mod.
- **Importuj listę z GitHuba…** przyjmuje publiczny plik TXT lub JSON przez link
  `https://github.com/OWNER/REPO/blob/main/plik.json` albo adres raw.
- TXT: jeden link KingMods na linię; puste linie i komentarze `#` są pomijane.
- JSON: obiekt `{"mods": [...]}` lub lista. Wpis może być linkiem albo obiektem
  z polami `url`, `name`, `archiveName`, `modDescTitles`, `editId`.
- `archiveName` to docelowa nazwa ZIP. Bez niej aplikacja odczytuje nazwę z
  pierwszej strony pliku ModsFire. `modDescTitles` pozwala dodatkowo sprawdzić
  tożsamość moda; zalecane dla katalogu współdzielonego.
- `editId` wiąże oryginał z identyfikatorem w katalogu GitHub, np.
  `strelokpl.ursus330fs25`. Dopasowanie działa także po nazwie archiwum.

Gotowe przykłady: `examples/kingmods-links.txt` i `examples/kingmods-catalog.json`.
Można skopiować je do osobnego repozytorium z samymi odnośnikami. Aplikacja nie
wymaga haseł ani tokenów do publicznego katalogu.

Adres katalogu jest zapamiętywany i sprawdzany razem z wersjami. Import scala
wpisy według numeru moda KingMods, zachowując wcześniejsze metadane, gdy prosty
wpis ich nie dostarcza. Usunięcie pozycji z pliku nie usuwa lokalnej obserwacji.
Pozycja usunięta lokalnie wróci, jeśli nadal jest obecna w katalogu GitHub.

## Wersje i instalowanie

Sprawdzanie odbywa się po uruchomieniu i co 15 minut (można odznaczyć), a także
przyciskiem **Sprawdź wersje**. Odpowiedzi są buforowane na 5 minut. Gdy aplikacja
jest zajęta instalacją, automatyczne sprawdzenie poczeka. Błąd jednej strony nie
zatrzymuje sprawdzania pozostałych. Ostatni odczyt z bieżącej sesji pozostaje w
 tabeli z oznaczeniem błędu. Błąd katalogu GitHub jest pokazany w pasku stanu.

Wybierz numer wydania i **Otwórz wybraną wersję na ModsFire**. Link prowadzi do
strony pliku wskazanej przez KingMods; pobieranie i generowanie linku odbywa się
ręcznie w przeglądarce. Brak wybranej wersji nie przełącza automatycznie na inną.

**Wskaż pobrany ZIP i zainstaluj…**:

1. Jeśli istnieje poprzedni mod: **Tak** zachowuje jego kopię, **Nie** zastępuje
   bez kopii, **Anuluj** przerywa operację.
2. Aplikacja kopiuje pobrany plik do pliku tymczasowego w folderze modów,
   sprawdza modDesc.xml, wersję, nazwę archiwum, znany tytuł i integralność ZIP.
   Sufiksy przeglądarki, np. ` (1).zip`, są akceptowane.
3. Dopiero po walidacji i wykonaniu wybranej kopii zastępuje docelowy ZIP
   atomowo. Po sukcesie usuwa plik z miejsca pobrania — jest to przeniesienie.
   Błąd walidacji/kopii/podmiany zachowuje poprzedniego moda i pobrany plik.
4. Błąd usunięcia pliku z folderu pobierania jest zgłaszany jako ostrzeżenie po
   udanej instalacji, nie jako błąd instalacji.

Kopie i historia znajdują się w folderze danych aplikacji (`backups`); menu
**Pomoc → Otwórz folder logów** otwiera ten folder. Kopia oryginału powiązanego
z editem jest widoczna w istniejącej funkcji **Przywróć oryginalny mod…**.
Zwykła aktualizacja GitHub również pyta o zachowanie kopii. Migracje łączące
kilka archiwów nadal wykonują wymagane kopie modów i zapisów gry.

Filtr działa dla wszystkich, zainstalowanych lub niezainstalowanych modów.
Kolumna **Edit StrelokPL** oznacza dostępne powiązanie w katalogu, nawet jeśli
repozytorium editu jest w przygotowaniu. Stan osobno informuje, czy zainstalowana
paczka ma autora StrielokPL. Numeracja editu nie jest porównywana z oryginałem.

Ta zmiana instaluje całe oryginalne ZIP-y. Nie nakłada jeszcze łatek na oryginał
ani nie zmienia sposobu publikacji Twoich editów na GitHubie.

## Rozbudowa

`KingModsClient` i modele w `kingmods.py` są niezależne od Qt. `KingModsTab`
obsługuje listę, filtry i akcje tego źródła. `MainWindow.register_source_tab`
rejestruje zakładki po unikalnym identyfikatorze, umożliwiając dodawanie kolejnych.
KingMods jest odczytywany z HTML, więc zmiana struktury serwisu może wymagać
aktualizacji parsera. Nie ma obchodzenia logowania ani zabezpieczeń hostingu.
