# Oficjalny katalog modów

## Rola katalogu

Katalog jest zdalnie aktualizowaną, oficjalną listą modów StrelokPL. Adres repozytorium może
zostać zmieniony bez utraty powiązania z zainstalowanym archiwum. Tożsamość logiczną określa
stałe pole `id`, a instalację lokalną dokładne pole `archiveName`.

## Nagłówek

```json
{
  "schemaVersion": 1,
  "catalogVersion": 2,
  "minimumUpdaterVersion": "0.1.0",
  "publishedAt": "2026-08-29",
  "mods": []
}
```

- `schemaVersion` — wersja technicznego formatu pliku;
- `catalogVersion` — rosnący numer publikowanej listy;
- `minimumUpdaterVersion` — najstarsza wersja aplikacji potrafiąca użyć katalogu;
- `publishedAt` — data informacyjna w formacie ISO;
- `mods` — lista wszystkich aktywnych i historycznych wpisów.

## Aktywny mod

```json
{
  "id": "strelokpl.ursus16541954",
  "name": "Ursus 1654/1954 Pack",
  "archiveName": "FS25_Ursus_1654_1954_Pack.zip",
  "repository": "StrielokPL/Ursus16541954",
  "assetPattern": "FS25_Ursus_1654_1954_Pack.zip",
  "modDescTitles": ["Ursus 1654-1954 Pack"],
  "status": "active",
  "description": "Oficjalny pakiet Ursus 1654/1954."
}
```

Pole `repository` może zostać zmienione w kolejnej wersji katalogu. `id` powinno pozostać
niezmienne. `archiveName` jest dokładną nazwą instalowanego pliku. `assetPattern` może zawierać
maskę, ale jeśli w wydaniu istnieje asset o dokładnej nazwie `archiveName`, ma on pierwszeństwo.

`modDescTitles` zawiera dozwolone angielskie tytuły odczytywane z
`<title><en>...</en></title>` w `modDesc.xml`. Dla oficjalnych wpisów pole powinno być zawsze
uzupełnione. Dzięki temu sama przypadkowo zgodna nazwa ZIP-a nie wystarczy do nadpisania innego
moda.

Updater rozpoznaje autora jako StrelokPL, gdy `StrielokPL` występuje jako osobna pozycja w
rozdzielonej przecinkami liście `<author>`. Nie zależy to od numeru linii ani kolejności autorów.
Zgodny tytuł i autor StrelokPL oznaczają mod zarządzany. Zgodny tytuł bez StrelokPL oznacza
oryginalny mod możliwy do zastąpienia po ostrzeżeniu i utworzeniu kopii. Niezgodny tytuł blokuje
automatyczną podmianę.

## Statusy historyczne

- `active` — normalnie rozwijany;
- `archived` — pozostaje rozpoznawalny, ale nie otrzymuje aktualizacji;
- `merged` — połączony z inną paczką;
- `deprecated` — zastąpiony nowym projektem;
- `unavailable` — tymczasowo niedostępny.

Nie należy usuwać wpisu z katalogu, jeśli jego archiwum mogło zostać zainstalowane przez
użytkowników.

## Merge kilku modów

Stare wpisy pozostają w katalogu:

```json
{
  "id": "strelokpl.old-a",
  "name": "Old A",
  "archiveName": "FS25_OldA.zip",
  "repository": "StrielokPL/OldA",
  "status": "merged",
  "replacementId": "strelokpl.combined-pack"
}
```

Nowa paczka wskazuje wszystkie zastępowane identyfikatory:

```json
{
  "id": "strelokpl.combined-pack",
  "name": "Combined Pack",
  "archiveName": "FS25_CombinedPack.zip",
  "repository": "StrielokPL/CombinedPack",
  "status": "active",
  "replaces": [
    "strelokpl.old-a",
    "strelokpl.old-b"
  ],
  "migration": {
    "type": "merge",
    "saveRisk": true,
    "message": "Po migracji sprawdź posiadane maszyny przed zapisaniem gry."
  }
}
```

Jeżeli updater wykryje stare archiwa, pobiera i sprawdza nową paczkę, kopiuje stare pliki oraz
savegame'y, usuwa stare ZIP-y i instaluje nowy. Cała operacja trafia do wspólnej historii i może
zostać cofnięta.

## Publikacja katalogu

1. Zmień plik `src/strelok_fs25_mod_updater/resources/official_catalog.json`.
2. Zwiększ `catalogVersion`.
3. Zatwierdź zmianę w gałęzi `main`.
4. Uruchom workflow **Publish official catalog** i podaj ten sam numer.
5. Workflow zweryfikuje plik i utworzy wydanie `catalog-vN` z assetem
   `strelok-mod-catalog.json`.

Program ignoruje wydanie katalogu, jeśli tag, numer wewnątrz pliku i wymagania wersji aplikacji
nie są zgodne.
