from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from strelok_fs25_mod_updater.self_update import (
    LINUX_ASSET_NAME,
    LINUX_EXECUTABLE_NAME,
    ApplicationUpdate,
    ApplicationUpdateService,
    SelfUpdateError,
    _WINDOWS_UPDATE_SCRIPT,
    cleanup_previous_executable,
)
from strelok_fs25_mod_updater.versioning import ModVersion


def github_release(tag: str, *, prerelease: bool = False, asset: str = LINUX_ASSET_NAME):
    return {
        "tag_name": tag,
        "name": tag,
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-08-30T00:00:00Z",
        "body": f"Zmiany w {tag}",
        "assets": [
            {
                "name": asset,
                "browser_download_url": f"https://example.invalid/{asset}",
                "size": 123,
            }
        ],
    }


class FakeClient:
    def __init__(self, releases=(), download_source: Path | None = None):
        self.releases = list(releases)
        self.download_source = download_source

    def list_releases(self, _repository):
        return self.releases

    def download(self, _url, target, *, progress=None):
        if self.download_source is None:
            raise AssertionError("Brak pliku testowego")
        shutil.copy2(self.download_source, target)
        if progress:
            size = target.stat().st_size
            progress(size, size)


class ApplicationUpdateTests(unittest.TestCase):
    def test_alpha_version_receives_newer_prerelease(self) -> None:
        service = ApplicationUpdateService(
            FakeClient(
                [
                    github_release("v0.0.1a3", prerelease=True),
                    github_release("v0.0.1a4", prerelease=True),
                    github_release("catalog-v2"),
                ]
            ),
            current_version="0.0.1a2",
            platform_name="posix",
        )
        update = service.check()
        self.assertIsNotNone(update)
        self.assertEqual(update.tag, "v0.0.1a4")

    def test_stable_version_ignores_prerelease(self) -> None:
        service = ApplicationUpdateService(
            FakeClient(
                [
                    github_release("v1.1.0a1", prerelease=True),
                    github_release("v1.0.1"),
                ]
            ),
            current_version="1.0.0",
            platform_name="posix",
        )
        update = service.check()
        self.assertIsNotNone(update)
        self.assertEqual(update.tag, "v1.0.1")

    def test_linux_update_is_staged_as_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / LINUX_EXECUTABLE_NAME
            current.write_bytes(b"old executable")
            current.chmod(0o700)
            new_binary = root / "new-binary"
            new_binary.write_bytes(b"new executable")
            archive_path = root / LINUX_ASSET_NAME
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(new_binary, arcname=LINUX_EXECUTABLE_NAME)

            update = ApplicationUpdate(
                tag="v0.0.1a3",
                version=ModVersion.parse("v0.0.1a3"),
                prerelease=True,
                published_at="2026-08-30T00:00:00Z",
                notes="",
                asset_name=LINUX_ASSET_NAME,
                download_url="https://example.invalid/update.tar.gz",
                size=archive_path.stat().st_size,
            )
            service = ApplicationUpdateService(
                FakeClient(download_source=archive_path),
                current_version="0.0.1a2",
                platform_name="posix",
                executable_path=current,
                frozen=True,
            )
            prepared = service.prepare(update)

            self.assertEqual(prepared.staged_path.read_bytes(), b"new executable")
            self.assertTrue(prepared.staged_path.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(current.read_bytes(), b"old executable")

    def test_linux_archive_must_contain_expected_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / LINUX_EXECUTABLE_NAME
            current.write_bytes(b"old")
            archive_path = root / LINUX_ASSET_NAME
            wrong = root / "wrong"
            wrong.write_bytes(b"wrong")
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(wrong, arcname="other-file")
            update = ApplicationUpdate(
                tag="v0.0.1a3",
                version=ModVersion.parse("v0.0.1a3"),
                prerelease=True,
                published_at="",
                notes="",
                asset_name=LINUX_ASSET_NAME,
                download_url="https://example.invalid/update.tar.gz",
                size=archive_path.stat().st_size,
            )
            service = ApplicationUpdateService(
                FakeClient(download_source=archive_path),
                current_version="0.0.1a2",
                platform_name="posix",
                executable_path=current,
                frozen=True,
            )
            with self.assertRaises(SelfUpdateError):
                service.prepare(update)

    def test_previous_executable_cleanup_has_fixed_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / LINUX_EXECUTABLE_NAME
            previous = executable.with_name(f".{executable.name}.previous")
            previous.write_bytes(b"previous")
            cleanup_previous_executable(executable)
            self.assertFalse(previous.exists())

    @unittest.skipUnless(os.name == "nt", "Test składni PowerShell wymaga Windowsa")
    def test_windows_update_helper_has_valid_powershell_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "update.ps1"
            script.write_text(_WINDOWS_UPDATE_SCRIPT, encoding="utf-8")
            environment = os.environ.copy()
            environment["STRELOK_UPDATE_TEST_SCRIPT"] = str(script)
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "[void][ScriptBlock]::Create([IO.File]::ReadAllText("
                    "$env:STRELOK_UPDATE_TEST_SCRIPT))",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
