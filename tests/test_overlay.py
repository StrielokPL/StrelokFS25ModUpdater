import copy
import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from strelok_fs25_mod_updater.installer import InstallError, ModInstaller
from strelok_fs25_mod_updater.overlay import (
    construct_overlay,
    content_digest,
    find_original_backup,
    index_zip,
    install_overlay,
    restore_original,
    zip_members,
)
from strelok_fs25_mod_updater.packs import EDIT_MODS, MIZIUU_LIST, OWN_LIST, parse_pack
from strelok_fs25_mod_updater.storage import HistoryStore
from tests.helpers import make_mod_zip


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mod = EDIT_MODS[0]
        self.base = make_mod_zip(
            self.root / self.mod.archive,
            "1.0.0.0",
            title=self.mod.titles[0],
            extra={"old.txt": "delete", "keep.txt": "keep"},
        )
        self.edit = make_mod_zip(
            self.root / "edited.zip",
            "0.0.5.1",
            author="StrielokPL",
            title=self.mod.titles[0],
            extra={"keep.txt": "keep", "new.txt": "added"},
        )
        with zipfile.ZipFile(self.base) as z:
            base_index = index_zip(z, zip_members(z))
        with zipfile.ZipFile(self.edit) as z:
            result_index = index_zip(z, zip_members(z))
            self.payload = {n: z.read(n) for n in ["modDesc.xml", "new.txt"]}
        self.manifest = {
            "schemaVersion": 1,
            "packageType": "file-overlay",
            "id": "edit330miziuu",
            "version": "0.0.5.1",
            "archiveName": self.mod.archive,
            "baseMod": {
                "kingmodsUrl": "https://www.kingmods.net/en/fs25/mods/63913/ursus",
                "downloadPage": "https://modsfire.com/abc",
                "version": "1.0.0.0",
                "sha256": hashlib.sha256(self.base.read_bytes()).hexdigest(),
                "contentSha256": content_digest(base_index),
            },
            "files": [
                {
                    "path": n,
                    "action": "replace" if n == "modDesc.xml" else "add",
                    **result_index[n],
                    **({"baseSha256": base_index[n]["sha256"]} if n == "modDesc.xml" else {}),
                }
                for n in self.payload
            ],
            "delete": [{"path": "old.txt", "baseSha256": base_index["old.txt"]["sha256"]}],
            "result": {
                "fileCount": len(result_index),
                "contentSha256": content_digest(result_index),
            },
        }
        self.package = self.root / "repo.zip"
        self.write_package()
        self.directory = self.root / "mods"
        self.directory.mkdir()
        self.client = Mock()
        self.client.get_json.return_value = {"sha": "a" * 40}
        self.client.download.side_effect = lambda url, path, **kw: shutil.copy2(self.package, path)
        self.installer = ModInstaller(
            self.client, HistoryStore(self.root / "history.json"), self.root / "backups"
        )

    def write_package(self, manifest=None, payload=None):
        with zipfile.ZipFile(self.package, "w") as z:
            z.writestr("repo/updater.json", json.dumps(manifest or self.manifest))
            for n, data in (payload or self.payload).items():
                z.writestr("repo/files/" + n, data)

    def build(self, **kwargs):
        return construct_overlay(
            self.mod, self.manifest, self.base, self.package, self.root / "result.zip", **kwargs
        )

    def test_official_list_accepts_edits_but_community_cannot_add_github(self):
        text = "My list\n" + "\n".join(m.url for m in EDIT_MODS)
        self.assertEqual(parse_pack(text, source=OWN_LIST)[1], list(EDIT_MODS))
        for source in ["", MIZIUU_LIST, OWN_LIST.replace("HEAD", "other")]:
            with self.assertRaises(ValueError):
                parse_pack(text, source=source)

    def test_reconstructs_source_replaces_adds_deletes_and_preserves_base(self):
        before = self.base.read_bytes()
        result = self.build()
        self.assertTrue(result["exactBase"])
        with zipfile.ZipFile(self.root / "result.zip") as z:
            self.assertEqual(set(z.namelist()), {"modDesc.xml", "keep.txt", "new.txt"})
            self.assertEqual(z.read("keep.txt"), b"keep")
        self.assertEqual(self.base.read_bytes(), before)

    def test_new_original_files_survive_only_after_explicit_confirmation(self):
        with zipfile.ZipFile(self.base, "a") as z:
            z.writestr("new-original.txt", "feature")
        with self.assertRaisesRegex(ValueError, "potwierdzenie"):
            self.build()
        result = self.build(allow_mismatch=True)
        self.assertFalse(result["exactBase"])
        with zipfile.ZipFile(self.root / "result.zip") as z:
            self.assertEqual(z.read("new-original.txt"), b"feature")

    def test_tampered_payload_rejected_even_when_user_allows_mismatch(self):
        self.write_package(payload={**self.payload, "new.txt": b"evil!"})
        with self.assertRaisesRegex(ValueError, "suma"):
            self.build(allow_mismatch=True)

    def test_snapshot_change_rejected(self):
        m = copy.deepcopy(self.manifest)
        m["version"] = "0.0.5.2"
        self.write_package(manifest=m)
        with self.assertRaisesRegex(ValueError, "zmienił"):
            self.build()

    def test_paths_duplicates_case_conflicts_symlinks_rejected(self):
        for name in ["../escape", "/absolute", "C:/file", "a\\b", "CON.txt", "a./b"]:
            self.write_package(payload={**self.payload, name: b"bad"})
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.build()
        self.write_package()
        with zipfile.ZipFile(self.package, "a") as z:
            z.writestr("repo/files/NEW.txt", "case conflict")
        with self.assertRaises(ValueError):
            self.build()

    def test_atomic_install_backup_restore_and_preserve_download(self):
        target = self.directory / self.mod.archive
        shutil.copy2(self.base, target)
        before = target.read_bytes()
        with patch("strelok_fs25_mod_updater.overlay.is_fs25_running", return_value=False):
            event = install_overlay(
                self.installer, self.mod, self.manifest, self.base, self.directory, backup=True
            )
        self.assertTrue(self.base.exists())
        self.assertEqual(
            (Path(event["backupDirectory"]) / "mods" / self.mod.archive).read_bytes(), before
        )
        self.assertIsNotNone(find_original_backup(self.installer, self.mod))
        with patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=False):
            restore_original(self.installer, self.mod, self.directory, backup=False)
        self.assertEqual(target.read_bytes(), before)
        self.assertIsNotNone(find_original_backup(self.installer, self.mod))

    def test_failed_install_does_not_change_target_or_create_backup(self):
        target = self.directory / self.mod.archive
        shutil.copy2(self.base, target)
        before = target.read_bytes()
        self.write_package(payload={**self.payload, "new.txt": b"bad"})
        with (
            patch("strelok_fs25_mod_updater.overlay.is_fs25_running", return_value=False),
            self.assertRaises(InstallError),
        ):
            install_overlay(
                self.installer, self.mod, self.manifest, self.base, self.directory, backup=True
            )
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.root / "backups").exists())
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_no_backup_and_changed_source_guard(self):
        target = self.directory / self.mod.archive
        shutil.copy2(self.base, target)
        with patch("strelok_fs25_mod_updater.overlay.is_fs25_running", return_value=False):
            with self.assertRaisesRegex(InstallError, "zmienił"):
                install_overlay(
                    self.installer,
                    self.mod,
                    self.manifest,
                    self.base,
                    self.directory,
                    backup=False,
                    expected_base_hash="bad",
                )
            event = install_overlay(
                self.installer, self.mod, self.manifest, self.base, self.directory, backup=False
            )
        self.assertEqual(event["backupDirectory"], "")
        self.assertFalse((self.root / "backups").exists())
