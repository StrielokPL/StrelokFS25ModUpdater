from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
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
from .diagnostics import create_diagnostic_bundle
from .fs25 import discover_mod_directories, scan_known_mods
from .github_client import GitHubClient
from .installer import ModInstaller
from .models import (
    CatalogMod,
    LocalModKind,
    ModStatus,
    ReleaseChannel,
    SourceKind,
    UpdateCheck,
    UpdateState,
)
from .self_update import (
    ApplicationUpdate,
    ApplicationUpdateService,
    PreparedApplicationUpdate,
    SelfUpdateError,
)
from .storage import (
    AppSettings,
    ExternalSourcesStore,
    HistoryStore,
    SettingsStore,
    config_dir,
    data_dir,
)
from .task import Task, TaskSignals
from .update_service import UpdateCheckService


STATE_LABELS = {
    UpdateState.UNKNOWN: "Nie sprawdzono",
    UpdateState.NOT_INSTALLED: "Do pobrania",
    UpdateState.CURRENT: "Aktualny",
    UpdateState.UPDATE_AVAILABLE: "Aktualizacja",
    UpdateState.PRERELEASE_AVAILABLE: "Wersja testowa",
    UpdateState.VERSION_CHANGE: "Zmiana wersji",
    UpdateState.LOCAL_NEWER: "Lokalny nowszy",
    UpdateState.UNMANAGED_REPLACEABLE: "Oryginał do zastąpienia",
    UpdateState.ARCHIVE_CONFLICT: "Konflikt archiwum",
    UpdateState.MIGRATION_AVAILABLE: "Migracja paczki",
    UpdateState.DISABLED: "Nieaktywny",
    UpdateState.ERROR: "Błąd",
}

