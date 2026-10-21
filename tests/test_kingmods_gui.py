import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    from strelok_fs25_mod_updater.gui import MainWindow
except ImportError:
    QApplication = None

from strelok_fs25_mod_updater.kingmods import parse_page, DEFAULT_MODS
from tests.helpers import make_mod_zip
from tests.test_kingmods import HTML


@unittest.skipIf(QApplication is None, 'Qt is not installed')
class KingModsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {
            'LOCALAPPDATA': tmp.name, 'XDG_CONFIG_HOME': tmp.name, 'XDG_DATA_HOME': tmp.name})
        env.start()
        self.addCleanup(env.stop)
        with patch.object(MainWindow, '_initialise_path'):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.tab = self.window.pack_tabs[0]
        self.tab.mods = list(DEFAULT_MODS)
        self.tab.pack.mods = self.tab.mods
        self.mod = self.tab.mods[0]
        self.window.settings.mods_directory = tmp.name
        self.tab.pages[self.mod.id] = parse_page(HTML)
        self.tab.populate()
        self.tab.table.selectRow(0)

    def test_tabs_filters_edit_navigation_and_versions(self):
        self.assertEqual(self.window.tabs.tabText(0), 'Miziuu')
        self.assertEqual(self.window.tabs.tabText(1), 'StrielokPL')
        self.window.register_source_tab('test', 'Dodatkowe źródło', QWidget())
        self.assertEqual(self.window.tabs.count(), 3)
        make_mod_zip(self.root / self.mod.archive, '0.0.5.1', title=self.mod.name,
                     author='StrielokPL, Miziuu')
        self.tab.filter.setCurrentIndex(1)
        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertIn('edit StrelokPL', self.tab.table.item(0, 5).text())
        self.assertEqual(self.tab.table.item(0, 4).text(), '—')
        self.tab.table.selectRow(0)
        combo = self.tab.table.cellWidget(0, 3)
        combo.setCurrentIndex(1)
        with patch.object(self.tab, 'open_url') as open_url:
            self.tab.open_download()
            open_url.assert_called_once_with('https://modsfire.com/old123')
        self.tab.open_edit()
        self.assertFalse(self.tab.edit_button.isEnabled())
        self.tab.filter.setCurrentIndex(2)
        self.assertEqual(self.tab.table.rowCount(), 1)
        self.assertNotEqual(self.tab.row_mods[0].id, self.mod.id)

    def test_backup_choice_and_cancel(self):
        make_mod_zip(self.root / self.mod.archive, '1.0.0.0', title=self.mod.name)
        for answer, expected in [(QMessageBox.StandardButton.Yes, True),
                                 (QMessageBox.StandardButton.No, False),
                                 (QMessageBox.StandardButton.Cancel, None)]:
            with patch('strelok_fs25_mod_updater.kingmods_gui.QFileDialog.getOpenFileName',
                       return_value=('/tmp/download.zip', '')), \
                 patch('strelok_fs25_mod_updater.kingmods_gui.QMessageBox.question',
                       return_value=answer), \
                 patch.object(self.window, '_start_task') as start, \
                 patch.object(self.window.installer, 'install_local') as install:
                self.tab.import_zip()
                if expected is None:
                    start.assert_not_called()
                else:
                    from unittest.mock import Mock
                    start.call_args.args[0](Mock())
                    self.assertEqual(install.call_args.kwargs['backup'], expected)

    def test_disappeared_version_never_opens_latest_instead(self):
        self.tab.selections[self.mod.id] = '0.5.0.0'
        self.tab.populate()
        self.tab.table.selectRow(0)
        self.assertIsNone(self.tab.release(self.mod))
        with patch.object(self.tab, 'open_url') as open_url:
            self.tab.open_download()
            open_url.assert_not_called()
