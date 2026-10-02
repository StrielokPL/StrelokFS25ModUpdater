from __future__ import annotations

import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path

from strelok_fs25_mod_updater.update_helper import (
    UPDATE_CLEANUP_ARGUMENT,
    UpdateHelperError,
    perform_update,
    launch_application,
    main,
)


class UpdateHelperTests(unittest.TestCase):
    def test_restarted_application_has_independent_pyinstaller_environment(self) -> None:
        with patch.dict(os.environ, {"_PYI_APPLICATION_HOME_DIR": "old extraction"}):
            with patch("strelok_fs25_mod_updater.update_helper.subprocess.Popen") as popen:
                launch_application(Path("app.exe"), [])
            self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            self.assertEqual(os.environ["_PYI_APPLICATION_HOME_DIR"], "old extraction")

    def test_helper_waits_for_parent_authorization_before_touching_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, staged = root / "app.exe", root / "new.exe"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            ready, proceed = staged.with_suffix(".ready"), staged.with_suffix(".proceed")
            with patch("strelok_fs25_mod_updater.update_helper._configure_logging"), patch(
                "strelok_fs25_mod_updater.update_helper.perform_update"
            ) as perform, patch("strelok_fs25_mod_updater.update_helper._show_error"), patch(
                "strelok_fs25_mod_updater.update_helper.time.monotonic", side_effect=[0, 41]
            ):
                result = main(["--old-pid", "1", "--target", str(target), "--staged", str(staged),
                    "--backup", str(root / ".app.exe.previous"),
                    "--ready-file", str(ready), "--proceed-file", str(proceed)])
            self.assertEqual(result, 1)
            perform.assert_not_called()
            self.assertEqual(target.read_bytes(), b"old")
            self.assertFalse(ready.exists())

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
            self.assertEqual(
                launches,
                [(target.resolve(), [UPDATE_CLEANUP_ARGUMENT])],
            )

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
            self.assertEqual(launches[-1], (target.resolve(), []))

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