SELECTABLE_STATES = {
    UpdateState.NOT_INSTALLED,
    UpdateState.UPDATE_AVAILABLE,
    UpdateState.PRERELEASE_AVAILABLE,
    UpdateState.VERSION_CHANGE,
    UpdateState.UNMANAGED_REPLACEABLE,
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
    def __init__(self):
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
        self.application_updates = ApplicationUpdateService(self.github)
        self.update_checks = UpdateCheckService(self.github)
        self.installer = ModInstaller(self.github, self.history)
        self.thread_pool = QThreadPool.globalInstance()
        self.active_tasks: set[Task] = set()
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

    def start(self, *, check_updates: bool = True) -> None:
        """Run startup actions after the main window has become visible."""
        self._show_first_run_warning()
        if check_updates:
            QTimer.singleShot(
                250,
                lambda: self._begin_application_update_check(startup=True),
            )

    def _build_ui(self) -> None:
        help_menu = self.menuBar().addMenu("Pomoc")
        open_logs_action = QAction("Otwórz folder logów", self)
        open_logs_action.triggered.connect(self._open_log_directory)
        help_menu.addAction(open_logs_action)
        save_diagnostics_action = QAction("Zapisz pakiet diagnostyczny…", self)
        save_diagnostics_action.triggered.connect(self._save_diagnostic_bundle)
        help_menu.addAction(save_diagnostics_action)

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
        self.app_update_button = QPushButton("Aktualizuj aplikację")
        self.app_update_button.clicked.connect(
            lambda: self._begin_application_update_check(startup=False)
        )
        toolbar.addWidget(self.check_button)
        toolbar.addWidget(self.install_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.app_update_button)
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
                "Kanał / wersja",
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
                if check.local.kind is LocalModKind.ARCHIVE_CONFLICT:
                    check.state = UpdateState.ARCHIVE_CONFLICT
                    check.message = (
                        "Tytuł w modDesc.xml nie odpowiada wpisowi oficjalnego katalogu"
                    )
                elif check.local.kind is LocalModKind.UNMANAGED_REPLACEABLE:
                    check.message = (
                        "Wykryto oryginalny mod; oczekuje na sprawdzenie GitHuba"
                    )
                else:
                    check.message = "Oczekuje na sprawdzenie GitHuba"
            else:
                check.state = UpdateState.NOT_INSTALLED
                check.message = "Mod nie jest zainstalowany"
            checks.append(check)
        self._populate_table(checks)

    def _begin_application_update_check(self, *, startup: bool) -> None:
        self._set_status("Sprawdzanie aktualizacji aplikacji…")

        def work(_signals: TaskSignals):
            return self.application_updates.check()

        self._start_task(
            work,
            lambda update: self._application_update_checked(update, startup=startup),
            error=lambda message, traceback_text: self._application_update_check_failed(
                message,
                traceback_text,
                startup=startup,
            ),
            name="application-update-check",
        )

    def _application_update_checked(
        self,
        update: ApplicationUpdate | None,
        *,
        startup: bool,
    ) -> None:
        if update is None:
            self._set_status("Aplikacja jest aktualna")
            if startup:
                self._begin_catalog_check()
            else:
                QMessageBox.information(
                    self,
                    "Brak aktualizacji",
                    "Masz najnowszą wersję aplikacji dla wybranego kanału.",
                )
            return

        size = f"{update.size / (1024 * 1024):.1f} MB" if update.size else "nieznany"
        release_kind = "prerelease" if update.prerelease else "wydanie stabilne"
        notes = update.notes.strip()
        notes_excerpt = f"\n\n{notes[:900]}" if notes else ""
        answer = QMessageBox.question(
            self,
            "Dostępna aktualizacja aplikacji",
            f"Dostępna jest wersja {update.tag} ({release_kind}).\n"
            f"Rozmiar pobierania: {size}.\n\n"
            "Czy pobrać aktualizację i ponownie uruchomić program?"
            f"{notes_excerpt}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._prepare_application_update(update)
        elif startup:
            self._begin_catalog_check()
        else:
            self._set_status("Pominięto aktualizację aplikacji")

    def _application_update_check_failed(
        self,
        message: str,
        traceback_text: str,
        *,
        startup: bool,
    ) -> None:
        logging.getLogger(__name__).error(
            "Nie udało się sprawdzić aktualizacji aplikacji:\n%s",
            traceback_text,
        )
        self._set_status(f"Nie sprawdzono aktualizacji aplikacji: {message}")
        if startup:
            self._begin_catalog_check()
        else:
            QMessageBox.warning(self, "Błąd aktualizacji", message)

    def _prepare_application_update(self, update: ApplicationUpdate) -> None:
        self._set_status(f"Pobieranie aktualizacji aplikacji {update.tag}…")

        def work(signals: TaskSignals):
            return self.application_updates.prepare(
                update,
                status=signals.status.emit,
                progress=signals.progress.emit,
            )

        def success(prepared: PreparedApplicationUpdate) -> None:
            if prepared.platform_name == "nt":
                restart_message = (
                    "Program zostanie teraz zamknięty. Osobny helper podmieni plik, "
                    "uruchomi nową wersję i sam zakończy działanie."
                )
            else:
                restart_message = (
                    "Program zostanie teraz zamknięty, zaktualizowany i uruchomiony ponownie."
                )
            QMessageBox.information(
                self,
                "Aktualizacja pobrana",
                f"{restart_message} Ustawienia oraz pobrane mody pozostaną bez zmian.",
            )
            try:
                prepared.apply_and_restart()
            except SelfUpdateError as exc:
                QMessageBox.critical(self, "Błąd aktualizacji", str(exc))
                self._set_status(f"Błąd aktualizacji: {exc}")
                return
            QApplication.instance().quit()

        self._start_task(work, success, name="application-update-prepare")

    def _begin_catalog_check(self) -> None:
        self._set_status("Sprawdzanie wersji oficjalnej listy modów…")

        def work(_signals: TaskSignals):
            return self.catalog_updates.check()

        self._start_task(
            work,
            self._catalog_checked,
            error=self._catalog_check_failed,
            name="catalog-update-check",
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

        self._start_task(work, success, name="catalog-update-install")

    def _begin_release_check(self) -> None:
        self._scan_local()
        channels = {mod.id: self.settings.channel_for(mod.id) for mod in self.mods}
        pinned_versions = {
            mod.id: self.settings.pinned_version_for(mod.id) for mod in self.mods
        }
        self._set_status("Sprawdzanie wydań modów na GitHubie…")

        def work(signals: TaskSignals):
            return self.update_checks.check_all(
                self.mods,
                self.local_mods,
                channels,
                pinned_versions,
                status=signals.status.emit,
            )

        def success(checks: list[UpdateCheck]) -> None:
            self._populate_table(checks)
            errors = sum(1 for check in checks if check.state is UpdateState.ERROR)
            updates = sum(1 for check in checks if check.state in SELECTABLE_STATES)
            if errors:
                self._set_status(f"Znaleziono {updates} pozycji; błędy źródeł: {errors}")
            else:
                self._set_status(f"Znaleziono {updates} pozycji do pobrania lub aktualizacji")

        self._start_task(work, success, name="mod-release-check")

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
            channel.addItem(
                "Automatycznie — stabilne",
                f"channel:{ReleaseChannel.STABLE.value}",
            )
            channel.addItem(
                "Automatycznie — stabilne i testowe",
                f"channel:{ReleaseChannel.PRERELEASE.value}",
            )
            for release in check.available_releases:
                suffix = " (prerelease)" if release.prerelease else ""
                channel.addItem(
                    f"Wersja {release.tag}{suffix}",
                    f"release:{release.tag}",
                )
            channel.addItem(
                "Wyłączone",
                f"channel:{ReleaseChannel.DISABLED.value}",
            )
            selected_channel = self.settings.channel_for(check.mod.id)
            pinned_tag = self.settings.pinned_version_for(check.mod.id)
            if selected_channel is ReleaseChannel.PINNED and pinned_tag:
                selected_data = f"release:{pinned_tag}"
                if channel.findData(selected_data) < 0:
                    channel.insertItem(
                        channel.count() - 1,
                        f"Niedostępna wersja {pinned_tag}",
                        selected_data,
                    )
            else:
                selected_data = f"channel:{selected_channel.value}"
            index = channel.findData(selected_data)
            channel.setCurrentIndex(max(index, 0))
            channel.setEnabled(check.mod.status is ModStatus.ACTIVE)
            channel.currentIndexChanged.connect(
                lambda _index, mod_id=check.mod.id, widget=channel: (
                    self._release_selection_changed(mod_id, widget)
                )
            )
            self.table.setCellWidget(row, 6, channel)

            state_item = QTableWidgetItem(STATE_LABELS[check.state])
            state_item.setToolTip(check.message)
            if check.state in SELECTABLE_STATES:
                state_item.setForeground(QColor("#c75b00"))
            elif check.state is UpdateState.CURRENT:
                state_item.setForeground(QColor("#2e7d32"))
            elif check.state in {UpdateState.ERROR, UpdateState.ARCHIVE_CONFLICT}:
                state_item.setForeground(QColor("#b00020"))
            self.table.setItem(row, 7, state_item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _release_selection_changed(self, mod_id: str, combo: QComboBox) -> None:
        kind, _, value = str(combo.currentData()).partition(":")
        if kind == "release" and value:
            self.settings.set_pinned_version(mod_id, value)
        elif kind == "channel":
            self.settings.set_channel(mod_id, ReleaseChannel(value))
            self.settings.clear_pinned_version(mod_id)
        else:
            return
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
        if check.local:
            ownership = {
                LocalModKind.MANAGED: "zarządzany",
                LocalModKind.UNMANAGED_REPLACEABLE: "oryginalny — możliwy do zastąpienia",
                LocalModKind.ARCHIVE_CONFLICT: "konflikt — podmiana zablokowana",
            }[check.local.kind]
            lines.extend(
                [
                    f"**Autor lokalnego moda:** {check.local.author or '—'}",
                    f"**Tytuł lokalnego moda:** {check.local.title or '—'}",
                    f"**Identyfikacja:** {ownership}",
                ]
            )
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

        replacements = [
            check
            for check in selected
            if check.local
            and check.local.kind is LocalModKind.UNMANAGED_REPLACEABLE
        ]
        if replacements:
            changes = "\n".join(
                f"• {check.mod.name}: {check.local.author or 'nieznany autor'}"
                for check in replacements
                if check.local
            )
            answer = QMessageBox.warning(
                self,
                "Zastąpienie oryginalnego moda",
                "Wybrane pliki mają zgodny tytuł, ale nie są wydaniem StrelokPL:\n\n"
                f"{changes}\n\n"
                "Updater wykona kopię obecnego archiwum, a następnie zastąpi je "
                "wydaniem StrelokPL. Zmiana może wpłynąć na sprzęt w savegame. "
                "Czy kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        downgrades = [
            check
            for check in selected
            if check.local
            and check.local.kind is LocalModKind.MANAGED
            and check.selected_release
            and check.selected_release.version < check.local.version
        ]
        if downgrades:
            changes = "\n".join(
                f"• {check.mod.name}: {check.local.version_text} → "
                f"{check.selected_release.tag}"
                for check in downgrades
                if check.local and check.selected_release
            )
            answer = QMessageBox.warning(
                self,
                "Instalacja starszej wersji",
                "Wybrano zmianę na starszą wersję:\n\n"
                f"{changes}\n\n"
                "Updater wykona kopię obecnego archiwum, ale starszy mod może nie być "
                "zgodny z aktualnym zapisem gry. Czy kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
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

        self._start_task(work, success, name="mod-install")

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

        self._start_task(work, success, name="rollback")

    def _open_log_directory(self) -> None:
        directory = data_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logging.getLogger(__name__).exception("Nie udało się utworzyć folderu logów")
            QMessageBox.warning(self, "Błąd", f"Nie można otworzyć folderu logów:\n{exc}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            QMessageBox.information(
                self,
                "Folder logów",
                f"Nie udało się otworzyć folderu automatycznie.\n\n{directory}",
            )

    def _save_diagnostic_bundle(self) -> None:
        default_target = Path.home() / "StrelokFS25ModUpdater-diagnostyka.zip"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Zapisz pakiet diagnostyczny",
            str(default_target),
            "Archiwum ZIP (*.zip)",
        )
        if not selected:
            return
        target = Path(selected)
        if target.suffix.casefold() != ".zip":
            target = target.with_suffix(".zip")
        try:
            create_diagnostic_bundle(
                target,
                extra={
                    "status": self.status_label.text(),
                    "modsDirectory": self.settings.mods_directory,
                    "catalogVersion": self.catalog.catalog_version,
                    "knownMods": len(self.mods),
                    "activeTasks": [task.name for task in self.active_tasks],
                },
            )
        except OSError as exc:
            logging.getLogger(__name__).exception("Nie udało się zapisać diagnostyki")
            QMessageBox.critical(self, "Błąd zapisu", str(exc))
            return
        logging.getLogger(__name__).info("Zapisano pakiet diagnostyczny target=%s", target)
        QMessageBox.information(
            self,
            "Pakiet diagnostyczny zapisany",
            f"Wyślij testerowi lub autorowi ten plik:\n\n{target}",
        )

    def _start_task(
        self,
        function,
        result,
        *,
        error=None,
        name: str | None = None,
    ) -> None:
        task = Task(function, name=name)
        task.signals.result.connect(result)
        task.signals.error.connect(error or self._task_error)
        task.signals.status.connect(self._set_status)
        task.signals.progress.connect(self._set_progress)
        task.signals.finished.connect(lambda task=task: self._task_finished(task))
        self.active_tasks.add(task)
        self.busy_tasks += 1
        self.progress.setRange(0, 0)
        self._update_busy_state()
        self.thread_pool.start(task)

    def _task_finished(self, task: Task) -> None:
        self.active_tasks.discard(task)
        self.busy_tasks = max(0, self.busy_tasks - 1)
        if self.busy_tasks == 0:
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
            self.app_update_button,
        ):
            button.setEnabled(not busy)
        self.table.setEnabled(not busy)

    def _set_status(self, text: str) -> None:
        logging.getLogger(__name__).info("STATUS %s", text)
        self.status_label.setText(text)

    def _set_progress(self, received: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(min(100, int(received * 100 / total)))
