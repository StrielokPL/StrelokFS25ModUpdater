from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .catalog import CatalogManager
from .catalog_updates import CatalogUpdate, CatalogUpdateService
from .fs25 import discover_mod_directories, scan_known_mods
from .github_client import GitHubClient
from .installer import ModInstaller
from .models import (
    CatalogMod,
    ModStatus,
    ReleaseChannel,
    SourceKind,
    UpdateCheck,
    UpdateState,
)
from .storage import (
    AppSettings,
    ExternalSourcesStore,
    HistoryStore,
    SettingsStore,
    config_dir,
)
from .task import Task, TaskSignals
from .update_service import UpdateCheckService


CHANNEL_LABELS = {
    ReleaseChannel.STABLE: "Stabilny",
    ReleaseChannel.PRERELEASE: "Testowy",
    ReleaseChannel.DISABLED: "Wyłączony",
}

STATE_LABELS = {
    UpdateState.UNKNOWN: "Nie sprawdzono",
    UpdateState.NOT_INSTALLED: "Do pobrania",
    UpdateState.CURRENT: "Aktualny",
    UpdateState.UPDATE_AVAILABLE: "Aktualizacja",
    UpdateState.PRERELEASE_AVAILABLE: "Wersja testowa",
    UpdateState.LOCAL_NEWER: "Lokalny nowszy",
    UpdateState.MIGRATION_AVAILABLE: "Migracja paczki",
    UpdateState.DISABLED: "Nieaktywny",
    UpdateState.ERROR: "Błąd",
}

SELECTABLE_STATES = {
    UpdateState.NOT_INSTALLED,
    UpdateState.UPDATE_AVAILABLE,
    UpdateState.PRERELEASE_AVAILABLE,
    UpdateState.MIGRATION_AVAILABLE,
}


class ExternalSourceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Dodaj zewnętrzne repozytorium")
        self.name_edit = QLineEdit()
        self.repository_edit = QLineEdit()
        self.repository_edit.setPlaceholderText("właściciel/repozytorium")
        self.archive_edit = QLineEdit()
        self.archive_edit.setPlaceholderText("FS25_NazwaModa.zip")
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("domyślnie: dokładna nazwa ZIP")

        form = QFormLayout()
        form.addRow("Nazwa wyświetlana:", self.name_edit)
        form.addRow("Repozytorium GitHub:", self.repository_edit)
        form.addRow("Nazwa archiwum:", self.archive_edit)
        form.addRow("Wzorzec assetu:", self.pattern_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        warning = QLabel(
            "Źródło zostanie oznaczone jako zewnętrzne. StrelokPL nie odpowiada za jego "
            "zawartość ani bezpieczeństwo."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #b45f06;")
        layout.addWidget(warning)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def build_mod(self, existing_ids: set[str]) -> CatalogMod:
        name = self.name_edit.text().strip()
        repository = self.repository_edit.text().strip()
        archive = self.archive_edit.text().strip()
        pattern = self.pattern_edit.text().strip() or archive
        slug = re.sub(r"[^a-z0-9._-]+", ".", f"{repository}.{archive}".casefold()).strip(".")
        mod_id = f"external.{slug}"
        suffix = 2
        base_id = mod_id
        while mod_id in existing_ids:
            mod_id = f"{base_id}.{suffix}"
            suffix += 1
        return CatalogMod(
            id=mod_id,
            name=name,
            archive_name=archive,
            repository=repository,
            asset_pattern=pattern,
            source=SourceKind.EXTERNAL,
        )


class MainWindow(QMainWindow):
    def __init__(self, *, smoke_test: bool = False):
        super().__init__()
        self.setWindowTitle("Strelok FS25 Mod Updater")
        self.resize(1080, 720)

        self.settings_store = SettingsStore()
        self.settings: AppSettings = self.settings_store.load()
        self.external_store = ExternalSourcesStore()
        self.history = HistoryStore()
        self.catalog_manager = CatalogManager(config_dir() / "official_catalog.json")
        self.github = GitHubClient()
        self.catalog_updates = CatalogUpdateService(self.github, self.catalog_manager)
        self.update_checks = UpdateCheckService(self.github)
        self.installer = ModInstaller(self.github, self.history)
        self.thread_pool = QThreadPool.globalInstance()
        self.busy_tasks = 0

        self.catalog = self.catalog_manager.current()
        self.external_mods = self.external_store.load()
        self.mods: tuple[CatalogMod, ...] = ()
        self.local_mods: dict[str, Any] = {}
        self.checks: dict[str, UpdateCheck] = {}
        self.row_ids: dict[int, str] = {}

        self._build_ui()
        self._reload_mod_list()
        self._initialise_path()
        if not smoke_test:
            self._show_first_run_warning()
            QTimer.singleShot(250, self._startup_check)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Folder modów:"))
        self.path_edit = QLineEdit(self.settings.mods_directory)
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit, 1)
        self.detect_button = QPushButton("Wykryj")
        self.detect_button.clicked.connect(self._choose_detected_path)
        self.browse_button = QPushButton("Wybierz…")
        self.browse_button.clicked.connect(self._browse_path)
        path_layout.addWidget(self.detect_button)
        path_layout.addWidget(self.browse_button)
        root.addLayout(path_layout)

        toolbar = QHBoxLayout()
        self.check_button = QPushButton("Sprawdź aktualizacje")
        self.check_button.clicked.connect(self._begin_release_check)
        self.install_button = QPushButton("Pobierz / aktualizuj zaznaczone")
        self.install_button.clicked.connect(self._install_selected)
        self.add_external_button = QPushButton("Dodaj zewnętrzne repo")
        self.add_external_button.clicked.connect(self._add_external)
        self.remove_external_button = QPushButton("Usuń zewnętrzne")
        self.remove_external_button.clicked.connect(self._remove_external)
        self.rollback_button = QPushButton("Cofnij aktualizację")
        self.rollback_button.clicked.connect(self._rollback)
        toolbar.addWidget(self.check_button)
        toolbar.addWidget(self.install_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.add_external_button)
        toolbar.addWidget(self.remove_external_button)
        toolbar.addWidget(self.rollback_button)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Wybór",
                "Źródło",
                "Mod",
                "Zainstalowana",
                "Stabilna",
                "Testowa",
                "Kanał",
                "Stan",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_selected_details)
        splitter.addWidget(self.table)

        self.details = QTextBrowser()
        self.details.setPlaceholderText("Wybierz mod, aby zobaczyć opis i informacje o wydaniu.")
        splitter.addWidget(self.details)
        splitter.setSizes([480, 180])
        root.addWidget(splitter, 1)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Gotowy")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(280)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress)
        root.addLayout(status_layout)

    def _show_first_run_warning(self) -> None:
        if self.settings.first_run_warning_seen:
            return
        QMessageBox.information(
            self,
            "Ważna informacja o nazwach plików",
            "Nie zmieniaj nazw archiwów ZIP zarządzanych przez updater.\n\n"
            "Nazwa archiwum służy do rozpoznawania zainstalowanego moda. Plik o zmienionej "
            "nazwie może nie zostać rozpoznany, a ponowne pobranie może utworzyć "
            "drugą kopię.",
        )
        self.settings.first_run_warning_seen = True
        self.settings_store.save(self.settings)

    def _initialise_path(self) -> None:
        current = Path(self.settings.mods_directory) if self.settings.mods_directory else None
        if current and current.is_dir():
            self._scan_local()
            return
        detected = discover_mod_directories()
        if len(detected) == 1:
            self._set_mods_directory(detected[0])
        else:
            self._scan_local()

    def _reload_mod_list(self) -> None:
        self.catalog = self.catalog_manager.current()
        self.external_mods = self.external_store.load()
        self.mods = self.catalog.mods + self.external_mods

    def _mods_directory(self) -> Path | None:
        text = self.settings.mods_directory.strip()
        return Path(text) if text else None

    def _set_mods_directory(self, path: Path) -> None:
        self.settings.mods_directory = str(path)
        self.path_edit.setText(str(path))
        self.settings_store.save(self.settings)
        self._scan_local()

    def _browse_path(self) -> None:
        initial = self.settings.mods_directory or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Wybierz folder modów FS25", initial)
        if selected:
            self._set_mods_directory(Path(selected))

    def _choose_detected_path(self) -> None:
        detected = discover_mod_directories()
        if not detected:
            QMessageBox.information(
                self,
                "Nie znaleziono folderu",
                "Nie udało się automatycznie znaleźć folderu modów. Wskaż go ręcznie.",
            )
            return
        if len(detected) == 1:
            self._set_mods_directory(detected[0])
            return
        labels = [str(path) for path in detected]
        selected, ok = QInputDialog.getItem(
            self, "Wybierz profil FS25", "Znalezione foldery:", labels, 0, False
        )
        if ok and selected:
            self._set_mods_directory(Path(selected))

    def _scan_local(self) -> None:
        directory = self._mods_directory()
        self.local_mods = scan_known_mods(directory, self.mods) if directory else {}
        self._populate_without_remote()

    def _populate_without_remote(self) -> None:
        checks: list[UpdateCheck] = []
        for mod in self.mods:
            check = UpdateCheck(mod=mod, local=self.local_mods.get(mod.id))
            if mod.status is not ModStatus.ACTIVE:
                check.state = UpdateState.DISABLED
            elif check.local:
                check.message = "Oczekuje na sprawdzenie GitHuba"
            else:
                check.state = UpdateState.NOT_INSTALLED
                check.message = "Mod nie jest zainstalowany"
            checks.append(check)
        self._populate_table(checks)

    def _startup_check(self) -> None:
        self._set_status("Sprawdzanie wersji oficjalnej listy modów…")

        def work(_signals: TaskSignals):
            return self.catalog_updates.check()

        self._start_task(
            work,
            self._catalog_checked,
            error=self._catalog_check_failed,
        )

    def _catalog_checked(self, update: CatalogUpdate | None) -> None:
        if update is None:
            self._begin_release_check()
            return
        answer = QMessageBox.question(
            self,
            "Dostępna nowa lista modów",
            f"Dostępna jest nowa oficjalna lista modów StrelokPL.\n\n"
            f"Wersja {update.current_version} → {update.release.catalog_version}\n\n"
            "Czy pobrać ją teraz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._apply_catalog_update(update)
        else:
            self._set_status("Pominięto aktualizację listy modów")
            self._begin_release_check()

    def _catalog_check_failed(self, message: str, _traceback: str) -> None:
        self._set_status(f"Nie sprawdzono listy modów: {message}")
        self._begin_release_check()

    def _apply_catalog_update(self, update: CatalogUpdate) -> None:
        self._set_status("Pobieranie nowej oficjalnej listy modów…")

        def work(_signals: TaskSignals):
            return self.catalog_updates.download_and_install(update)

        def success(_catalog: object) -> None:
            self._reload_mod_list()
            self._scan_local()
            self._set_status("Zaktualizowano oficjalną listę modów")
            self._begin_release_check()

        self._start_task(work, success)

    def _begin_release_check(self) -> None:
        self._scan_local()
        channels = {mod.id: self.settings.channel_for(mod.id) for mod in self.mods}
        self._set_status("Sprawdzanie wydań modów na GitHubie…")

        def work(_signals: TaskSignals):
            return self.update_checks.check_all(self.mods, self.local_mods, channels)

        def success(checks: list[UpdateCheck]) -> None:
            self._populate_table(checks)
            errors = sum(1 for check in checks if check.state is UpdateState.ERROR)
            updates = sum(1 for check in checks if check.state in SELECTABLE_STATES)
            if errors:
                self._set_status(f"Znaleziono {updates} pozycji; błędy źródeł: {errors}")
            else:
                self._set_status(f"Znaleziono {updates} pozycji do pobrania lub aktualizacji")

        self._start_task(work, success)

    def _populate_table(self, checks: list[UpdateCheck]) -> None:
        self.checks = {check.mod.id: check for check in checks}
        self.row_ids.clear()
        self.table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            self.row_ids[row] = check.mod.id
            selection = QTableWidgetItem()
            selection.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if check.state in SELECTABLE_STATES and check.selected_release:
                selection.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                selection.setCheckState(Qt.CheckState.Unchecked)
            else:
                selection.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, selection)

            source_text = (
                "✓ StrelokPL"
                if check.mod.source is SourceKind.OFFICIAL
                else "⚠ Zewnętrzny"
            )
            source_item = QTableWidgetItem(source_text)
            source_item.setForeground(
                QColor("#2e7d32") if check.mod.source is SourceKind.OFFICIAL else QColor("#b45f06")
            )
            self.table.setItem(row, 1, source_item)
            name_item = QTableWidgetItem(check.mod.name)
            name_item.setData(Qt.ItemDataRole.UserRole, check.mod.id)
            self.table.setItem(row, 2, name_item)
            self.table.setItem(
                row,
                3,
                QTableWidgetItem(check.local.version_text if check.local else "—"),
            )
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(check.stable.tag if check.stable else "—"),
            )
            self.table.setItem(
                row,
                5,
                QTableWidgetItem(check.prerelease.tag if check.prerelease else "—"),
            )

            channel = QComboBox()
            for value, label in CHANNEL_LABELS.items():
                channel.addItem(label, value.value)
            selected_channel = self.settings.channel_for(check.mod.id)
            index = channel.findData(selected_channel.value)
            channel.setCurrentIndex(max(index, 0))
            channel.setEnabled(check.mod.status is ModStatus.ACTIVE)
            channel.currentIndexChanged.connect(
                lambda _index, mod_id=check.mod.id, widget=channel: self._channel_changed(
                    mod_id, widget
                )
            )
            self.table.setCellWidget(row, 6, channel)

            state_item = QTableWidgetItem(STATE_LABELS[check.state])
            state_item.setToolTip(check.message)
            if check.state in SELECTABLE_STATES:
                state_item.setForeground(QColor("#c75b00"))
            elif check.state is UpdateState.CURRENT:
                state_item.setForeground(QColor("#2e7d32"))
            elif check.state is UpdateState.ERROR:
                state_item.setForeground(QColor("#b00020"))
            self.table.setItem(row, 7, state_item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _channel_changed(self, mod_id: str, combo: QComboBox) -> None:
        channel = ReleaseChannel(str(combo.currentData()))
        self.settings.set_channel(mod_id, channel)
        self.settings_store.save(self.settings)
        QTimer.singleShot(0, self._begin_release_check)

    def _show_selected_details(self) -> None:
        row = self.table.currentRow()
        mod_id = self.row_ids.get(row)
        check = self.checks.get(mod_id or "")
        if check is None:
            self.details.clear()
            return
        source = (
            "Oficjalny mod StrelokPL"
            if check.mod.source is SourceKind.OFFICIAL
            else "Zewnętrzne źródło — brak odpowiedzialności StrelokPL"
        )
        release = check.selected_release or check.stable or check.prerelease
        lines = [
            f"## {check.mod.name}",
            "",
            f"**Źródło:** {source}",
            f"**Repozytorium:** `{check.mod.repository}`",
            f"**Archiwum:** `{check.mod.archive_name}`",
            f"**Stan:** {STATE_LABELS[check.state]} — {check.message}",
        ]
        if check.mod.description:
            lines.extend(["", check.mod.description])
        if release:
            lines.extend(["", f"### {release.name}", "", release.notes or "Brak opisu wydania."])
        self.details.setMarkdown("\n".join(lines))

    def _selected_checks(self) -> list[UpdateCheck]:
        selected: list[UpdateCheck] = []
        for row, mod_id in self.row_ids.items():
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                check = self.checks.get(mod_id)
                if check and check.selected_release:
                    selected.append(check)
        return selected

    def _install_selected(self) -> None:
        selected = self._selected_checks()
        if not selected:
            QMessageBox.information(self, "Brak wyboru", "Zaznacz co najmniej jeden mod.")
            return
        mods_directory = self._mods_directory()
        if mods_directory is None or not mods_directory.is_dir():
            QMessageBox.warning(self, "Brak folderu", "Najpierw wskaż istniejący folder modów.")
            return

        migrations = [check for check in selected if check.replaced_local_mods]
        if migrations:
            replaced = "\n".join(
                f"• {local.path.name}"
                for check in migrations
                for local in check.replaced_local_mods
            )
            answer = QMessageBox.warning(
                self,
                "Migracja może wpłynąć na zapis gry",
                "Aktualizacja połączy lub zastąpi następujące archiwa:\n\n"
                f"{replaced}\n\n"
                "Przed zmianą updater wykona kopię starych modów i wszystkich savegame'ów. "
                "Mimo to po wczytaniu zapisu sprzęt ze starych modów może zniknąć.\n\n"
                "Czy kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        def work(signals: TaskSignals):
            events = []
            for index, check in enumerate(selected, start=1):
                signals.status.emit(f"{index}/{len(selected)}: {check.mod.name}")
                event = self.installer.install(
                    check.mod,
                    check.selected_release,  # type: ignore[arg-type]
                    mods_directory,
                    replaced_mods=check.replaced_local_mods,
                    backup_savegames=bool(
                        check.replaced_local_mods
                        and check.mod.migration
                        and check.mod.migration.save_risk
                    ),
                    status=signals.status.emit,
                    progress=signals.progress.emit,
                )
                events.append(event)
            return events

        def success(events: list[dict[str, object]]) -> None:
            QMessageBox.information(
                self,
                "Zakończono",
                f"Pomyślnie zainstalowano lub zaktualizowano {len(events)} pozycji.",
            )
            self._scan_local()
            self._begin_release_check()

        self._start_task(work, success)

    def _add_external(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Zewnętrzne źródło",
            "Repozytorium nie będzie częścią oficjalnego katalogu StrelokPL. "
            "Autor programu nie odpowiada za pobierane z niego pliki.\n\n"
            "Czy chcesz kontynuować?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dialog = ExternalSourceDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            mod = dialog.build_mod({item.id for item in self.mods})
        except ValueError as exc:
            QMessageBox.warning(self, "Nieprawidłowe dane", str(exc))
            return
        external = list(self.external_mods)
        external.append(mod)
        self.external_store.save(external)
        self._reload_mod_list()
        self._scan_local()
        self._begin_release_check()

    def _remove_external(self) -> None:
        row = self.table.currentRow()
        mod_id = self.row_ids.get(row)
        mod = next((item for item in self.external_mods if item.id == mod_id), None)
        if mod is None:
            QMessageBox.information(self, "Wybierz źródło", "Wybierz zewnętrzny mod z tabeli.")
            return
        answer = QMessageBox.question(
            self,
            "Usuń zewnętrzne źródło",
            f"Usunąć źródło {mod.name}?\n\nZainstalowane archiwum nie zostanie usunięte.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.external_store.save([item for item in self.external_mods if item.id != mod.id])
            self._reload_mod_list()
            self._scan_local()

    def _rollback(self) -> None:
        events = [event for event in reversed(self.history.load()) if event.get("backupDirectory")]
        if not events:
            QMessageBox.information(
                self,
                "Brak kopii",
                "Nie ma aktualizacji możliwej do cofnięcia.",
            )
            return
        labels = [
            f"{event.get('timestamp', '')[:19]} — "
            f"{event.get('archiveName', '')} — {event.get('version', '')}"
            for event in events
        ]
        selected, ok = QInputDialog.getItem(
            self, "Cofnij aktualizację", "Wybierz operację:", labels, 0, False
        )
        if not ok:
            return
        event = events[labels.index(selected)]
        restore_saves = False
        if event.get("savegamesBackedUp"):
            answer = QMessageBox.question(
                self,
                "Przywrócić zapisy gry?",
                "Ta migracja zawiera również kopie savegame'ów. Czy je przywrócić?\n\n"
                "Obecne wersje tych zapisów zostaną zastąpione.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            restore_saves = answer == QMessageBox.StandardButton.Yes
        mods_directory = self._mods_directory()
        if mods_directory is None:
            return

        def work(_signals: TaskSignals):
            self.installer.rollback(event, mods_directory, restore_savegames=restore_saves)
            return True

        def success(_result: object) -> None:
            QMessageBox.information(self, "Przywrócono", "Poprzednie pliki zostały przywrócone.")
            self._scan_local()
            self._begin_release_check()

        self._start_task(work, success)

    def _start_task(
        self,
        function,
        result,
        *,
        error=None,
    ) -> None:
        task = Task(function)
        task.signals.result.connect(result)
        task.signals.error.connect(error or self._task_error)
        task.signals.status.connect(self._set_status)
        task.signals.progress.connect(self._set_progress)
        task.signals.finished.connect(self._task_finished)
        self.busy_tasks += 1
        self._update_busy_state()
        self.thread_pool.start(task)

    def _task_finished(self) -> None:
        self.busy_tasks = max(0, self.busy_tasks - 1)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._update_busy_state()

    def _task_error(self, message: str, traceback_text: str) -> None:
        logging.getLogger(__name__).error("Błąd zadania w tle:\n%s", traceback_text)
        self._set_status(f"Błąd: {message}")
        QMessageBox.critical(
            self,
            "Błąd",
            f"{message}\n\nSzczegóły zapisano w logu aplikacji.",
        )
        QApplication.instance().setProperty("last_task_traceback", traceback_text)

    def _update_busy_state(self) -> None:
        busy = self.busy_tasks > 0
        for button in (
            self.check_button,
            self.install_button,
            self.detect_button,
            self.browse_button,
            self.add_external_button,
            self.remove_external_button,
            self.rollback_button,
        ):
            button.setEnabled(not busy)
        self.table.setEnabled(not busy)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_progress(self, received: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(min(100, int(received * 100 / total)))
