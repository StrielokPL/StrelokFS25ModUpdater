from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from strelok_fs25_mod_updater.installer import InstallError, ModInstaller
from strelok_fs25_mod_updater.models import CatalogMod
from strelok_fs25_mod_updater.storage import HistoryStore
from tests.helpers import FakeGitHubClient, make_mod_zip


class RestoreOriginalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mods = self.root / 'mods'
        self.mod = CatalogMod('test.mod', 'Ursus', 'FS25_Test.zip', 'owner/repo',
                              'FS25_Test.zip', mod_desc_titles=('Ursus',))
        self.current = make_mod_zip(self.mods / self.mod.archive_name, '2.0',
                                    author='StrielokPL', title='Ursus')
        self.current_bytes = self.current.read_bytes()
        self.history = HistoryStore(self.root / 'history.json')
        self.installer = ModInstaller(FakeGitHubClient(self.current), self.history,
                                       self.root / 'backups')

    def backup(self, name, author='Original author', title='Ursus'):
        directory = self.root / name
        archive = make_mod_zip(directory / 'mods' / self.mod.archive_name, '1.0',
                               author=author, title=title)
        self.history.append({'modId': self.mod.id, 'archiveName': self.mod.archive_name,
                             'backupDirectory': str(directory), 'version': '2.0'})
        return archive

    @patch('strelok_fs25_mod_updater.installer.is_fs25_running', return_value=False)
    def test_legacy_original_is_restored_and_operation_can_be_undone(self, _running):
        original = self.backup('old original')
        self.backup('newer managed', author='StrielokPL')
        original_bytes = original.read_bytes()
        self.assertEqual(self.installer.find_original_backup(self.mod).path, original)
        event = self.installer.restore_original(self.mod, self.mods)
        self.assertEqual(self.current.read_bytes(), original_bytes)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual((Path(event['backupDirectory']) / 'mods' / self.mod.archive_name).read_bytes(),
                         self.current_bytes)
        self.installer.rollback(event, self.mods)
        self.assertEqual(self.current.read_bytes(), self.current_bytes)

    def test_absent_wrong_title_and_managed_backups_are_not_originals(self):
        self.assertIsNone(self.installer.find_original_backup(self.mod))
        self.backup('wrong title', title='Other mod')
        self.backup('managed', author='StrielokPL')
        self.backup('deleted').unlink()
        self.assertIsNone(self.installer.find_original_backup(self.mod))

    @patch('strelok_fs25_mod_updater.installer.is_fs25_running', return_value=True)
    def test_running_game_blocks_restore(self, _running):
        self.backup('original')
        with self.assertRaisesRegex(InstallError, 'Zamknij'):
            self.installer.restore_original(self.mod, self.mods)
        self.assertEqual(self.current.read_bytes(), self.current_bytes)

    @patch('strelok_fs25_mod_updater.installer.is_fs25_running', return_value=False)
    def test_failed_replace_preserves_current_and_original(self, _running):
        original = self.backup('original')
        old = original.read_bytes()
        with patch('strelok_fs25_mod_updater.installer.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(InstallError):
                self.installer.restore_original(self.mod, self.mods)
        self.assertEqual(self.current.read_bytes(), self.current_bytes)
        self.assertEqual(original.read_bytes(), old)
        self.assertEqual(list(self.mods.iterdir()), [self.current])
