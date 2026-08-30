from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .fs25 import inspect_mod_archive, savegame_directories_for, sha256_file
from .github_client import GitHubClient
from .models import CatalogMod, LocalMod, LocalModKind, ReleaseInfo, SourceKind
from .storage import HistoryStore, data_dir


StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


class InstallError(RuntimeError):
    pass


def is_fs25_running() -> bool:
    names = {"farmingsimulator2025game.exe", "farmingsimulator2025game"}
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = completed.stdout.casefold()
            return any(name in output for name in names)
        except (OSError, subprocess.SubprocessError):
            return False

    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            process_name = (entry / "comm").read_text(encoding="utf-8").strip().casefold()
            command_line = (entry / "cmdline").read_bytes().decode("utf-8", "ignore").casefold()
            if process_name in names or any(name in command_line for name in names):
                return True
        except (OSError, UnicodeError):
            continue
    return False


class ModInstaller:
    def __init__(
        self,
        client: GitHubClient,
        history: HistoryStore | None = None,
        backups_root: Path | None = None,
    ):
        self.client = client
        self.history = history or HistoryStore()
        self.backups_root = backups_root or data_dir() / "backups"

    def install(
        self,
        mod: CatalogMod,
        release: ReleaseInfo,
        mods_directory: Path,
        *,
        replaced_mods: tuple[LocalMod, ...] = (),
        backup_savegames: bool = False,
        status: StatusCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, object]:
        if is_fs25_running():
            raise InstallError("Zamknij Farming Simulator 25 przed instalacją aktualizacji")
        mods_directory.mkdir(parents=True, exist_ok=True)
        if not mods_directory.is_dir():
            raise InstallError("Wybrana ścieżka nie jest katalogiem modów")

        if status:
            status(f"Pobieranie {release.asset_name}")
        temporary = mods_directory / f".{uuid.uuid4().hex}.{mod.archive_name}"
        target = mods_directory / mod.archive_name
        backup_dir: Path | None = None
        affected: list[Path] = []

        try:
            self.client.download(release.download_url, temporary, progress=progress)
            downloaded = inspect_mod_archive(
                mod.id,
                temporary,
                with_hash=True,
                catalog_mod=mod,
            )
            if downloaded.version != release.version:
                raise InstallError(
                    "Wersja w modDesc.xml pobranego archiwum nie odpowiada tagowi wydania"
                )
            if (
                mod.source is SourceKind.OFFICIAL
                and mod.mod_desc_titles
                and downloaded.kind is not LocalModKind.MANAGED
            ):
                if downloaded.kind is LocalModKind.ARCHIVE_CONFLICT:
                    raise InstallError(
                        "Tytuł w modDesc.xml pobranego archiwum nie odpowiada katalogowi"
                    )
                raise InstallError(
                    "Pobrane oficjalne archiwum nie zawiera autora StrelokPL w modDesc.xml"
                )
            self._verify_digest(temporary, release.digest)

            affected = self._unique_paths(
                [target] + [item.path for item in replaced_mods]
            )
            existing = [path for path in affected if path.exists()]
            if existing or (backup_savegames and replaced_mods):
                backup_dir = self._new_backup_dir(mod.id)
                if status:
                    status("Tworzenie kopii bezpieczeństwa")
                self._backup_files(existing, backup_dir / "mods")
                if backup_savegames:
                    self._backup_savegames(mods_directory, backup_dir / "savegames")

            removed: list[str] = []
            try:
                for old_mod in replaced_mods:
                    if old_mod.path != target and old_mod.path.exists():
                        old_mod.path.unlink()
                        removed.append(old_mod.path.name)
                os.replace(temporary, target)
            except BaseException:
                self._restore_files(backup_dir, mods_directory)
                raise

            event: dict[str, object] = {
                "type": "migration" if replaced_mods else ("update" if existing else "install"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "modId": mod.id,
                "archiveName": mod.archive_name,
                "version": release.tag,
                "removedArchives": removed,
                "backupDirectory": str(backup_dir) if backup_dir else "",
                "savegamesBackedUp": bool(backup_savegames and backup_dir),
                "sha256": downloaded.sha256 or sha256_file(target),
            }
            self.history.append(event)
            if status:
                status(f"Zainstalowano {mod.name} {release.tag}")
            return event
        except InstallError:
            raise
        except BaseException as exc:
            raise InstallError(str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def rollback(
        self,
        event: dict[str, object],
        mods_directory: Path,
        *,
        restore_savegames: bool = False,
    ) -> None:
        backup_value = str(event.get("backupDirectory", ""))
        if not backup_value:
            raise InstallError("Ta instalacja nie ma kopii możliwej do przywrócenia")
        backup_dir = Path(backup_value)
        if not backup_dir.is_dir():
            raise InstallError("Katalog kopii bezpieczeństwa już nie istnieje")
        archive_name = str(event.get("archiveName", ""))
        if archive_name:
            (mods_directory / archive_name).unlink(missing_ok=True)
        self._restore_files(backup_dir, mods_directory)
        if restore_savegames:
            source = backup_dir / "savegames"
            if source.is_dir():
                profile = mods_directory.parent
                for saved in source.iterdir():
                    target = profile / saved.name
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(saved, target)

    def _new_backup_dir(self, mod_id: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.backups_root / mod_id / f"{timestamp}-{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True, exist_ok=False)
        return path

    @staticmethod
    def _unique_paths(paths: list[Path]) -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = os.path.normcase(str(path.absolute()))
            if key not in seen:
                seen.add(key)
                result.append(path)
        return result

    @staticmethod
    def _backup_files(files: list[Path], target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for source in files:
            shutil.copy2(source, target / source.name)

    @staticmethod
    def _backup_savegames(mods_directory: Path, target: Path) -> None:
        saves = savegame_directories_for(mods_directory)
        if not saves:
            return
        target.mkdir(parents=True, exist_ok=True)
        for savegame in saves:
            shutil.copytree(savegame, target / savegame.name)

    @staticmethod
    def _restore_files(backup_dir: Path | None, mods_directory: Path) -> None:
        if backup_dir is None:
            return
        source = backup_dir / "mods"
        if not source.is_dir():
            return
        for backup in source.iterdir():
            if backup.is_file():
                shutil.copy2(backup, mods_directory / backup.name)

    @staticmethod
    def _verify_digest(path: Path, digest: str | None) -> None:
        if not digest:
            return
        algorithm, _, expected = digest.partition(":")
        if algorithm.casefold() != "sha256" or not expected:
            return
        if sha256_file(path).casefold() != expected.casefold():
            raise InstallError("Suma SHA-256 pobranego archiwum jest nieprawidłowa")
