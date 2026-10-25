import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from strelok_fs25_mod_updater.installer import InstallError, ModInstaller
from strelok_fs25_mod_updater.kingmods import (
    DEFAULT_MODS,
    KingMod,
    KingModsClient,
    KingModsError,
    KingModsStore,
    github_list_url,
    kingmods_url,
    parse_page,
    parse_watch_list,
)
from strelok_fs25_mod_updater.storage import HistoryStore
from tests.helpers import make_mod_zip

HTML = """<h1>Ursus C-330/330M</h1>
<a href="https://modsfire.com/new123" target="_blank" class="btn">
 <svg></svg> Pobierz V1.10.0.0 (modsfire.com)</a>
<a href="https://modsfire.com/new123" class="dropdown-item">Pobierz V1.10.0.0</a>
<a href="https://modsfire.com/old123" class="dropdown-item">Pobierz <span>V1.9.1.0</span></a>
<a href="https://evil.example/modsfire.com/file">Pobierz V9.0.0.0</a>"""


class KingModsTests(unittest.TestCase):
    def test_versions_deduplicate_and_sort_numerically(self):
        page = parse_page(HTML)
        self.assertEqual(page.name, "Ursus C-330/330M")
        self.assertEqual(
            [(r.version, r.url) for r in page.releases],
            [
                ("1.10.0.0", "https://modsfire.com/new123"),
                ("1.9.1.0", "https://modsfire.com/old123"),
            ],
        )

    def test_no_download_or_ambiguous_version_is_error(self):
        for text in [
            "<h1>Cloudflare</h1>",
            HTML + '<a href="https://modsfire.com/other">Pobierz V1.9.1.0</a>',
        ]:
            with self.assertRaises(KingModsError):
                parse_page(text)

    def test_urls_and_archive_cannot_escape_allowed_sources(self):
        for value in [
            "http://www.kingmods.net/pl/fs25/mods/63913/test",
            "https://www.kingmods.net.evil/pl/fs25/mods/63913/test",
            "https://user@www.kingmods.net/pl/fs25/mods/63913/test",
        ]:
            with self.assertRaises(ValueError):
                kingmods_url(value)
        with self.assertRaises(ValueError):
            KingMod(DEFAULT_MODS[0].url, archive="../outside.zip")
        with self.assertRaises(ValueError):
            github_list_url("https://github.com.evil/user/repo/blob/main/mods.txt")
        self.assertEqual(
            github_list_url("https://github.com/a/b/blob/main/mods.json"),
            "https://raw.githubusercontent.com/a/b/main/mods.json",
        )

    def test_lists_support_txt_json_and_stable_language_independent_ids(self):
        url = DEFAULT_MODS[0].url
        entries = parse_watch_list("# Lista\n" + url + "\n" + url.replace("/pl/", "/en/"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, "kingmods.63913")
        entries = parse_watch_list(
            '{"mods":[{"url":"' + url + '","archiveName":"FS25_Test.zip","editId":"my.edit"}]}'
        )
        self.assertEqual(entries[0].edit_id, "my.edit")
        with self.assertRaises(ValueError):
            parse_watch_list('{"mods":"invalid"}')

    def test_store_empty_list_persists_and_metadata_resolves(self):
        with tempfile.TemporaryDirectory() as root:
            store = KingModsStore(Path(root) / "watch.json")
            self.assertEqual(len(store.load()[0]), 2)
            store.save([], "feed")
            self.assertEqual(store.load(), ([], "feed"))
        client = KingModsClient()
        with patch.object(client, "read", side_effect=[HTML, "<h3>FS25_Ursus.zip</h3>"]):
            mod, page = client.fetch(KingMod(DEFAULT_MODS[0].url))
        self.assertEqual(mod.archive, "FS25_Ursus.zip")
        self.assertEqual(len(page.releases), 2)


class KingModsInstallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.directory = self.root / "mods"
        self.directory.mkdir()
        self.mod = DEFAULT_MODS[0]
        self.target = make_mod_zip(
            self.directory / self.mod.archive, "1.0.0.0", title=self.mod.name
        )
        self.before = self.target.read_bytes()
        self.source = make_mod_zip(
            self.root / "downloads" / self.mod.archive, "1.9.1.0", title=self.mod.name
        )
        self.installer = ModInstaller(
            None, HistoryStore(self.root / "history.json"), self.root / "backups"
        )
        running = patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=False)
        running.start()
        self.addCleanup(running.stop)

    def install(self, backup=True, version="1.9.1.0"):
        return self.installer.install_local(
            self.mod, version, self.source, self.directory, backup=backup
        )

    def test_backup_then_move_and_history(self):
        expected = self.source.read_bytes()
        event = self.install()
        self.assertEqual(self.target.read_bytes(), expected)
        self.assertFalse(self.source.exists())
        self.assertEqual(
            (Path(event["backupDirectory"]) / "mods" / self.mod.archive).read_bytes(), self.before
        )
        self.assertEqual(event["modId"], self.mod.edit_id)

    def test_without_backup(self):
        self.assertEqual(self.install(False)["backupDirectory"], "")
        self.assertFalse(self.installer.backups_root.exists())
        self.assertFalse(self.source.exists())

    def test_wrong_version_title_or_broken_archive_preserves_old_and_source(self):
        for kwargs in [
            {"version": "1.8.0.0", "title": self.mod.name},
            {"version": "1.9.1.0", "title": "Different mod"},
        ]:
            make_mod_zip(self.source, **kwargs)
            with self.assertRaises(InstallError):
                self.install()
            self.assertEqual(self.target.read_bytes(), self.before)
            self.assertTrue(self.source.exists())
        self.source.write_bytes(b"not a zip")
        with self.assertRaises(InstallError):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_failed_backup_or_replace_preserves_previous(self):
        for method in ["_backup_files", None]:
            mocked = (
                patch.object(self.installer, method, side_effect=OSError("disk full"))
                if method
                else patch(
                    "strelok_fs25_mod_updater.installer.os.replace", side_effect=OSError("locked")
                )
            )
            with mocked, self.assertRaises(InstallError):
                self.install()
            self.assertEqual(self.target.read_bytes(), self.before)
            self.assertTrue(self.source.exists())

    def test_first_install_and_duplicate_browser_filename(self):
        self.target.unlink()
        renamed = self.source.with_name(self.source.stem + " (1).zip")
        self.source.rename(renamed)
        self.source = renamed
        self.assertEqual(self.install()["backupDirectory"], "")
        self.assertTrue(self.target.exists())

    def test_same_file_and_running_game_are_rejected(self):
        self.source = self.target
        with self.assertRaises(InstallError):
            self.install(version="1.0.0.0")
        with (
            patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=True),
            self.assertRaises(InstallError),
        ):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.before)
