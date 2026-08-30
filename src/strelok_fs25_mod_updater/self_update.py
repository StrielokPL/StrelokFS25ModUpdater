from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .fs25 import sha256_file
from .github_client import GitHubClient
from .update_helper import UPDATE_CLEANUP_ARGUMENT, WINDOWS_HELPER_NAME
from .versioning import ModVersion


UPDATER_REPOSITORY = "StrielokPL/StrelokFS25ModUpdater"
WINDOWS_ASSET_NAME = "StrelokFS25ModUpdater-Windows-x64.exe"
LINUX_ASSET_NAME = "StrelokFS25ModUpdater-Linux-x64.tar.gz"
LINUX_EXECUTABLE_NAME = "StrelokFS25ModUpdater"

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


class SelfUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApplicationUpdate:
    tag: str
    version: ModVersion
    prerelease: bool
    published_at: str
    notes: str
    asset_name: str
    download_url: str
    size: int = 0
    digest: str | None = None
    helper_download_url: str = ""
    helper_size: int = 0
    helper_digest: str | None = None


@dataclass(frozen=True)
class PreparedApplicationUpdate:
    update: ApplicationUpdate
    staged_path: Path
    executable_path: Path
    platform_name: str
    helper_path: Path | None = None

    @property
    def backup_path(self) -> Path:
        return self.executable_path.with_name(f".{self.executable_path.name}.previous")

    def apply_and_restart(self) -> None:
        if self.platform_name == "nt":
            self._schedule_windows_update()
        else:
            self._apply_linux_update()

    def _apply_linux_update(self) -> None:
        target = self.executable_path
        backup = self.backup_path
        backup.unlink(missing_ok=True)
        os.replace(target, backup)
        try:
            os.replace(self.staged_path, target)
            subprocess.Popen(
                [str(target), UPDATE_CLEANUP_ARGUMENT],
                cwd=target.parent,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException as exc:
            target.unlink(missing_ok=True)
            os.replace(backup, target)
            raise SelfUpdateError(f"Nie udało się uruchomić nowej wersji: {exc}") from exc

    def _schedule_windows_update(self) -> None:
        target = self.executable_path
        backup = self.backup_path
        helper = self.helper_path
        if helper is None or not helper.is_file():
            raise SelfUpdateError("Nie znaleziono helpera aktualizacji Windows")
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(
                [
                    str(helper),
                    "--old-pid",
                    str(os.getpid()),
                    "--target",
                    str(target),
                    "--staged",
                    str(self.staged_path),
                    "--backup",
                    str(backup),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            self.staged_path.unlink(missing_ok=True)
            raise SelfUpdateError(
                f"Nie udało się uruchomić helpera aktualizacji: {exc}"
            ) from exc


class ApplicationUpdateService:
    def __init__(
        self,
        client: GitHubClient,
        *,
        current_version: str = __version__,
        platform_name: str = os.name,
        executable_path: Path | None = None,
        frozen: bool | None = None,
    ):
        self.client = client
        self.current_version = ModVersion.parse(current_version)
        self.platform_name = platform_name
        self.executable_path = (executable_path or Path(sys.executable)).resolve()
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen

    @property
    def asset_name(self) -> str:
        return WINDOWS_ASSET_NAME if self.platform_name == "nt" else LINUX_ASSET_NAME

    def check(self) -> ApplicationUpdate | None:
        allow_prerelease = bool(self.current_version.suffix)
        candidates: list[ApplicationUpdate] = []
        for release in self.client.list_releases(UPDATER_REPOSITORY):
            if release.get("draft"):
                continue
            tag = str(release.get("tag_name", ""))
            version = ModVersion.try_parse(tag)
            if version is None or version <= self.current_version:
                continue
            is_prerelease = bool(release.get("prerelease") or version.suffix)
            if is_prerelease and not allow_prerelease:
                continue
            assets = [item for item in release.get("assets", []) if isinstance(item, dict)]
            asset = next(
                (item for item in assets if str(item.get("name", "")) == self.asset_name),
                None,
            )
            if asset is None:
                continue
            download_url = str(asset.get("browser_download_url", ""))
            if not download_url.startswith("https://"):
                continue
            helper_asset = None
            if self.platform_name == "nt":
                helper_asset = next(
                    (
                        item
                        for item in assets
                        if str(item.get("name", "")) == WINDOWS_HELPER_NAME
                    ),
                    None,
                )
                if helper_asset is None:
                    continue
                helper_url = str(helper_asset.get("browser_download_url", ""))
                if not helper_url.startswith("https://"):
                    continue
            candidates.append(
                ApplicationUpdate(
                    tag=tag,
                    version=version,
                    prerelease=is_prerelease,
                    published_at=str(
                        release.get("published_at") or release.get("created_at") or ""
                    ),
                    notes=str(release.get("body") or ""),
                    asset_name=self.asset_name,
                    download_url=download_url,
                    size=int(asset.get("size") or 0),
                    digest=(str(asset["digest"]) if asset.get("digest") else None),
                    helper_download_url=(
                        str(helper_asset.get("browser_download_url", ""))
                        if helper_asset
                        else ""
                    ),
                    helper_size=(int(helper_asset.get("size") or 0) if helper_asset else 0),
                    helper_digest=(
                        str(helper_asset["digest"])
                        if helper_asset and helper_asset.get("digest")
                        else None
                    ),
                )
            )
        return max(
            candidates,
            key=lambda item: (item.version, item.published_at),
            default=None,
        )

    def prepare(
        self,
        update: ApplicationUpdate,
        *,
        status: StatusCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> PreparedApplicationUpdate:
        if not self.frozen:
            raise SelfUpdateError(
                "Automatyczna podmiana jest dostępna tylko w spakowanej wersji programu"
            )
        target = self.executable_path
        if not target.is_file():
            raise SelfUpdateError(f"Nie znaleziono uruchomionego programu: {target}")
        if not os.access(target.parent, os.W_OK):
            raise SelfUpdateError(
                "Brak prawa zapisu w folderze programu. Przenieś aplikację do własnego "
                "katalogu, np. ~/Aplikacje."
            )

        token = uuid.uuid4().hex
        downloaded = target.parent / f".{target.name}.{token}.download"
        staged = target.parent / f".{target.name}.{token}.update"
        helper_downloaded: Path | None = None
        helper_path: Path | None = None
        if self.platform_name == "nt":
            staged = staged.with_suffix(".exe")
        try:
            if status:
                status(f"Pobieranie aktualizacji {update.tag}…")
            self.client.download(update.download_url, downloaded, progress=progress)
            self._verify_download(downloaded, update)
            if self.platform_name == "nt":
                self._verify_windows_executable(downloaded, "aplikacji")
                os.replace(downloaded, staged)
                helper_path = target.parent / WINDOWS_HELPER_NAME
                helper_ready = (
                    helper_path.is_file()
                    and helper_path.stat().st_size > 0
                    and self._has_windows_header(helper_path)
                )
                if not helper_ready:
                    if not update.helper_download_url:
                        raise SelfUpdateError(
                            "Wydanie nie zawiera helpera aktualizacji Windows"
                        )
                    if status:
                        status("Pobieranie helpera aktualizacji…")
                    helper_downloaded = target.parent / (
                        f".{WINDOWS_HELPER_NAME}.{token}.download"
                    )
                    self.client.download(
                        update.helper_download_url,
                        helper_downloaded,
                        progress=progress,
                    )
                    self._verify_file(
                        helper_downloaded,
                        expected_size=update.helper_size,
                        digest=update.helper_digest,
                        description="helpera aktualizacji",
                    )
                    self._verify_windows_executable(
                        helper_downloaded,
                        "helpera aktualizacji",
                    )
                    os.replace(helper_downloaded, helper_path)
            else:
                self._stage_linux_executable(downloaded, staged, target)
            return PreparedApplicationUpdate(
                update=update,
                staged_path=staged,
                executable_path=target,
                platform_name=self.platform_name,
                helper_path=helper_path,
            )
        except SelfUpdateError:
            staged.unlink(missing_ok=True)
            raise
        except BaseException as exc:
            staged.unlink(missing_ok=True)
            raise SelfUpdateError(str(exc)) from exc
        finally:
            downloaded.unlink(missing_ok=True)
            if helper_downloaded is not None:
                helper_downloaded.unlink(missing_ok=True)

    @staticmethod
    def _verify_download(path: Path, update: ApplicationUpdate) -> None:
        ApplicationUpdateService._verify_file(
            path,
            expected_size=update.size,
            digest=update.digest,
            description="pliku aktualizacji",
        )

    @staticmethod
    def _verify_file(
        path: Path,
        *,
        expected_size: int,
        digest: str | None,
        description: str,
    ) -> None:
        if expected_size and path.stat().st_size != expected_size:
            raise SelfUpdateError(f"Pobrano niepełny plik {description}")
        if not digest:
            return
        algorithm, _, expected = digest.partition(":")
        if algorithm.casefold() == "sha256" and expected:
            if sha256_file(path).casefold() != expected.casefold():
                raise SelfUpdateError(f"Suma SHA-256 {description} jest nieprawidłowa")

    @staticmethod
    def _has_windows_header(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                return handle.read(2) == b"MZ"
        except OSError:
            return False

    @staticmethod
    def _verify_windows_executable(path: Path, description: str) -> None:
        if not ApplicationUpdateService._has_windows_header(path):
            raise SelfUpdateError(f"Pobrany plik {description} nie jest programem Windows")

    @staticmethod
    def _stage_linux_executable(archive_path: Path, staged: Path, current: Path) -> None:
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                member = archive.getmember(LINUX_EXECUTABLE_NAME)
                if not member.isfile() or member.size <= 0 or member.size > 1024 * 1024 * 1024:
                    raise SelfUpdateError("Archiwum aktualizacji zawiera nieprawidłowy program")
                source = archive.extractfile(member)
                if source is None:
                    raise SelfUpdateError("Nie można odczytać programu z aktualizacji")
                with source, staged.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        except (KeyError, tarfile.TarError) as exc:
            raise SelfUpdateError("Nieprawidłowe archiwum aktualizacji dla Linuksa") from exc
        mode = stat.S_IMODE(current.stat().st_mode)
        staged.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def cleanup_previous_executable(executable_path: Path | None = None) -> None:
    if not getattr(sys, "frozen", False) and executable_path is None:
        return
    target = (executable_path or Path(sys.executable)).resolve()
    target.with_name(f".{target.name}.previous").unlink(missing_ok=True)
