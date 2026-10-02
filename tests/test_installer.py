from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

from strelok_fs25_mod_updater.fs25 import inspect_mod_archive, scan_known_mods
from strelok_fs25_mod_updater.installer import InstallError, ModInstaller
from strelok_fs25_mod_updater.models import CatalogMod, ReleaseInfo, UpdateState
from strelok_fs25_mod_updater.update_service import UpdateCheckService
from strelok_fs25_mod_updater.storage import HistoryStore
from strelok_fs25_mod_updater.versioning import ModVersion

from .helpers import FakeGitHubClient, make_mod_zip


def release(version: str, archive_name: str) -> ReleaseInfo:
    return ReleaseInfo(
        tag=version,
        name=version,
        version=ModVersion.parse(version),
        prerelease=False,
        published_at="2026-08-29T00:00:00Z",
        notes="",
        asset_name=archive_name,
        download_url="https://example.invalid/mod.zip",
    )


class InstallerTests(unittest.TestCase):
    @patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=False)
    def test_numeric_xml_prerelease_installs_backs_up_and_remembers_exact_tag(self, _running) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mod = CatalogMod("test.mod", "Test", "FS25_Test.zip", "owner/repo", "FS25_Test.zip", mod_desc_titles=("Test mod",))
            mods = root / "mods"
            target = make_mod_zip(mods / mod.archive_name, "1.1.1.1", author="Original")
            old_bytes = target.read_bytes()
            source = make_mod_zip(root / "source.zip", "1.1.1.2", author="StrielokPL")
            selected = replace(release("1.1.1.2P2", mod.archive_name), prerelease=True)
            history = HistoryStore(root / "history.json")
            installer = ModInstaller(FakeGitHubClient(source), history, root / "backups")
            event = installer.install(mod, selected, mods)
            backup = Path(event["backupDirectory"]) / "mods" / mod.archive_name
            self.assertEqual(backup.read_bytes(), old_bytes)
            local = scan_known_mods(mods, (mod,), history=history.load())
            self.assertEqual(local[mod.id].version_text, "1.1.1.2P2")
            self.assertEqual(event["modDescVersion"], "1.1.1.2")
            from strelok_fs25_mod_updater.models import ReleaseChannel
            with patch.object(FakeGitHubClient, "releases_for_mod", create=True, return_value=[selected]):
                check = UpdateCheckService(FakeGitHubClient(source)).check_all(
                    (mod,), local, {mod.id: ReleaseChannel.PRERELEASE})[0]
            self.assertEqual(check.state, UpdateState.CURRENT)
            # Replacing the archive manually must invalidate the remembered tag.
            make_mod_zip(target, "1.1.1.2", author="StrielokPL", extra={"changed.txt": "changed"})
            self.assertEqual(scan_known_mods(mods, (mod,), history=history.load())[mod.id].version_text, "1.1.1.2")
            installer.rollback(event, mods)
            self.assertEqual(target.read_bytes(), old_bytes)

    @patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=False)
    def test_version_and_digest_mismatches_preserve_existing_mod(self, _running) -> None:
        for xml, tag, prerelease, digest in (
            ("1.1.1.1", "1.1.1.2P2", True, None),
            ("1.1.1.2P1", "1.1.1.2P2", True, None),
            ("1.1.1.2", "1.1.1.2P2", False, None),
            ("1.1.1.2", "1.1.1.2P2", True, "sha256:" + "0" * 64),
        ):
            with self.subTest(xml=xml, prerelease=prerelease, digest=digest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                mod = CatalogMod("test.mod", "Test", "FS25_Test.zip", "owner/repo", "FS25_Test.zip")
                mods = root / "mods"
                target = make_mod_zip(mods / mod.archive_name, "1.0.0.0")
                original = target.read_bytes()
                source = make_mod_zip(root / "source.zip", xml)
                selected = replace(release(tag, mod.archive_name), prerelease=prerelease, digest=digest)
                installer = ModInstaller(FakeGitHubClient(source), HistoryStore(root / "history.json"), root / "backups")
                with self.assertRaises(InstallError):
                    installer.install(mod, selected, mods)
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse((root / "backups").exists())
                self.assertEqual(list(mods.iterdir()), [target])

    def test_update_creates_backup_and_can_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mods = root / "profile" / "mods"
            mods.mkdir(parents=True)
            old = make_mod_zip(mods / "FS25_Test.zip", "1.0.0.0", extra={"old.txt": "old"})
            source = make_mod_zip(root / "release.zip", "1.1.0.0", extra={"new.txt": "new"})
            mod = CatalogMod(
                id="strelokpl.test",
                name="Test",
                archive_name="FS25_Test.zip",
                repository="StrielokPL/Test",
                asset_pattern="FS25_Test.zip",
            )
            installer = ModInstaller(
                FakeGitHubClient(source),
                HistoryStore(root / "history.json"),
                root / "backups",
            )
            event = installer.install(mod, release("1.1.0.0", mod.archive_name), mods)
            self.assertEqual(inspect_mod_archive(mod.id, old).version_text, "1.1.0.0")
            self.assertTrue(Path(str(event["backupDirectory"])).is_dir())

            installer.rollback(event, mods)
            self.assertEqual(inspect_mod_archive(mod.id, old).version_text, "1.0.0.0")

    def test_merge_backs_up_old_mods_and_savegames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile"
            mods = profile / "mods"
            mods.mkdir(parents=True)
            old_a_path = make_mod_zip(mods / "FS25_OldA.zip", "1.0.0.0")
            old_b_path = make_mod_zip(mods / "FS25_OldB.zip", "1.0.0.0")
            save = profile / "savegame1"
            save.mkdir()
            (save / "vehicles.xml").write_text("before", encoding="utf-8")
            source = make_mod_zip(root / "pack-release.zip", "2.0.0.0")

            old_a = inspect_mod_archive("strelokpl.old-a", old_a_path)
            old_b = inspect_mod_archive("strelokpl.old-b", old_b_path)
            pack = CatalogMod(
                id="strelokpl.pack",
                name="Pack",
                archive_name="FS25_Pack.zip",
                repository="StrielokPL/Pack",
                asset_pattern="FS25_Pack.zip",
                replaces=(old_a.mod_id, old_b.mod_id),
            )
            installer = ModInstaller(
                FakeGitHubClient(source),
                HistoryStore(root / "history.json"),
                root / "backups",
            )
            event = installer.install(
                pack,
                release("2.0.0.0", pack.archive_name),
                mods,
                replaced_mods=(old_a, old_b),
                backup_savegames=True,
            )
            self.assertFalse(old_a_path.exists())
            self.assertFalse(old_b_path.exists())
            self.assertTrue((mods / pack.archive_name).exists())
            backup = Path(str(event["backupDirectory"]))
            self.assertTrue((backup / "mods" / old_a_path.name).exists())
            self.assertTrue((backup / "savegames" / "savegame1" / "vehicles.xml").exists())

            (save / "vehicles.xml").write_text("after", encoding="utf-8")
            installer.rollback(event, mods, restore_savegames=True)
            self.assertTrue(old_a_path.exists())
            self.assertTrue(old_b_path.exists())
            self.assertFalse((mods / pack.archive_name).exists())
            self.assertEqual((save / "vehicles.xml").read_text(encoding="utf-8"), "before")

    def test_official_download_requires_matching_title_and_strelokpl_author(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mods = root / "mods"
            source = make_mod_zip(
                root / "release.zip",
                "1.0.0.0",
                author="Speedy, Miziuu",
                title="Ursus C-330/330M",
            )
            mod = CatalogMod(
                id="strelokpl.test",
                name="Test",
                archive_name="FS25_Test.zip",
                repository="StrielokPL/Test",
                asset_pattern="FS25_Test.zip",
                mod_desc_titles=("Ursus C-330/330M",),
            )
            installer = ModInstaller(
                FakeGitHubClient(source),
                HistoryStore(root / "history.json"),
                root / "backups",
            )

            with self.assertRaisesRegex(InstallError, "autora StrelokPL"):
                installer.install(mod, release("1.0.0.0", mod.archive_name), mods)

            self.assertFalse((mods / mod.archive_name).exists())

    def test_official_download_accepts_strelokpl_in_author_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mods = root / "mods"
            source = make_mod_zip(
                root / "release.zip",
                "1.0.0.0",
                author="M8E, StrielokPL",
                title="Ursus 1654-1954 Pack",
            )
            mod = CatalogMod(
                id="strelokpl.ursus",
                name="Ursus",
                archive_name="FS25_Ursus.zip",
                repository="StrielokPL/Ursus",
                asset_pattern="FS25_Ursus.zip",
                mod_desc_titles=("Ursus 1654-1954 Pack",),
            )
            installer = ModInstaller(
                FakeGitHubClient(source),
                HistoryStore(root / "history.json"),
                root / "backups",
            )

            installer.install(mod, release("1.0.0.0", mod.archive_name), mods)

            self.assertTrue((mods / mod.archive_name).exists())


if __name__ == "__main__":
    unittest.main()
