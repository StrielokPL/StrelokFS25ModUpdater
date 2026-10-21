from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
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
    KingPage,
    KingRelease,
    kingmods_url,
    modsfire_url,
)
from .packs import GitHubMod
from .versioning import ModVersion


class KingModsTab(QWidget):
    """Independent source tab; uses the host's shared directory and background task runner."""

    def __init__(self, host, pack):
        super().__init__(host)
        self.host = host
        self.client = KingModsClient()
        self.pack = pack
        self.mods = list(pack.mods)
        self.removed = False
        self.pages = {}
        self.errors = {}
        self.selections = {}
        self.row_mods = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton("Sprawdź wersje")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        self.source_label = QLabel(pack.source)
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        toolbar.addWidget(self.source_label, 1)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Pokaż:"))
        self.filter = QComboBox()
        self.filter.addItems(["Wszystkie", "Zainstalowane", "Niezainstalowane"])
        self.filter.currentIndexChanged.connect(self.populate)
        filters.addWidget(self.filter)
        self.watch = QCheckBox("Sprawdzaj co 15 minut")
        self.watch.setChecked(pack.watch)
        self.watch.toggled.connect(self.save_watch)
        filters.addWidget(self.watch)
        filters.addStretch()
        layout.addLayout(filters)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Mod",
                "Zainstalowana",
                "Najnowsza",
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
        self.page_button = QPushButton("Strona moda")
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
        self.details.setTextFormat(Qt.TextFormat.PlainText)
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
        if self.removed or not self.watch.isChecked():
            return
        if self.host.busy_tasks:
            QTimer.singleShot(5000, self.poll)
            return
        self.refresh()

    def save_watch(self, checked):
        self.pack.watch = checked
        self.host.save_packs()

    def linked_edit(self, mod):
        if isinstance(mod, GitHubMod):
            return None
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
            local = self.host.local_mods.get(mod.id) if isinstance(mod, GitHubMod) else None
            local = local or inspect_mod_archive(
                mod.id, target, catalog_mod=mod.catalog if isinstance(mod, GitHubMod) else None
            )
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
            if is_edit and not isinstance(mod, GitHubMod):
                state = "Zainstalowany edit StrelokPL"
            elif page and page.releases and page.releases[0].version and local:
                latest = ModVersion.parse(page.releases[0].version)
                state = (
                    "Aktualizacja"
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
                (page.releases[0].version or "Wersja z ZIP-a") if page else "—",
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
                    combo.addItem(
                        release.version or "Plik ModsFire — wersja z ZIP-a", release.version
                    )
                prior = self.selections.get(mod.id, "")
                index = combo.findData(prior)
                if prior and index < 0:
                    combo.addItem(f"{prior} — niedostępna", prior)
                    index = combo.count() - 1
                combo.setCurrentIndex(max(0, index))
                self.selections[mod.id] = combo.currentData()
            if (
                isinstance(mod, GitHubMod)
                and local
                and _is_strielokpl_author(local.author)
                and self.host.installer.find_original_backup(mod.catalog)
            ):
                combo.addItem("Przywróć oryginalny mod…", "__restore__")
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
        if combo.currentData() == "__restore__" and isinstance(mod, GitHubMod):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(self.selections.get(mod.id, ""))))
            combo.blockSignals(False)
            QTimer.singleShot(0, lambda: self.host._restore_original(mod.id))
            return
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
        self.import_button.setEnabled(
            bool(mod and not isinstance(mod, GitHubMod) and self.release(mod) and mod.archive)
        )
        self.download_button.setText(
            "Pobierz / zainstaluj z GitHuba"
            if isinstance(mod, GitHubMod)
            else "Otwórz wybraną wersję na ModsFire"
        )
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
            self.details.setText("Wybierz mod z tej paczki.")

    def set_busy(self, busy):
        self.setEnabled(not busy)

    def refresh(self):
        if self.host.busy_tasks or self.removed:
            return
        mods = list(self.mods)

        def work(signals):
            entries, name, errors = mods, self.pack.name, {}
            try:
                name, entries = self.pack.parse(self.pack.load_text(self.client))
                # The source list is authoritative. Preserve only resolved display metadata.
                old = {m.id: m for m in mods}
                entries = [
                    replace(
                        m, name=m.name or old[m.id].name, archive=m.archive or old[m.id].archive
                    )
                    if isinstance(m, KingMod) and m.id in old
                    else m
                    for m in entries
                ]
            except (ValueError, OSError) as exc:
                errors["feed"] = str(exc)
            pages, updated = {}, []
            for index, mod in enumerate(entries, 1):
                signals.status.emit(f"{name} {index}/{len(entries)}: {mod.name or mod.url}")
                try:
                    if isinstance(mod, GitHubMod):
                        releases = self.host.github.releases_for_mod(mod.catalog)
                        releases.sort(key=lambda r: r.version, reverse=True)
                        if not releases:
                            raise ValueError("Brak publicznych wydań z paczką ZIP")
                        page = KingPage(
                            mod.name, [KingRelease(r.tag, r.download_url, r) for r in releases]
                        )
                    else:
                        mod, page = self.client.fetch(mod)
                    pages[mod.id] = page
                except Exception as exc:
                    errors[mod.id] = str(exc)
                    logging.getLogger(__name__).warning("PACK %s: %s", mod.url, exc)
                updated.append(mod)
            return name, updated, pages, errors

        def success(result):
            if self.removed:
                return
            self.pack.name, self.mods, pages, self.errors = result
            self.pack.mods = self.mods
            ids = {m.id for m in self.mods}
            self.pages = {key: value for key, value in self.pages.items() if key in ids}
            self.pages.update(pages)
            self.host.save_packs()
            self.host.tabs.setTabText(self.host.tabs.indexOf(self), self.pack.name)
            self.host._reload_mod_list()
            self.host._scan_local()
            self.host._set_status(
                f"{self.pack.name}: sprawdzono {len(pages)}/{len(self.mods)}; "
                f"błędy: {len(self.errors)}"
                + (f". Lista: {self.errors['feed']}" if "feed" in self.errors else "")
            )
            if "feed" in self.errors:
                self.details.setText(
                    "Nie odświeżono listy; pokazano poprzednie dane.\n" + self.errors["feed"]
                )

        self.host._start_task(work, success, name="pack-check")

    def open_url(self, url):
        # Validate immediately before handing a URL to the OS/browser.
        mod = self.selected()
        if isinstance(mod, GitHubMod) and url == mod.url:
            pass  # This object can only originate from the exact trusted official list.
        else:
            try:
                url = kingmods_url(url)
            except ValueError:
                url = modsfire_url(url)
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(self, "Link", f"Otwórz adres w przeglądarce:\n{url}")

    def open_download(self):
        mod = self.selected()
        release = self.release(mod) if mod else None
        if release:
            if isinstance(mod, GitHubMod):
                self.install_github(mod, release)
            else:
                self.open_url(modsfire_url(release.url))

    def open_page(self):
        mod = self.selected()
        if mod:
            self.open_url(mod.url)

    def open_edit(self):
        mod = self.selected()
        edit = self.linked_edit(mod) if mod else None
        if edit:
            for tab in self.host.pack_tabs:
                for row, entry in tab.row_mods.items():
                    if entry.id == edit.id:
                        self.host.tabs.setCurrentWidget(tab)
                        tab.table.selectRow(row)
                        return

    def install_github(self, mod, release):
        directory = self.host._mods_directory()
        if directory is None or not directory.is_dir():
            QMessageBox.warning(self, "Folder modów", "Najpierw wskaż folder modów.")
            return
        if release.github_release is None:
            return
        local, error = self.local(mod)
        if error:
            QMessageBox.warning(self, "Konflikt archiwum", error)
            return
        if (
            local
            and _is_strielokpl_author(local.author)
            and release.github_release.version < local.version
        ):
            answer = QMessageBox.warning(
                self,
                "Starsza wersja moda",
                "Wybrano starszą wersję. Może nie być zgodna z aktualnym zapisem gry. Kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        backup = True
        if (directory / mod.archive).exists():
            answer = QMessageBox.question(
                self,
                "Kopia poprzedniego moda",
                f"Zastąpić {mod.name} wersją {release.version or 'odczytaną z ZIP-a'}?\n"
                "Czy zachować kopię obecnego moda?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            backup = answer == QMessageBox.StandardButton.Yes
        else:
            if (
                QMessageBox.question(
                    self,
                    "Instalacja",
                    f"Pobrać {mod.name} {release.version}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return

        def work(signals):
            return self.host.installer.install(
                mod.catalog,
                release.github_release,
                directory,
                backup_existing=backup,
                status=signals.status.emit,
                progress=signals.progress.emit,
            )

        def success(_event):
            self.host._scan_local()
            QMessageBox.information(self, "Zainstalowano", f"{mod.name} {release.version}")

        self.host._start_task(work, success, name="pack-github-install")

    def import_zip(self):
        mod = self.selected()
        release = self.release(mod) if mod else None
        directory = self.host._mods_directory()
        if not mod or not release or isinstance(mod, GitHubMod):
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
                f"Zastąpić {mod.archive} wersją {release.version or 'odczytaną z ZIP-a'}?\n\n"
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
