# Historia zmian

## 0.0.1a6 — bezpieczniejsza aktualizacja Windows

- usunięto aktualizację opartą na ukrytym PowerShellu i `ExecutionPolicy Bypass`;
- dodano osobny program `StrelokFS25ModUpdaterHelper.exe`;
- helper czeka na zamknięcie GUI, podmienia zweryfikowany plik i uruchamia nową wersję;
- w razie błędu helper przywraca poprzednią wersję aplikacji;
- wydanie Windows zawiera zalecaną paczkę ZIP z aplikacją i helperem;
- wyłączono UPX oraz dodano metadane produktu i wersji do plików Windows.

## 0.0.1a5 — diagnostyka połączeń i awarii

- dodano szczegółowy log startu, zadań w tle i zapytań do GitHuba;
- dodano osobny log awarii natywnych Pythona i komunikatów Qt;
- status pokazuje aktualnie sprawdzany mod oraz repozytorium;
- podczas oczekiwania na GitHuba pasek postępu jest animowany zamiast stale pokazywać 0%;
- menu Pomoc pozwala otworzyć folder logów i zapisać gotowy pakiet diagnostyczny ZIP.

## 0.0.1a4 — stabilność zadań w tle

- naprawiono losowe zamykanie GUI podczas sprawdzania repozytoriów;
- aktywne zadania Qt są przechowywane do chwili dostarczenia wszystkich sygnałów;
- dodano test obciążeniowy 64 równoległych zadań dla źródeł i gotowych programów.

## 0.0.1a3 — automatyczna aktualizacja aplikacji

- dodano sprawdzanie nowych wydań updatera przy starcie i na żądanie;
- dodano automatyczny wybór pliku dla Windowsa lub Linuksa;
- dodano weryfikację rozmiaru oraz dostępnej sumy SHA-256;
- dodano bezpieczną podmianę programu i ponowne uruchomienie;
- przyszłe wydania stabilne nie będą automatycznie przechodzić na prerelease'y.

## 0.0.1a2 — wybór konkretnego wydania

- dodano zapamiętywany wybór konkretnego taga wydania osobno dla każdego moda;
- dodano możliwość świadomego powrotu do starszej wersji;
- dodano ostrzeżenie o ryzyku dla savegame'u przed instalacją starszego moda;
- lista wersji rozróżnia pełne wydania i prerelease'y.

## 0.0.1a1 — poprawka pierwszego uruchomienia

- poprawiono zamykanie aplikacji po zaakceptowaniu pierwszego monitu na Linuksie;
- dodano automatyczny test pełnej sekwencji pierwszego uruchomienia GUI.

## 0.0.1a — pierwsze wydanie alfa

- utworzono działający rdzeń aplikacji i GUI;
- dodano oficjalny katalog StrelokPL oraz jego zdalne aktualizacje;
- dodano skanowanie wersji modów z `modDesc.xml`;
- dodano obsługę pełnych wydań i prerelease'ów GitHub Releases;
- dodano kanały stabilny, testowy i wyłączony;
- dodano instalowanie, aktualizowanie, kopie bezpieczeństwa i rollback;
- dodano migracje łączące stare mody w nową paczkę;
- dodano kopie zapisów gry dla migracji wysokiego ryzyka;
- dodano rozróżnienie źródeł oficjalnych i zewnętrznych;
- dodano automatyczne buildy Windows/Linux i testy CI.
