import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from strelok_fs25_mod_updater.gui import MainWindow
    from strelok_fs25_mod_updater.kingmods_gui import KingModsTab
except ImportError:
    QApplication = None

from strelok_fs25_mod_updater.kingmods import KingMod, KingPage, KingRelease
from strelok_fs25_mod_updater.packs import ModPack
from tests.test_packs import KM, MF


@unittest.skipIf(QApplication is None, "Qt is not installed")
class PackTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(
            os.environ,
            {"LOCALAPPDATA": tmp.name, "XDG_CONFIG_HOME": tmp.name, "XDG_DATA_HOME": tmp.name},
        )
        env.start()
        self.addCleanup(env.stop)
        with patch.object(MainWindow, "_initialise_path"):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        from importlib.resources import files
        import json
        manifests = json.loads(files('strelok_fs25_mod_updater').joinpath(
            'resources/edit_compatibility.json').read_text(encoding='utf-8'))
        metadata = patch.object(self.window.github, 'edit_manifest', side_effect=lambda repo: manifests[repo])
        metadata.start()
        self.addCleanup(metadata.stop)

    def synchronous(self, work, callback, **_kwargs):
        callback(work(Mock()))

    def test_local_lists_are_separate_tabs_duplicate_import_is_not_duplicated(self):
        for number in [1, 2]:
            source = self.root / f"{number}.txt"
            source.write_text("Ta sama nazwa\n" + (KM if number == 1 else MF))
            pack = ModPack(
                str(source), "Ta sama nazwa", [KingMod(KM if number == 1 else MF)], local=True
            )
            with patch.object(KingModsTab, "start"):
                self.window._pack_loaded(pack)
        self.assertEqual(len(self.window.pack_tabs), 4)
        a, b = self.window.pack_tabs[-2:]
        self.assertNotEqual(a.pack.id, b.pack.id)
        self.assertNotEqual(a.mods[0].url, b.mods[0].url)
        self.window._pack_loaded(a.pack)
        self.assertEqual(len(self.window.pack_tabs), 4)
        self.assertIs(self.window.tabs.currentWidget(), a)
        with patch(
            "strelok_fs25_mod_updater.gui.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window._remove_pack()
        self.assertEqual(len(self.window.pack_tabs), 3)
        self.assertTrue(Path(a.pack.source).exists())
        self.assertEqual(len(self.window.pack_store.load()), 3)

    def test_refresh_renames_and_removes_entries_without_merging_other_tabs(self):
        tab = self.window.pack_tabs[0]
        tab.mods = [KingMod(KM)]
        page = KingPage("Test", [KingRelease("", MF)])
        with (
            patch.object(self.window, "_start_task", side_effect=self.synchronous),
            patch.object(tab.pack, "load_text", return_value="Nowa nazwa\n" + MF),
            patch.object(tab.client, "fetch", side_effect=lambda mod: (mod, page)),
        ):
            tab.refresh()
        self.assertEqual(self.window.tabs.tabText(0), "Nowa nazwa")
        self.assertEqual([m.url for m in tab.mods], [MF])
        self.assertEqual(self.window.pack_tabs[1].pack.name, "StrielokPL")
        self.assertEqual(len(self.window.pack_tabs[1].mods), 1)

    def test_invalid_remote_list_keeps_last_valid_pack(self):
        tab = self.window.pack_tabs[0]
        tab.mods = [KingMod(KM)]
        page = KingPage("Test", [KingRelease("1.0.0.0", MF)])
        with (
            patch.object(self.window, "_start_task", side_effect=self.synchronous),
            patch.object(tab.pack, "load_text", return_value="Zła lista\nhttps://evil.org/mod"),
            patch.object(tab.client, "fetch", side_effect=lambda mod: (mod, page)),
        ):
            tab.refresh()
        self.assertEqual(tab.pack.name, "Miziuu")
        self.assertEqual([m.url for m in tab.mods], [KM])
        self.assertIn("feed", tab.errors)
        self.assertIn("poprzednie dane", tab.details.text())

    def test_direct_modsfire_can_open_without_a_remote_version(self):
        tab = self.window.pack_tabs[0]
        mod = KingMod(MF, "Test", "FS25_Test.zip")
        tab.mods = [mod]
        tab.pages[mod.id] = KingPage("Test", [KingRelease("", MF)])
        tab.populate()
        tab.table.selectRow(0)
        self.assertTrue(tab.download_button.isEnabled())
        self.assertTrue(tab.import_button.isEnabled())
        with patch(
            "strelok_fs25_mod_updater.kingmods_gui.QDesktopServices.openUrl", return_value=True
        ) as opened:
            tab.open_download()
            self.assertEqual(opened.call_args.args[0].toString(), MF)
