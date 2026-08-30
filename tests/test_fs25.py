from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from strelok_fs25_mod_updater.fs25 import inspect_mod_archive, scan_known_mods
from strelok_fs25_mod_updater.models import CatalogMod, LocalModKind

from .helpers import make_mod_zip


class Fs25Tests(unittest.TestCase):
    def test_reads_version_from_mod_desc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = make_mod_zip(Path(directory) / "FS25_Test.zip", "1.2.3.4")
            local = inspect_mod_archive("strelokpl.test", archive, with_hash=True)
            self.assertEqual(local.version_text, "1.2.3.4")
            self.assertEqual(local.author, "Test")
            self.assertEqual(local.title, "Test mod")
            self.assertEqual(len(local.sha256 or ""), 64)

    def test_author_and_title_do_not_depend_on_xml_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "FS25_Test.zip"
            mod_desc = """<?xml version="1.0" encoding="utf-8"?>
<!-- komentarz przesuwa wszystkie elementy -->
<modDesc descVersion="96">
    <version>1.0.0.0</version>
    <!-- autor nie musi być w trzeciej linii -->
    <author>StrielokPL, Speedy</author>
    <title>
        <en>Ursus C-330/330M</en>
    </title>
</modDesc>
"""
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("modDesc.xml", mod_desc)

            local = inspect_mod_archive("strelokpl.test", archive)

            self.assertEqual(local.author, "StrielokPL, Speedy")
            self.assertEqual(local.title, "Ursus C-330/330M")

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

    def test_matching_title_and_strelokpl_author_is_managed(self) -> None:
        mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test.zip",
            mod_desc_titles=("Ursus C-330/330M",),
        )
        with tempfile.TemporaryDirectory() as directory:
            archive = make_mod_zip(
                Path(directory) / mod.archive_name,
                "1.0.0.0",
                author="M8E, StrielokPL",
                title="Ursus C-330/330M",
            )
            local = scan_known_mods(Path(directory), (mod,))[mod.id]
            self.assertEqual(local.kind, LocalModKind.MANAGED)
            self.assertEqual(local.path, archive)

    def test_matching_title_without_strelokpl_is_replaceable(self) -> None:
        mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test.zip",
            mod_desc_titles=("Ursus C-330/330M",),
        )
        with tempfile.TemporaryDirectory() as directory:
            make_mod_zip(
                Path(directory) / mod.archive_name,
                "9.9.9.9",
                author="Speedy, Miziuu",
                title="Ursus C-330/330M",
            )
            local = scan_known_mods(Path(directory), (mod,))[mod.id]
            self.assertEqual(local.kind, LocalModKind.UNMANAGED_REPLACEABLE)

    def test_mismatched_title_blocks_automatic_replacement(self) -> None:
        mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test.zip",
            mod_desc_titles=("Ursus C-330/330M",),
        )
        with tempfile.TemporaryDirectory() as directory:
            make_mod_zip(
                Path(directory) / mod.archive_name,
                "1.0.0.0",
                author="StrielokPL, Speedy",
                title="Zupełnie inny mod",
            )
            local = scan_known_mods(Path(directory), (mod,))[mod.id]
            self.assertEqual(local.kind, LocalModKind.ARCHIVE_CONFLICT)


if __name__ == "__main__":
    unittest.main()
