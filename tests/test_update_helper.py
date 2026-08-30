from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from strelok_fs25_mod_updater.update_helper import (
    UPDATE_CLEANUP_ARGUMENT,
    UpdateHelperError,
    perform_update,
)


class UpdateHelperTests(unittest.TestCase):
    def test_replaces_application_and_starts_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Updater.exe"
            staged = root / ".Updater.exe.token.update.exe"
            backup = root / ".Updater.exe.previous"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            waits: list[tuple[int, float]] = []
            launches: list[tuple[Path, list[str]]] = []

            perform_update(
                old_process_id=123,
                target=target,
                staged=staged,
                backup=backup,
                wait=lambda process_id, timeout: waits.append((process_id, timeout)),
                launch=lambda path, arguments: launches.append((path, arguments)),
            )

            self.assertEqual(waits, [(123, 120.0)])
            self.assertEqual(target.read_bytes(), b"new")
            self.assertEqual(backup.read_bytes(), b"old")
            self.assertFalse(staged.exists())
            self.assertEqual(launches, [(target, [UPDATE_CLEANUP_ARGUMENT])])

    def test_restores_previous_version_when_new_one_cannot_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Updater.exe"
            staged = root / ".Updater.exe.token.update.exe"
            backup = root / ".Updater.exe.previous"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            launches: list[tuple[Path, list[str]]] = []

            def launch(path: Path, arguments: list[str]) -> None:
                launches.append((path, arguments))
                if arguments:
                    raise OSError("test launch failure")

            with self.assertLogs(level="ERROR"):
                with self.assertRaises(UpdateHelperError):
                    perform_update(
                        old_process_id=123,
                        target=target,
                        staged=staged,
                        backup=backup,
                        wait=lambda _process_id, _timeout: None,
                        launch=launch,
                    )

            self.assertEqual(target.read_bytes(), b"old")
            self.assertFalse(backup.exists())
            self.assertEqual(launches[-1], (target, []))

    def test_rejects_backup_outside_application_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Updater.exe"
            staged = root / "new.exe"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")

            with self.assertRaisesRegex(UpdateHelperError, "jednym folderze"):
                perform_update(
                    old_process_id=1,
                    target=target,
                    staged=staged,
                    backup=root.parent / "backup.exe",
                    wait=lambda _process_id, _timeout: None,
                    launch=lambda _path, _arguments: None,
                )


if __name__ == "__main__":
    unittest.main()
