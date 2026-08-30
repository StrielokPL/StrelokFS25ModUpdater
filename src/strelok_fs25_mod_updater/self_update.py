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


@dataclass(frozen=True)
class PreparedApplicationUpdate:
    update: ApplicationUpdate
    staged_path: Path
    executable_path: Path
    platform_name: str

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
                [str(target), "--cleanup-update-backup"],
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
        script = target.parent / f".strelok-update-{uuid.uuid4().hex}.ps1"
        script.write_text(_WINDOWS_UPDATE_SCRIPT, encoding="utf-8")
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(script),
                    "-OldPid",
                    str(os.getpid()),
                    "-Target",
                    str(target),
                    "-Staged",
                    str(self.staged_path),
                    "-Backup",
                    str(backup),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            script.unlink(missing_ok=True)
            raise SelfUpdateError(
                f"Nie udało się uruchomić instalatora aktualizacji: {exc}"
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
        if self.platform_name == "nt":
            staged = staged.with_suffix(".exe")
        try:
            if status:
                status(f"Pobieranie aktualizacji {update.tag}…")
            self.client.download(update.download_url, downloaded, progress=progress)
            self._verify_download(downloaded, update)
            if self.platform_name == "nt":
                os.replace(downloaded, staged)
            else:
                self._stage_linux_executable(downloaded, staged, target)
            return PreparedApplicationUpdate(
                update=update,
                staged_path=staged,
                executable_path=target,
                platform_name=self.platform_name,
            )
        except SelfUpdateError:
            raise
        except BaseException as exc:
            raise SelfUpdateError(str(exc)) from exc
        finally:
            downloaded.unlink(missing_ok=True)

    @staticmethod
    def _verify_download(path: Path, update: ApplicationUpdate) -> None:
        if update.size and path.stat().st_size != update.size:
            raise SelfUpdateError("Pobrano niepełny plik aktualizacji")
        if not update.digest:
            return
        algorithm, _, expected = update.digest.partition(":")
        if algorithm.casefold() == "sha256" and expected:
            if sha256_file(path).casefold() != expected.casefold():
                raise SelfUpdateError("Suma SHA-256 aktualizacji jest nieprawidłowa")

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


_WINDOWS_UPDATE_SCRIPT = r'''param(
    [int]$OldPid,
    [string]$Target,
    [string]$Staged,
    [string]$Backup
)

$ErrorActionPreference = "Stop"
Wait-Process -Id $OldPid -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue

try {
    Move-Item -LiteralPath $Target -Destination $Backup -Force
    Move-Item -LiteralPath $Staged -Destination $Target -Force
    Start-Process -FilePath $Target `
        -ArgumentList "--cleanup-update-backup" `
        -WorkingDirectory (Split-Path -Parent $Target)
} catch {
    Remove-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $Backup) {
        Move-Item -LiteralPath $Backup -Destination $Target -Force
        Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target)
    }
}

Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
'''
