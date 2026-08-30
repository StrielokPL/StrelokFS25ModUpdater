from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from strelok_fs25_mod_updater.self_update import (
    LINUX_ASSET_NAME,
    LINUX_EXECUTABLE_NAME,
    WINDOWS_ASSET_NAME,
    ApplicationUpdate,
    ApplicationUpdateService,
    PreparedApplicationUpdate,
    SelfUpdateError,
    cleanup_previous_executable,
)
from strelok_fs25_mod_updater.update_helper import WINDOWS_HELPER_NAME
from strelok_fs25_mod_updater.versioning import ModVersion


def github_release(tag: str, *, prerelease: bool = False, asset: str = LINUX_ASSET_NAME):
    assets = [
        {
            "name": asset,
            "browser_download_url": f"https://example.invalid/{asset}",
            "size": 123,
        }
    ]
    if asset == WINDOWS_ASSET_NAME:
        assets.append(
            {
                "name": WINDOWS_HELPER_NAME,
                "browser_download_url": f"https://example.invalid/{WINDOWS_HELPER_NAME}",
                "size": 45,
            }
        )
    return {
        "tag_name": tag,
        "name": tag,
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-08-30T00:00:00Z",
        "body": f"Zmiany w {tag}",
        "assets": assets,
    }


class FakeClient:
    def __init__(
        self,
        releases=(),
        download_source: Path | None = None,
        helper_source: Path | None = None,
    ):
        self.releases = list(releases)
        self.download_source = download_source
        self.helper_source = helper_source

    def list_releases(self, _repository):
        return self.releases

    def download(self, url, target, *, progress=None):
        source = (
            self.helper_source
            if url.endswith(WINDOWS_HELPER_NAME)
            else self.download_source
        )
        if source is None:
            raise AssertionError("Brak pliku testowego")
        shutil.copy2(source, target)
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

    def test_windows_release_includes_separate_helper(self) -> None:
        service = ApplicationUpdateService(
            FakeClient(
                [
                    github_release(
                        "v0.0.1a6",
                        prerelease=True,
                        asset=WINDOWS_ASSET_NAME,
                    )
                ]
            ),
            current_version="0.0.1a5",
            platform_name="nt",
        )

        update = service.check()

        self.assertIsNotNone(update)
        self.assertTrue(update.helper_download_url.endswith(WINDOWS_HELPER_NAME))

    def test_windows_release_without_helper_is_ignored(self) -> None:
        release = github_release(
            "v0.0.1a6",
            prerelease=True,
            asset=WINDOWS_ASSET_NAME,
        )
        release["assets"] = release["assets"][:1]
        service = ApplicationUpdateService(
            FakeClient([release]),
            current_version="0.0.1a5",
            platform_name="nt",
        )

        self.assertIsNone(service.check())

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
            if os.name != "nt":
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

    def test_windows_update_downloads_and_prepares_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / WINDOWS_ASSET_NAME
            current.write_bytes(b"old application")
            new_application = root / "new-application"
            new_application.write_bytes(b"MZnew application")
            new_helper = root / "new-helper"
            new_helper.write_bytes(b"MZupdate helper")
            update = ApplicationUpdate(
                tag="v0.0.1a6",
                version=ModVersion.parse("v0.0.1a6"),
                prerelease=True,
                published_at="",
                notes="",
                asset_name=WINDOWS_ASSET_NAME,
                download_url="https://example.invalid/application.exe",
                size=new_application.stat().st_size,
                helper_download_url=f"https://example.invalid/{WINDOWS_HELPER_NAME}",
                helper_size=new_helper.stat().st_size,
            )
            service = ApplicationUpdateService(
                FakeClient(
                    download_source=new_application,
                    helper_source=new_helper,
                ),
                current_version="0.0.1a5",
                platform_name="nt",
                executable_path=current,
                frozen=True,
            )

            prepared = service.prepare(update)

            self.assertEqual(prepared.staged_path.read_bytes(), b"MZnew application")
            self.assertEqual(
                prepared.helper_path,
                (root / WINDOWS_HELPER_NAME).resolve(),
            )
            self.assertEqual(prepared.helper_path.read_bytes(), b"MZupdate helper")
            self.assertEqual(current.read_bytes(), b"old application")

    def test_windows_update_launches_helper_without_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / WINDOWS_ASSET_NAME
            staged = root / ".application.update.exe"
            helper = root / WINDOWS_HELPER_NAME
            current.write_bytes(b"old")
            staged.write_bytes(b"new")
            helper.write_bytes(b"helper")
            update = ApplicationUpdate(
                tag="v0.0.1a6",
                version=ModVersion.parse("v0.0.1a6"),
                prerelease=True,
                published_at="",
                notes="",
                asset_name=WINDOWS_ASSET_NAME,
                download_url="https://example.invalid/application.exe",
            )
            prepared = PreparedApplicationUpdate(
                update=update,
                staged_path=staged,
                executable_path=current,
                platform_name="nt",
                helper_path=helper,
            )

            with mock.patch(
                "strelok_fs25_mod_updater.self_update.subprocess.Popen"
            ) as popen:
                prepared.apply_and_restart()

            arguments = popen.call_args.args[0]
            self.assertEqual(arguments[0], str(helper))
            self.assertNotIn("powershell.exe", [item.casefold() for item in arguments])
            self.assertIn("--old-pid", arguments)
            self.assertIn("--staged", arguments)

    def test_previous_executable_cleanup_has_fixed_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / LINUX_EXECUTABLE_NAME
            previous = executable.with_name(f".{executable.name}.previous")
            previous.write_bytes(b"previous")
            cleanup_previous_executable(executable)
            self.assertFalse(previous.exists())

if __name__ == "__main__":
    unittest.main()
