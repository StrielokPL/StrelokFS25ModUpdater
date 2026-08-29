# Architektura

Kod jest rozdzielony tak, aby logika aktualizacji nie zależała od Qt i mogła być testowana bez
uruchamiania GUI.

- `models.py` — kontrakty katalogu, modów lokalnych, wydań i stanów aktualizacji;
- `versioning.py` — wersje FS w formacie do czterech segmentów i sufiksy testowe;
- `fs25.py` — wykrywanie folderów, odczyt `modDesc.xml`, savegame'y i SHA-256;
- `github_client.py` — publiczne GitHub Releases i pobieranie assetów;
- `catalog.py`, `catalog_updates.py` — katalog wbudowany, cache i zdalne wydania katalogu;
- `update_service.py` — decyzja, która wersja jest aktualna dla wybranego kanału;
- `installer.py` — instalacja transakcyjna, kopie, migracje i rollback;
- `storage.py` — atomowy zapis ustawień, źródeł zewnętrznych i historii;
- `gui.py` — prezentacja i sterowanie zadaniami wykonywanymi poza głównym wątkiem;
- `task.py` — bezpieczny most między zadaniami w tle i Qt.

Oficjalny status pochodzi wyłącznie z katalogu updatera. Wpisy utworzone lokalnie zawsze mają
typ `external`, niezależnie od nazwy autora, repozytorium lub archiwum.

