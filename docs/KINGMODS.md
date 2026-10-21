# Paczki modów jako zakładki

Każda lista jest oddzielną zakładką. Listy nie są scalane. Domyślne źródła:

- **Miziuu**: https://github.com/StrielokPL/MiziuuModList
- **StrielokPL**: https://github.com/StrielokPL/StrielokPLModList

## Najprostszy format — mods.txt

Pierwszy niepusty wiersz to nazwa zakładki, potem po jednym adresie na wiersz:

```text
Moja paczka
https://www.kingmods.net/en/fs25/mods/63913/ursus-c-330330m
https://modsfire.com/xnKLKu6d2U89Ej4
```

Puste wiersze i komentarze rozpoczynające się od `#` są pomijane. Maksymalnie
200 modów, 4 MB pliku i 80 znaków nazwy. Plik należy zapisać jako UTF-8.
KingMods i bezpośrednie ModsFire można mieszać w jednej liście.

**Opcje → Dodaj paczkę z GitHuba…**: wklej adres publicznego repozytorium.
Aplikacja odczyta `mods.txt` z domyślnej gałęzi. Można też wskazać konkretny plik
TXT/JSON przez link GitHub `blob` albo `raw.githubusercontent.com`.

**Opcje → Wczytaj plik jako zakładkę…**: wskaż lokalny TXT lub JSON. Zostaje
zapamiętana ścieżka — kolejne odświeżenie odczyta aktualną zawartość tego pliku.
Przeniesienie/usunięcie pliku powoduje komunikat błędu i zachowanie ostatnich danych.
Nie należy usuwać pliku po imporcie, jeśli lista ma być dalej odświeżana.

**Opcje → Usuń bieżącą zakładkę…** usuwa subskrypcję, bez usuwania listy i modów.
Usunięte zakładki domyślne nie wracają przy ponownym uruchomieniu. Ponowne wczytanie
tego samego źródła wybiera istniejącą zakładkę. Różne źródła o identycznej nazwie
pozostają osobnymi paczkami; ich adresy są widoczne nad tabelą.

Każda paczka ma własne odświeżanie co 15 minut, filtr instalacji i wybór wersji.
Nazwa i usunięcie wpisu w źródle są odzwierciedlane przy odświeżeniu. Usunięcie
wpisu nie usuwa moda z dysku. Błąd listy zachowuje poprzednią poprawną zawartość.
Błąd pojedynczej strony nie zatrzymuje pozostałych pozycji. Bufor HTTP: 5 minut.

## KingMods, ModsFire i instalacja

KingMods dostarcza listę wersji i odpowiadające im strony plików ModsFire.
Bezpośredni link ModsFire wskazuje jeden plik; aplikacja nie zgaduje jego numeru
wersji. Pokazuje „Wersja z ZIP-a”, a numer odczytuje z modDesc.xml przy imporcie.

Użytkownik otwiera ModsFire, pobiera paczkę w przeglądarce i wybiera
**Wskaż pobrany ZIP i zainstaluj…**. Jeśli mod jest już zainstalowany, wybiera
kopię, podmianę bez kopii albo anulowanie. ZIP jest walidowany przed atomową
podmianą; po sukcesie plik znika z miejsca pobrania (przeniesienie). Błąd
walidacji, wykonania kopii lub podmiany zachowuje dotychczasowy mod i pobrany ZIP.

Sprawdzane są: nazwa pliku (w tym dopuszczony sufiks przeglądarki „ (1)”),
modDesc.xml, znany tytuł, integralność ZIP-a i numer wersji, jeśli podał go KingMods.
Kopie znajdują się w folderze danych aplikacji, w `backups`. **Pomoc → Otwórz
folder logów** otwiera ten folder.

## Zasady adresów i zaufania

Obce listy mogą zawierać tylko:

- `https://www.kingmods.net/<język>/fs25/mods/<numer>/<nazwa>`
- `https://modsfire.com/<identyfikator>`

Dopuszczone są też kanoniczne warianty domen bez/z `www`. HTTP, inne domeny,
porty inne niż 443, dane logowania w URL, zapytania/fragmenty i podszywające się
domeny są odrzucane. Przekierowania odczytywane przez aplikację podlegają walidacji
przed kolejnym żądaniem. Każdy link jest ponownie walidowany przed otwarciem
przeglądarki. Zawartość zewnętrznej listy nie może rozszerzyć listy zaufanych domen.
GitHub jest dopuszczony jako źródło tekstowego katalogu, nie dowolny hosting moda.

Wyjątek dotyczy dokładnie oficjalnego `StrielokPL/StrielokPLModList`, pliku
`mods.txt` na gałęzi `HEAD`/`main`: może wskazywać publiczny mod
`https://github.com/StrielokPL/Ursus16541954`. Aplikacja pobiera jego wydania
przez dotychczasowy klient GitHub. Nazwa zakładki „StrielokPL”, kopia pliku
lokalnego lub inny katalog nie nadają tego uprawnienia. Nowe repozytoria GitHub
wymagają jawnego rozszerzenia zaufanej konfiguracji aplikacji.

Ta kontrola ogranicza adresy obsługiwane przez aplikację. Nie jest skanerem
zawartości modów i nie kontroluje reklam lub dalszej nawigacji w przeglądarce.

## Opcjonalny JSON

```json
{
  "name": "Moja paczka",
  "mods": [
    {
      "url": "https://www.kingmods.net/en/fs25/mods/63913/ursus-c-330330m",
      "name": "Ursus C-330/330M",
      "archiveName": "FS25_UrsusC330_330M_4x2.zip",
      "modDescTitles": ["Ursus C-330/330M"]
    },
    "https://modsfire.com/xnKLKu6d2U89Ej4"
  ]
}
```

Metadane są opcjonalne: nazwa i archiwum zostają odczytane z KingMods/ModsFire.
JSON podlega tym samym zasadom URL co TXT. Istniejące obserwacje z a12 są
przenoszone do oddzielnej zakładki „Moje obserwowane”. Prywatne repozytoria editów
nie są obecnie zawarte w domyślnej oficjalnej liście.
