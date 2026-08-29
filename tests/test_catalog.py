from __future__ import annotations

import unittest

from strelok_fs25_mod_updater.catalog import CatalogManager
from strelok_fs25_mod_updater.models import OfficialCatalog


def catalog_data() -> dict:
    return {
        "schemaVersion": 1,
        "catalogVersion": 2,
        "minimumUpdaterVersion": "0.1.0.dev1",
        "publishedAt": "2026-08-29",
        "mods": [
            {
                "id": "strelokpl.old-a",
                "name": "Old A",
                "archiveName": "FS25_OldA.zip",
                "repository": "StrielokPL/OldA",
                "status": "merged",
                "replacementId": "strelokpl.pack",
            },
            {
                "id": "strelokpl.old-b",
                "name": "Old B",
                "archiveName": "FS25_OldB.zip",
                "repository": "StrielokPL/OldB",
                "status": "merged",
                "replacementId": "strelokpl.pack",
            },
            {
                "id": "strelokpl.pack",
                "name": "Pack",
                "archiveName": "FS25_Pack.zip",
                "repository": "StrielokPL/Pack",
                "replaces": ["strelokpl.old-a", "strelokpl.old-b"],
                "migration": {"type": "merge", "saveRisk": True},
            },
        ],
    }


class CatalogTests(unittest.TestCase):
    def test_bundled_catalog_is_valid_and_compatible(self) -> None:
        catalog = CatalogManager.bundled_catalog()
        self.assertTrue(CatalogManager.is_compatible(catalog))
        self.assertEqual(catalog.mods[0].id, "strelokpl.ursus16541954")

    def test_merge_relationship_is_loaded(self) -> None:
        catalog = OfficialCatalog.from_dict(catalog_data())
        pack = catalog.by_id()["strelokpl.pack"]
        self.assertEqual(pack.replaces, ("strelokpl.old-a", "strelokpl.old-b"))
        self.assertTrue(pack.migration and pack.migration.save_risk)

    def test_unknown_replacement_is_rejected(self) -> None:
        data = catalog_data()
        data["mods"][2]["replaces"] = ["strelokpl.missing"]
        with self.assertRaises(ValueError):
            OfficialCatalog.from_dict(data)

    def test_duplicate_archive_names_are_rejected(self) -> None:
        data = catalog_data()
        data["mods"][1]["archiveName"] = "FS25_OldA.zip"
        with self.assertRaises(ValueError):
            OfficialCatalog.from_dict(data)


if __name__ == "__main__":
    unittest.main()

