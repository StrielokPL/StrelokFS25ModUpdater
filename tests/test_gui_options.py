import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
    from strelok_fs25_mod_updater.gui import MainWindow
except ImportError:
    QApplication = None

from strelok_fs25_mod_updater.models import UpdateCheck, LocalModKind
from strelok_fs25_mod_updater.fs25 import inspect_mod_archive
from tests import test_restore_original as restore_fixtures


@unittest.skipIf(QApplication is None, 'Qt is not installed')
class GuiOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_restore_visibility_and_busy_controls(self):
        fixture = restore_fixtures.RestoreOriginalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as profile, patch.dict(os.environ, {
            'LOCALAPPDATA': profile, 'XDG_CONFIG_HOME': profile, 'XDG_DATA_HOME': profile,
        }), patch.object(MainWindow, '_initialise_path'):
            window = MainWindow()
            try:
                window.installer = fixture.installer
                window.mods = (fixture.mod,)
                local = inspect_mod_archive(fixture.mod.id, fixture.current, catalog_mod=fixture.mod)
                self.assertEqual(local.kind, LocalModKind.MANAGED)
                check = UpdateCheck(mod=fixture.mod, local=local)
                window._populate_table([check])
                self.assertEqual(window.table.cellWidget(0, 6).findData('action:restore-original'), -1)
                fixture.backup('original')
                window._populate_table([check])
                self.assertGreaterEqual(window.table.cellWidget(0, 6).findData('action:restore-original'), 0)
                labels = [a.text() for a in window.options_menu.actions() if not a.isSeparator()]
                self.assertEqual(labels, ['Aktualizuj aplikację', 'Dodaj zewnętrzne repo…',
                                         'Usuń zewnętrzne repo…', 'Cofnij aktualizację moda…'])
                from PySide6.QtWidgets import QMessageBox
                window.settings.mods_directory = str(fixture.mods)
                combo = window.table.cellWidget(0, 6)
                previous = combo.currentData()
                with patch('strelok_fs25_mod_updater.gui.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
                    combo.setCurrentIndex(combo.findData('action:restore-original'))
                    self.app.processEvents()
                self.assertEqual(combo.currentData(), previous)
                self.assertEqual(fixture.current.read_bytes(), fixture.current_bytes)
                original = fixture.installer.find_original_backup(fixture.mod)
                restored_local = inspect_mod_archive(fixture.mod.id, original.path, catalog_mod=fixture.mod)
                window._populate_table([UpdateCheck(mod=fixture.mod, local=restored_local)])
                self.assertEqual(window.table.cellWidget(0, 6).findData('action:restore-original'), -1)
                window.busy_tasks = 1
                window._update_busy_state()
                self.assertFalse(window.options_button.isEnabled())
                self.assertFalse(window.rollback_action.isEnabled())
                window.busy_tasks = 0
                window._update_busy_state()
                self.assertTrue(window.options_button.isEnabled())
            finally:
                window.close()
