from __future__ import annotations

import unittest

from strelok_fs25_mod_updater.versioning import ModVersion, is_newer


class VersioningTests(unittest.TestCase):
    def test_four_part_versions_are_compared_numerically(self) -> None:
        self.assertTrue(is_newer("1.0.10.0", "1.0.2.9"))

    def test_short_versions_are_padded(self) -> None:
        self.assertEqual(ModVersion.parse("v1.2"), ModVersion.parse("1.2.0.0"))

    def test_stable_is_newer_than_suffix_with_same_numbers(self) -> None:
        self.assertGreater(ModVersion.parse("1.2.0.0"), ModVersion.parse("1.2.0.0-P3"))

    def test_suffix_numbers_are_natural(self) -> None:
        self.assertGreater(ModVersion.parse("1.2.0.0-P10"), ModVersion.parse("1.2.0.0-P2"))

    def test_invalid_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ModVersion.parse("finalna")


if __name__ == "__main__":
    unittest.main()

