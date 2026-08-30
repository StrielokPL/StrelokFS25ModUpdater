from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from strelok_fs25_mod_updater.diagnostics import create_diagnostic_bundle


class DiagnosticBundleTests(unittest.TestCase):
    def test_bundle_contains_system_information_and_all_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            logs = root / "logs"
            logs.mkdir()
            (logs / "strelok-fs25-mod-updater.log").write_text(
                "main log", encoding="utf-8"
            )
            (logs / "strelok-fs25-mod-updater.log.1").write_text(
                "older log", encoding="utf-8"
            )
            (logs / "strelok-fs25-mod-updater-fatal.log").write_text(
                "fatal log", encoding="utf-8"
            )
            (logs / "history.json").write_text("private history", encoding="utf-8")
            target = root / "diagnostics.zip"

            create_diagnostic_bundle(
                target,
                source_directory=logs,
                extra={"status": "Sprawdzanie repozytorium"},
            )

            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "diagnostics.json",
                        "logs/strelok-fs25-mod-updater.log",
                        "logs/strelok-fs25-mod-updater.log.1",
                        "logs/strelok-fs25-mod-updater-fatal.log",
                    },
                )
                information = json.loads(archive.read("diagnostics.json"))
                self.assertIn("operatingSystem", information)
                self.assertEqual(
                    information["applicationState"]["status"],
                    "Sprawdzanie repozytorium",
                )


if __name__ == "__main__":
    unittest.main()
