from __future__ import annotations

import hashlib
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .models import CatalogMod, LocalMod
from .versioning import ModVersion


_SAVEGAME_RE = re.compile(r"^savegame\d+$", re.IGNORECASE)


def discover_mod_directories() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = [
        home / "Documents" / "My Games" / "FarmingSimulator2025" / "mods",
    ]

    if os.name == "nt":
        user_profile = Path(os.environ.get("USERPROFILE", home))
        candidates.append(
            user_profile / "Documents" / "My Games" / "FarmingSimulator2025" / "mods"
        )
        one_drive = os.environ.get("OneDrive")
        if one_drive:
            candidates.append(
                Path(one_drive) / "Documents" / "My Games" / "FarmingSimulator2025" / "mods"
            )
    else:
        wine_users = home / ".wine" / "drive_c" / "users"
        if wine_users.is_dir():
            for user_dir in wine_users.iterdir():
                candidates.append(
                    user_dir / "Documents" / "My Games" / "FarmingSimulator2025" / "mods"
                )

        compatdata = home / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        if compatdata.is_dir():
            for prefix in compatdata.iterdir():
                candidates.append(
                    prefix
                    / "pfx"
                    / "drive_c"
                    / "users"
                    / "steamuser"
                    / "Documents"
                    / "My Games"
                    / "FarmingSimulator2025"
                    / "mods"
                )

    existing: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            existing.append(resolved)
    return existing


def inspect_mod_archive(mod_id: str, path: Path, *, with_hash: bool = False) -> LocalMod:
    if path.name.lower().endswith(".zip") is False:
        raise ValueError(f"Plik nie jest archiwum ZIP: {path.name}")
    try:
        with zipfile.ZipFile(path) as archive:
            if "modDesc.xml" not in archive.namelist():
                raise ValueError(f"Archiwum {path.name} nie zawiera modDesc.xml w katalogu głównym")
            info = archive.getinfo("modDesc.xml")
            if info.file_size > 4 * 1024 * 1024:
                raise ValueError(f"Plik modDesc.xml w {path.name} jest podejrzanie duży")
            root = ElementTree.fromstring(archive.read(info))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Uszkodzone archiwum ZIP: {path.name}") from exc
    except ElementTree.ParseError as exc:
        raise ValueError(f"Nieprawidłowy modDesc.xml w {path.name}") from exc

    version_text = (root.findtext("version") or "").strip()
    version = ModVersion.try_parse(version_text)
    if version is None:
        raise ValueError(f"Nieprawidłowa lub brakująca wersja w {path.name}")

    return LocalMod(
        mod_id=mod_id,
        path=path,
        version_text=version_text,
        version=version,
        sha256=sha256_file(path) if with_hash else None,
    )


def scan_known_mods(mods_directory: Path, mods: tuple[CatalogMod, ...]) -> dict[str, LocalMod]:
    result: dict[str, LocalMod] = {}
    if not mods_directory.is_dir():
        return result
    for mod in mods:
        archive = mods_directory / mod.archive_name
        if not archive.is_file():
            continue
        try:
            result[mod.id] = inspect_mod_archive(mod.id, archive)
        except (OSError, ValueError):
            continue
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def savegame_directories_for(mods_directory: Path) -> list[Path]:
    profile = mods_directory.parent
    if not profile.is_dir():
        return []
    return sorted(
        path
        for path in profile.iterdir()
        if path.is_dir() and _SAVEGAME_RE.fullmatch(path.name)
    )

