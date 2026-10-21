from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .fs25 import _is_strielokpl_author, inspect_mod_archive
from .kingmods import (
    KingMod,
    KingModsClient,
    KingModsStore,
    github_list_url,
    modsfire_url,
    parse_watch_list,
)
from .versioning import ModVersion


class KingModsTab(QWidget):
    """Independent source tab; uses the host's shared directory and background task runner."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.client = KingModsClient()
        self.store = KingModsStore()
        self.mods, self.feed = self.store.load()
        self.pages = {}
        self.errors = {}
        self.selections = {}
        self.row_mods = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton("Sprawdź wersje")
        self.refresh_button.clicked.connect(self.refresh)
        self.add_button = QPushButton("Dodaj link KingMods…")
        self.add_button.clicked.connect(self.add_link)
        self.feed_button = QPushButton("Importuj listę z GitHuba…")
        self.feed_button.clicked.connect(self.import_feed)
        self.remove_button = QPushButton("Usuń z obserwowanych")
        self.remove_button.clicked.connect(self.remove_selected)
        for button in (self.refresh_button, self.add_button, self.feed_button, self.remove_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Pokaż:"))
        self.filter = QComboBox()
        self.filter.addItems(["Wszystkie", "Zainstalowane", "Niezainstalowane"])
        self.filter.currentIndexChanged.connect(self.populate)
        filters.addWidget(self.filter)
        self.watch = QCheckBox("Sprawdzaj co 15 minut")
        self.watch.setChecked(True)
        filters.addWidget(self.watch)
        filters.addStretch()
        layout.addLayout(filters)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Mod",
                "Zainstalowana",
                "Najnowsza na KingMods",
                "Wersja do pobrania",
                "Edit StrelokPL",
                "Stan",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.show_details)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.download_button = QPushButton("Otwórz wybraną wersję na ModsFire")
        self.download_button.clicked.connect(self.open_download)
        self.import_button = QPushButton("Wskaż pobrany ZIP i zainstaluj…")
        self.import_button.clicked.connect(self.import_zip)
        self.page_button = QPushButton("Strona KingMods")
        self.page_button.clicked.connect(self.open_page)
        self.edit_button = QPushButton("Przejdź do mojego editu")
        self.edit_button.clicked.connect(self.open_edit)
        for button in (
            self.download_button,
            self.import_button,
            self.page_button,
            self.edit_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.details = QLabel("Dodaj obserwowane mody linkiem lub importuj listę z GitHuba.")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.setInterval(15 * 60 * 1000)
        self.timer.timeout.connect(self.poll)
        self.populate()

    def start(self):
        self.timer.start()
        QTimer.singleShot(750, self.poll)

    def poll(self):
        if not self.watch.isChecked():
            return
        if self.host.busy_tasks:
            QTimer.singleShot(5000, self.poll)
            return
        self.refresh()

    def linked_edit(self, mod):
        return next(
            (
                item
                for item in self.host.mods
                if (mod.edit_id and item.id == mod.edit_id)
                or (
                    mod.archive
                    and item.archive_name.casefold() == mod.archive.casefold()
                    and item.id.startswith("strelokpl.")
                )
            ),
            None,
        )

    def local(self, mod):
        directory = self.host._mods_directory()
        if directory is None or not mod.archive:
            return None, ""
        target = directory / mod.archive
        if not target.exists():
            return None, ""
        try:
            local = inspect_mod_archive(mod.id, target)
            if mod.titles and local.title.casefold() not in {t.casefold() for t in mod.titles}:
                return None, "Konflikt: nazwa ZIP pasuje, tytuł moda jest inny"
            return local, ""
        except (OSError, ValueError) as exc:
            return None, str(exc)

    def populate(self):
        selected = self.selected()
        selected_id = selected.id if selected else ""
        self.table.setRowCount(0)
        self.row_mods = {}
        for mod in self.mods:
            local, local_error = self.local(mod)
            installed = bool(local or local_error)
            if self.filter.currentIndex() == 1 and not installed:
                continue
            if self.filter.currentIndex() == 2 and installed:
                continue
            page = self.pages.get(mod.id)
            edit = self.linked_edit(mod)
            is_edit = bool(local and _is_strielokpl_author(local.author))
            state = "Niezainstalowany" if not installed else "Zainstalowany"
            if is_edit:
                state = "Zainstalowany edit StrelokPL"
            elif page and local:
                latest = ModVersion.parse(page.releases[0].version)
                state = (
                    "Aktualizacja oryginału"
                    if latest > local.version
                    else "Aktualny"
                    if latest == local.version
                    else "Lokalny nowszy"
                )
            if local_error:
                state = "Konflikt / uszkodzony ZIP"
            elif mod.id in self.errors:
                state += " — nie sprawdzono strony"
            elif not page:
                state += " — wersja online niesprawdzona"
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.row_mods[row] = mod
            values = [
                mod.name or mod.url,
                local.version_text if local else "—",
                page.releases[0].version if page else "—",
                "",
                "Tak" if edit else "—",
                state,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(local_error or self.errors.get(mod.id, "") or value)
                self.table.setItem(row, column, item)
            combo = QComboBox()
            if page:
                for release in page.releases:
                    combo.addItem(release.version, release.version)
                prior = self.selections.get(mod.id, "")
                index = combo.findData(prior)
                if prior and index < 0:
                    combo.addItem(f"{prior} — niedostępna", prior)
                    index = combo.count() - 1
                combo.setCurrentIndex(max(0, index))
                self.selections[mod.id] = combo.currentData()
            combo.currentIndexChanged.connect(
                lambda _index, m=mod, c=combo: self.select_version(m, c)
            )
            self.table.setCellWidget(row, 3, combo)
            if mod.id == selected_id:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.show_details()

    def select_version(self, mod, combo):
        self.selections[mod.id] = combo.currentData()
        self.show_details()

    def selected(self):
        return self.row_mods.get(self.table.currentRow()) if hasattr(self, "table") else None

    def release(self, mod):
        page = self.pages.get(mod.id)
        return (
            next((r for r in page.releases if r.version == self.selections.get(mod.id)), None)
            if page
            else None
        )

    def show_details(self):
        if not hasattr(self, "details"):
            return
        mod = self.selected()
        self.download_button.setEnabled(bool(mod and self.release(mod)))
        self.import_button.setEnabled(bool(mod and self.release(mod) and mod.archive))
        self.edit_button.setEnabled(bool(mod and self.linked_edit(mod)))
        if mod:
            self.details.setText(
                f"{mod.name or mod.url}\n{mod.url}\n"
                f"Archiwum: {mod.archive or 'nazwa zostanie odczytana z ModsFire'}\n"
                + self.errors.get(mod.id, "")
                + "\nWskaż ZIP pobrany z wybranej wersji. O kopię poprzedniego moda zapytamy "
                "przed podmianą. Po instalacji pobrany plik zostanie przeniesiony do folderu modów."
            )
        else:
            self.details.setText("Wybierz mod. Lista zawiera obserwowane strony KingMods.")

    def set_busy(self, busy):
        self.setEnabled(not busy)

    @staticmethod
    def merge(existing, incoming):
        result = {m.id: m for m in existing}
        for mod in incoming:
            previous = result.get(mod.id)
            if previous:
                mod = replace(
                    mod,
                    name=mod.name or previous.name,
                    archive=mod.archive or previous.archive,
                    titles=mod.titles or previous.titles,
                    edit_id=mod.edit_id or previous.edit_id,
                )
            result[mod.id] = mod
        return list(result.values())

    def refresh(self):
        if self.host.busy_tasks:
            return
        mods, feed = list(self.mods), self.feed

        def work(signals):
            entries = mods
            errors = {}
            if feed:
                try:
                    entries = self.merge(
                        entries, parse_watch_list(self.client.read(github_list_url(feed)))
                    )
                except (ValueError, OSError) as exc:
                    errors["feed"] = str(exc)
            pages, updated = {}, []
            for index, mod in enumerate(entries, 1):
                signals.status.emit(f"KingMods {index}/{len(entries)}: {mod.name or mod.url}")
                try:
                    mod, page = self.client.fetch(mod)
                    pages[mod.id] = page
                except (ValueError, OSError) as exc:
                    errors[mod.id] = str(exc)
                    logging.getLogger(__name__).warning("KINGMODS %s: %s", mod.url, exc)
                updated.append(mod)
            return updated, pages, errors

        def success(result):
            self.mods, pages, self.errors = result
            self.pages.update(pages)
            self.store.save(self.mods, self.feed)
            self.populate()
            self.host._set_status(
                f"KingMods: sprawdzono {len(pages)}/{len(self.mods)}; "
                f"błędy: {len(self.errors)}"
                + (f". Katalog GitHub: {self.errors['feed']}" if "feed" in self.errors else "")
            )

        self.host._start_task(work, success, name="kingmods-check")

    def add_link(self):
        url, ok = QInputDialog.getText(self, "Obserwuj mod", "Link do moda FS25 na KingMods:")
        if not ok or not url.strip():
            return
        try:
            mod = KingMod(url)
        except ValueError as exc:
            QMessageBox.warning(self, "Nieprawidłowy link", str(exc))
            return
        self.mods = self.merge(self.mods, [mod])
        self.store.save(self.mods, self.feed)
        self.populate()
        self.refresh()

    def import_feed(self):
        url, ok = QInputDialog.getText(
            self,
            "Katalog linków z GitHuba",
            "Publiczny plik TXT (jeden link KingMods na linię) lub JSON.\n"
            "Zostanie zapamiętany i sprawdzany razem z wersjami:",
            text=self.feed,
        )
        if not ok:
            return
        try:
            feed = github_list_url(url)
        except ValueError as exc:
            QMessageBox.warning(self, "Nieprawidłowy katalog", str(exc))
            return

        def work(_signals):
            return parse_watch_list(self.client.read(feed))

        def success(mods):
            self.mods = self.merge(self.mods, mods)
            self.feed = feed
            self.store.save(self.mods, self.feed)
            self.populate()
            self.host._set_status(f"Zaimportowano {len(mods)} linków KingMods")
            QTimer.singleShot(100, self.refresh)

        self.host._start_task(work, success, name="kingmods-feed")

    def remove_selected(self):
        mod = self.selected()
        if not mod:
            return
        answer = QMessageBox.question(
            self,
            "Usuń obserwację",
            f"Usunąć {mod.name or mod.url} z listy? Plik moda pozostanie bez zmian.\n"
            "Jeśli wpis pochodzi z katalogu GitHub, wróci przy jego odświeżeniu.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.mods = [m for m in self.mods if m.id != mod.id]
            self.store.save(self.mods, self.feed)
            self.populate()

    def open_url(self, url):
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(self, "Link", f"Otwórz adres w przeglądarce:\n{url}")

    def open_download(self):
        mod = self.selected()
        release = self.release(mod) if mod else None
        if release:
            self.open_url(modsfire_url(release.url))

    def open_page(self):
        mod = self.selected()
        if mod:
            self.open_url(mod.url)

    def open_edit(self):
        mod = self.selected()
        edit = self.linked_edit(mod) if mod else None
        if edit:
            self.host.tabs.setCurrentWidget(self.host.github_tab)
            for row, mod_id in self.host.row_ids.items():
                if mod_id == edit.id:
                    self.host.table.selectRow(row)
                    break

    def import_zip(self):
        mod = self.selected()
        release = self.release(mod) if mod else None
        directory = self.host._mods_directory()
        if not mod or not release:
            return
        if directory is None or not directory.is_dir():
            QMessageBox.warning(self, "Folder modów", "Najpierw wskaż istniejący folder modów.")
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Wskaż pobrany mod", "", "Archiwum ZIP (*.zip)"
        )
        if not source:
            return
        target = directory / mod.archive
        backup = False
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Kopia poprzedniego moda",
                f"Zastąpić {mod.archive} wersją {release.version}?\n\n"
                "Czy wykonać kopię poprzedniego moda?\n"
                "Tak — zachowaj kopię.\nNie — zastąp bez kopii.\nAnuluj — nic nie zmieniaj.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            backup = answer == QMessageBox.StandardButton.Yes
        else:
            answer = QMessageBox.question(
                self,
                "Instalacja moda",
                f"Przenieść pobrany ZIP {mod.name} {release.version} do:\n{directory}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        edit = self.linked_edit(mod)
        if edit:
            mod = replace(mod, edit_id=edit.id)

        def work(signals):
            return self.host.installer.install_local(
                mod,
                release.version,
                Path(source),
                directory,
                backup=backup,
                status=signals.status.emit,
            )

        def success(event):
            self.host._scan_local()
            self.populate()
            message = f"Zainstalowano {mod.name} {release.version}."
            if event.get("backupDirectory"):
                message += f"\nKopia: {event['backupDirectory']}"
            if event.get("sourceRetained"):
                message += (
                    "\nInstalacja zakończona, ale pobrany plik pozostał w folderze pobierania."
                )
            if event.get("historyWarning"):
                message += "\nNie udało się zapisać historii operacji — sprawdź log."
            QMessageBox.information(self, "Zainstalowano mod", message)

        self.host._start_task(work, success, name="kingmods-import")
