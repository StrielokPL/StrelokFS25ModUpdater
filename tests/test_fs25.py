from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from strelok_fs25_mod_updater.fs25 import inspect_mod_archive, scan_known_mods
from strelok_fs25_mod_updater.models import CatalogMod

from .helpers import make_mod_zip


class Fs25Tests(unittest.TestCase):
    def test_reads_version_from_mod_desc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = make_mod_zip(Path(directory) / "FS25_Test.zip", "1.2.3.4")
            local = inspect_mod_archive("strelokpl.test", archive, with_hash=True)
            self.assertEqual(local.version_text, "1.2.3.4")
            self.assertEqual(len(local.sha256 or ""), 64)

    def test_requires_mod_desc_at_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "FS25_Bad.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("nested/modDesc.xml", "<modDesc />")
            with self.assertRaisesRegex(ValueError, "katalogu głównym"):
                inspect_mod_archive("strelokpl.bad", archive)

    def test_scanner_uses_exact_archive_name(self) -> None:
        mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test.zip",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_mod_zip(root / "Renamed.zip", "1.0.0.0")
            self.assertEqual(scan_known_mods(root, (mod,)), {})
            make_mod_zip(root / "FS25_Test.zip", "1.0.0.0")
            self.assertIn(mod.id, scan_known_mods(root, (mod,)))


if __name__ == "__main__":
    unittest.main()

