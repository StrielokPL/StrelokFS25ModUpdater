from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
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

from .compatibility import EDIT_REPOSITORIES, CompatibilityState, EditCompatibility
from .fs25 import _is_strielokpl_author, inspect_mod_archive
from .kingmods import (
    KingMod,
    KingModsClient,
    KingPage,
    KingRelease,
    kingmods_url,
    modsfire_url,
)
from .packs import EditMod, GitHubMod
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
        self.manifests = {}
        self.errors = {}
        self.selections = {}
        self.row_mods = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton("Odśwież listę i wersje")
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
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Mod",
                "Zainstalowana",
                "Najnowsza",
                "Wersja do pobrania",
                "Edit StrelokPL",
                "Stan",
                "Zgodność wyboru",
            ]
        )
        self.table.horizontalHeader().moveSection(6, 4)
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
        if isinstance(mod, (GitHubMod, EditMod)):
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

    def compatibility_profile(self, mod):
        return (
            self.host.compatibility_profiles.get(
                mod.base_id if isinstance(mod, EditMod) else mod.id
            )
            if not isinstance(mod, GitHubMod)
            else None
        )

    def assessment(self, mod, version=None):
        profile = self.compatibility_profile(mod)
        version = version if version is not None else self.selections.get(mod.id)
        if not profile or not version:
            return None
        return profile.assess(profile.source_version if isinstance(mod, EditMod) else version)

    def installed_assessment(self, mod, local):
        profile = self.compatibility_profile(mod)
        if not profile or not local or _is_strielokpl_author(local.author):
            return None
        if local.version == ModVersion.parse(profile.source_xml_version):
            return profile.assess(profile.source_version)
        # A mismatched XML/site numbering cannot be extrapolated to unlisted releases.
        if profile.source_xml_version != profile.source_version:
            return None
        return profile.assess(local.version_text)

    def update_compatibility_cell(self, mod):
        row = next((row for row, entry in self.row_mods.items() if entry.id == mod.id), None)
        if row is None:
            return
        profile = self.compatibility_profile(mod)
        assessment = self.assessment(mod)
        label = assessment.label if assessment else ("Brak oceny" if profile else "—")
        item = QTableWidgetItem(label)
        item.setToolTip(
            (
                assessment.notice
                if assessment
                else "Nie porównano tej wersji z bazą editu. Zalecana jest wersja źródłowa."
            )
            + (
                f"\nEdit: {profile.edit_version}; baza: {profile.source_version}."
                if profile
                else ""
            )
        )
        if assessment:
            color = (
                "#c75b00"
                if assessment.state is CompatibilityState.INCOMPATIBLE
                else "#2e7d32"
                if assessment.state is CompatibilityState.SOURCE
                else "#4b80bb"
            )
            item.setForeground(QColor(color))
        if isinstance(mod, EditMod) and profile:
            item.setText("Baza: " + profile.source_version)
        self.table.setItem(row, 6, item)

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
            profile = self.compatibility_profile(mod)
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
                "Tak" if edit or profile else "—",
                state,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(local_error or self.errors.get(mod.id, "") or value)
                self.table.setItem(row, column, item)
            installed_assessment = self.installed_assessment(mod, local)
            if installed_assessment:
                self.table.item(row, 1).setToolTip(
                    "Zainstalowany oryginał: "
                    + installed_assessment.label
                    + "\nOcena według numeru wersji. "
                    + installed_assessment.notice
                )
                if installed_assessment.state is CompatibilityState.INCOMPATIBLE:
                    self.table.item(row, 1).setForeground(QColor("#c75b00"))
            if profile and not isinstance(mod, EditMod) and page and page.releases[0].version:
                latest_assessment = self.assessment(mod, page.releases[0].version)
                if latest_assessment:
                    self.table.item(row, 2).setToolTip(
                        latest_assessment.label + "\n" + latest_assessment.notice
                    )
            combo = QComboBox()
            if page:
                for release in page.releases:
                    assessment = self.assessment(mod, release.version) if release.version else None
                    label = release.version or "Plik ModsFire — wersja z ZIP-a"
                    if profile and not isinstance(mod, EditMod):
                        label += " — " + (assessment.label if assessment else "Brak oceny")
                    combo.addItem(label, release.version)
                    if assessment:
                        combo.setItemData(
                            combo.count() - 1, assessment.notice, Qt.ItemDataRole.ToolTipRole
                        )
                prior = self.selections.get(
                    mod.id,
                    profile.source_version if profile and not isinstance(mod, EditMod) else "",
                )
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
            if isinstance(mod, EditMod) and local and is_edit:
                from .overlay import find_original_backup

                if find_original_backup(self.host.installer, mod):
                    combo.addItem("Przywróć oryginalny mod…", "__restore__")
            combo.currentIndexChanged.connect(
                lambda _index, m=mod, c=combo: self.select_version(m, c)
            )
            self.table.setCellWidget(row, 3, combo)
            self.update_compatibility_cell(mod)
            if mod.id == selected_id:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, min(190, self.table.columnWidth(0)))
        self.table.setColumnWidth(3, 255)
        self.table.setColumnWidth(6, 195)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.show_details()

    def select_version(self, mod, combo):
        if combo.currentData() == "__restore__" and isinstance(mod, (GitHubMod, EditMod)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(self.selections.get(mod.id, ""))))
            combo.blockSignals(False)
            if isinstance(mod, EditMod):
                QTimer.singleShot(0, lambda: self.restore_edit_base(mod))
            else:
                QTimer.singleShot(0, lambda: self.host._restore_original(mod.id))
            return
        self.selections[mod.id] = combo.currentData()
        self.update_compatibility_cell(mod)
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
        self.import_button.setText(
            "Zainstaluj edit na oryginalnym ZIP-ie…"
            if isinstance(mod, EditMod)
            else "Wskaż pobrany ZIP i zainstaluj…"
        )
        self.download_button.setText(
            "Pobierz zalecaną bazę z ModsFire"
            if isinstance(mod, EditMod)
            else "Pobierz / zainstaluj z GitHuba"
            if isinstance(mod, GitHubMod)
            else "Otwórz wybraną wersję na ModsFire"
        )
        self.edit_button.setEnabled(
            bool(mod and (self.linked_edit(mod) or self.compatibility_profile(mod)))
        )
        self.edit_button.setText(
            "Strona editu"
            if mod and self.compatibility_profile(mod) and not self.linked_edit(mod)
            else "Przejdź do mojego editu"
        )
        if mod:
            self.details.setText(
                f"{mod.name or mod.url}\n{mod.url}\n"
                f"Archiwum: {mod.archive or 'nazwa zostanie odczytana z ModsFire'}\n"
                + self.errors.get(mod.id, "")
                + "\nWskaż ZIP pobrany z wybranej wersji. O kopię poprzedniego moda zapytamy "
                "przed podmianą. Po instalacji pobrany plik zostanie przeniesiony do folderu modów."
            )
            profile = self.compatibility_profile(mod)
            if isinstance(mod, EditMod):
                self.details.setText(
                    f"{mod.name}\n{mod.url}\n"
                    "Edit zawiera tylko zmienione pliki. Wskaż oryginalny ZIP pobrany od autora "
                    "lub użyj zainstalowanego oryginału. ZIP wskazany spoza folderu modów "
                    "pozostanie zachowany.\n"
                    + self.errors.get(mod.id, "")
                )
            if profile:
                assessment = self.assessment(mod)
                description = (
                    assessment.label + ": " + assessment.notice
                    if assessment
                    else "Brak oceny tej wersji. Zalecana jest wersja źródłowa."
                )
                self.details.setText(
                    self.details.text() + f"\nEdit {profile.edit_version}: "
                    f"baza źródłowa {profile.source_version}.\n" + description
                )
                local, _error = self.local(mod)
                installed_assessment = self.installed_assessment(mod, local)
                if installed_assessment:
                    self.details.setText(
                        self.details.text()
                        + "\nZainstalowany oryginał: "
                        + installed_assessment.label
                    )
                if "compatibility:" + mod.id in self.errors:
                    self.details.setText(
                        self.details.text() + "\nNie odświeżono oceny z repozytorium; "
                        "pokazano ostatnie lub wbudowane dane."
                    )
        else:
            self.details.setText("Wybierz mod z tej paczki.")

    def set_busy(self, busy):
        self.setEnabled(not busy)

    def refresh(self):
        if self.host.busy_tasks or self.removed:
            return
        mods = list(self.mods)
        # Manual checks must not reuse the five-minute HTTP cache.
        self.client.cache.clear()
        self.host.github._cache.clear()

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
            pages, updated, profiles, manifests = {}, [], {}, {}
            for index, mod in enumerate(entries, 1):
                signals.status.emit(f"{name} {index}/{len(entries)}: {mod.name or mod.url}")
                try:
                    if isinstance(mod, EditMod):
                        manifest = self.host.github.edit_manifest(mod.repository)
                        profile = EditCompatibility.from_manifest(manifest, mod.repository)
                        if (
                            manifest.get("packageType") != "file-overlay"
                            or manifest.get("archiveName") != mod.archive
                        ):
                            raise ValueError("Nieprawidłowa paczka editu")
                        page = KingPage(
                            mod.name,
                            [
                                KingRelease(
                                    profile.edit_version,
                                    modsfire_url(manifest["baseMod"]["downloadPage"]),
                                )
                            ],
                        )
                        profiles[mod.base_id] = profile
                        manifests[mod.id] = manifest
                    elif isinstance(mod, GitHubMod):
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
                repository = EDIT_REPOSITORIES.get(mod.id)
                if repository:
                    try:
                        profiles[mod.id] = EditCompatibility.from_manifest(
                            self.host.github.edit_manifest(repository), repository
                        )
                    except Exception as exc:
                        errors["compatibility:" + mod.id] = str(exc)
                        logging.getLogger(__name__).warning(
                            "EDIT COMPATIBILITY %s: %s", repository, exc
                        )
                updated.append(mod)
            return name, updated, pages, errors, profiles, manifests

        def success(result):
            if self.removed:
                return
            self.pack.name, self.mods, pages, self.errors, profiles, manifests = result
            self.manifests = manifests
            self.host.compatibility_profiles.update(profiles)
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
        profile = self.compatibility_profile(mod) if mod else None
        if profile and url == "https://github.com/" + EDIT_REPOSITORIES.get(mod.id, ""):
            pass
        elif isinstance(mod, (GitHubMod, EditMod)) and url == mod.url:
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
        elif mod and self.compatibility_profile(mod):
            self.open_url("https://github.com/" + EDIT_REPOSITORIES[mod.id])

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
        if isinstance(mod, EditMod):
            self.install_edit(mod)
            return
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

    def install_edit(self, mod):
        from .fs25 import sha256_file
        from .overlay import base_assessment, install_overlay

        manifest = self.manifests.get(mod.id)
        directory = self.host._mods_directory()
        if manifest is None:
            QMessageBox.warning(self, "Edit", "Najpierw odśwież listę i wersje.")
            return
        if directory is None or not directory.is_dir():
            QMessageBox.warning(self, "Folder modów", "Najpierw wskaż istniejący folder modów.")
            return
        target = directory / mod.archive
        source = None
        if target.exists():
            try:
                local = inspect_mod_archive(mod.id, target)
                if not _is_strielokpl_author(local.author):
                    answer = QMessageBox.question(
                        self,
                        "Oryginalny mod",
                        "Użyć oryginału znajdującego się w folderze modów?\n"
                        "Nie — wskaż inny oryginalny ZIP.",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                        | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes,
                    )
                    if answer == QMessageBox.StandardButton.Cancel:
                        return
                    if answer == QMessageBox.StandardButton.Yes:
                        source = target
            except (OSError, ValueError):
                pass
        if source is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Wskaż oryginalny ZIP autora (nie edit)", "", "Archiwum ZIP (*.zip)"
            )
            if not path:
                return
            source = Path(path)
        try:
            local, assessment = base_assessment(mod, manifest, source)
            base_hash = sha256_file(source)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Nieprawidłowa baza", str(exc))
            return
        profile = self.compatibility_profile(mod)
        mismatch = base_hash != manifest["baseMod"]["sha256"]
        notice = assessment.notice if assessment else "Brak oceny zgodności tej wersji."
        warning = (
            assessment is None or assessment.state is not CompatibilityState.SOURCE or mismatch
        )
        if warning:
            message = (
                f"Oryginał: {local.version_text}. Zalecana baza: {profile.source_version}.\n"
                f"{assessment.label if assessment else 'Brak oceny'}\n{notice}"
            )
            if mismatch:
                message += "\nSuma ZIP-a różni się od źródłowej paczki."
            answer = QMessageBox.warning(
                self,
                "Zgodność bazy editu",
                message + "\n\nCzy mimo to kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        backup = False
        if target.exists():
            answer = QMessageBox.question(
                self,
                "Kopia poprzedniego moda",
                "Czy zachować kopię obecnego moda przed instalacją editu?\n"
                "Tak — wykonaj kopię. Nie — zastąp bez kopii. Anuluj — przerwij.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            backup = answer == QMessageBox.StandardButton.Yes
        elif (
            QMessageBox.question(
                self,
                "Instalacja editu",
                f"Zainstalować {mod.name} {manifest['version']}?\n"
                f"Baza pozostanie zachowana: {source}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def work(signals):
            return install_overlay(
                self.host.installer,
                mod,
                manifest,
                source,
                directory,
                backup=backup,
                allow_mismatch=warning,
                expected_base_hash=base_hash,
                status=signals.status.emit,
                progress=signals.progress.emit,
            )

        def success(event):
            self.host._scan_local()
            for tab in self.host.pack_tabs:
                tab.populate()
            message = f"Zainstalowano {mod.name} {manifest['version']}."
            if event.get("backupDirectory"):
                message += "\nKopia: " + event["backupDirectory"]
            if event.get("historyWarning"):
                message += "\nNie udało się zapisać historii — sprawdź log."
            QMessageBox.information(self, "Zainstalowano edit", message)

        self.host._start_task(work, success, name="file-overlay-install")

    def restore_edit_base(self, mod):
        from .overlay import restore_original

        directory = self.host._mods_directory()
        if directory is None or not directory.is_dir():
            return
        answer = QMessageBox.question(
            self,
            "Przywracanie oryginału",
            "Przywrócić oryginalny mod? Czy zachować kopię obecnego editu?\n"
            "Tak — z kopią. Nie — bez kopii. Anuluj — przerwij.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return

        def work(_signals):
            return restore_original(
                self.host.installer, mod, directory, backup=answer == QMessageBox.StandardButton.Yes
            )

        def success(_event):
            self.host._scan_local()
            for tab in self.host.pack_tabs:
                tab.populate()
            QMessageBox.information(self, "Oryginał", "Przywrócono oryginalny mod.")

        self.host._start_task(work, success, name="overlay-restore-original")
