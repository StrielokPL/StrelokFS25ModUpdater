from __future__ import annotations

import unittest
from pathlib import Path

from strelok_fs25_mod_updater import __version__


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_windows_metadata_matches_application_version(self) -> None:
        for name in ("version_info.txt", "helper_version_info.txt"):
            contents = (ROOT / "packaging" / name).read_text(encoding="utf-8")
            self.assertIn(f"'{__version__}'", contents)

    def test_windows_builds_disable_upx(self) -> None:
        for name in (
            "StrelokFS25ModUpdater.spec",
            "StrelokFS25ModUpdaterHelper.spec",
        ):
            contents = (ROOT / "packaging" / name).read_text(encoding="utf-8")
            self.assertIn("upx=False", contents)
            self.assertNotIn("upx=True", contents)

    def test_update_implementation_does_not_invoke_powershell(self) -> None:
        contents = "\n".join(
            (ROOT / "src" / "strelok_fs25_mod_updater" / name).read_text(
                encoding="utf-8"
            )
            for name in ("self_update.py", "update_helper.py")
        ).casefold()
        self.assertNotIn("powershell.exe", contents)
        self.assertNotIn("executionpolicy", contents)


if __name__ == "__main__":
    unittest.main()
