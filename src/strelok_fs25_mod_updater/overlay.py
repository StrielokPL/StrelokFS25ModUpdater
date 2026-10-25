"""Verified file overlays: construct a new ZIP before committing any installation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .compatibility import EditCompatibility
from .fs25 import _is_strielokpl_author, inspect_mod_archive
from .installer import InstallError, is_fs25_running
from .kingmods import archive_name, modsfire_url
from .versioning import ModVersion

MAX_BYTES = 20 * 1024**3


def safe_path(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
        or name.startswith("/")
        or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in name.split("/"))
    ):
        raise ValueError(f"Niebezpieczna ścieżka ZIP: {name!r}")
    if any(
        p.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }
        for p in name.split("/")
    ):
        raise ValueError("Zastrzeżona nazwa pliku Windows")
    return PurePosixPath(name).as_posix()


def zip_members(z):
    members, folded, total = {}, set(), 0
    if len(z.infolist()) > 50000:
        raise ValueError("Zbyt wiele plików ZIP")
    for info in z.infolist():
        if info.is_dir():
            continue
        name = safe_path(info.filename)
        if name.casefold() in folded or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("Powielona ścieżka lub dowiązanie w ZIP-ie")
        folded.add(name.casefold())
        members[name] = info
        total += info.file_size
        if total > MAX_BYTES or info.flag_bits & 1:
            raise ValueError("Zbyt duży lub zaszyfrowany ZIP")
    for name in folded:
        if any("/".join(name.split("/")[:i]) in folded for i in range(1, len(name.split("/")))):
            raise ValueError("Konflikt pliku i katalogu w ZIP-ie")
    return members


def index_zip(z, members):
    result = {}
    for name, info in members.items():
        digest = hashlib.sha256()
        with z.open(info) as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        result[name] = {"sha256": digest.hexdigest(), "size": info.file_size}
    return result


def content_digest(index):
    records = [{"path": name, **index[name]} for name in sorted(index)]
    return hashlib.sha256(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def base_assessment(mod, manifest, source):
    profile = EditCompatibility.from_manifest(manifest, mod.repository)
    local = inspect_mod_archive(mod.id, source)
    if _is_strielokpl_author(local.author):
        raise ValueError("Wskaż oryginalny mod, a nie wcześniej zainstalowany edit.")
    if local.title.casefold() not in {t.casefold() for t in mod.titles}:
        raise ValueError("ZIP zawiera inny mod niż wybrany edit.")
    version = (
        profile.source_version
        if local.version == ModVersion.parse(profile.source_xml_version)
        else local.version_text
        if profile.source_xml_version == profile.source_version
        else None
    )
    assessment = profile.assess(version) if version else None
    return local, assessment


def construct_overlay(mod, manifest, base, package, output, *, allow_mismatch=False):
    """Preserve unmodified/new original files, apply listed changes/deletions only."""
    profile = EditCompatibility.from_manifest(manifest, mod.repository)
    if manifest.get("packageType") != "file-overlay" or manifest.get("archiveName") != mod.archive:
        raise ValueError("Nieprawidłowy typ paczki lub nazwa archiwum editu")
    archive_name(mod.archive)
    modsfire_url(manifest["baseMod"]["downloadPage"])
    local, assessment = base_assessment(mod, manifest, base)
    with zipfile.ZipFile(base) as original, zipfile.ZipFile(package) as patch:
        original_members, patch_members = zip_members(original), zip_members(patch)
        roots = [
            n[: -len("updater.json")]
            for n in patch_members
            if n.endswith("/updater.json") and n.count("/") == 1
        ]
        if len(roots) != 1:
            raise ValueError("Brak jednoznacznego manifestu w paczce GitHuba")
        prefix = roots[0]
        if patch_members[prefix + "updater.json"].file_size > 512 * 1024:
            raise ValueError("Manifest jest zbyt duży")
        if json.loads(patch.read(prefix + "updater.json")) != manifest:
            raise ValueError(
                "Edit zmienił się od sprawdzenia wersji. Odśwież listę i spróbuj ponownie."
            )
        index = index_zip(original, original_members)
        exact = content_digest(index) == manifest["baseMod"]["contentSha256"]
        if not exact and not allow_mismatch:
            raise ValueError(
                "Zawartość oryginału różni się od bazy źródłowej. Wymagane potwierdzenie."
            )
        changes, deleted, seen = {}, set(), set()
        entries = manifest.get("files")
        deletions = manifest.get("delete")
        if not isinstance(entries, list) or not isinstance(deletions, list):
            raise ValueError("Nieprawidłowa lista zmian")
        for entry in entries + deletions:
            name = safe_path(entry["path"])
            if name.casefold() in seen:
                raise ValueError("Powielona zmiana w manifeście")
            seen.add(name.casefold())
        for entry in entries:
            name = entry["path"]
            if entry["action"] not in {"add", "replace"}:
                raise ValueError("Nieznana operacja editu")
            if exact:
                old = index.get(name)
                if (
                    (entry["action"] == "add") != (old is None)
                    or old
                    and old["sha256"] != entry.get("baseSha256")
                ):
                    raise ValueError("Operacja nie pasuje do źródłowej bazy")
            member = prefix + "files/" + name
            info = patch_members.get(member)
            if info is None or info.file_size != entry["size"]:
                raise ValueError(f"Brak lub niepoprawny rozmiar pliku: {name}")
            digest = index_zip(patch, {member: info})[member]["sha256"]
            if digest != entry["sha256"]:
                raise ValueError(f"Nieprawidłowa suma pliku editu: {name}")
            changes[name] = info
        payload = {
            n[len(prefix + "files/") :] for n in patch_members if n.startswith(prefix + "files/")
        }
        if payload != set(changes):
            raise ValueError("Nieujawnione pliki w paczce editu")
        for entry in deletions:
            name = entry["path"]
            if exact and (name not in index or index[name]["sha256"] != entry.get("baseSha256")):
                raise ValueError("Usuwany plik nie odpowiada bazie źródłowej")
            deleted.add(name)
        if changes.keys() & deleted or "modDesc.xml" in deleted:
            raise ValueError("Sprzeczne operacje editu")
        final = (set(index) - deleted) | set(changes)
        folded = [n.casefold() for n in final]
        if len(folded) != len(set(folded)) or any(
            "/".join(n.split("/")[:i]) in set(folded)
            for n in folded
            for i in range(1, len(n.split("/")))
        ):
            raise ValueError("Konflikt ścieżek po nałożeniu editu")
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
            for name in sorted(final):
                source_zip = patch if name in changes else original
                info = changes[name] if name in changes else original_members[name]
                with source_zip.open(info) as src, result.open(name, "w", force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        with zipfile.ZipFile(output) as result:
            result_index = index_zip(result, zip_members(result))
        if exact and (
            content_digest(result_index) != manifest["result"]["contentSha256"]
            or len(result_index) != manifest["result"]["fileCount"]
        ):
            raise ValueError("Wynik editu różni się od zweryfikowanej paczki")
    installed = inspect_mod_archive(mod.id, output, with_hash=True)
    if installed.version != ModVersion.parse(profile.edit_version):
        raise ValueError("Wersja utworzonego moda nie odpowiada wersji editu")
    return {
        "exactBase": exact,
        "baseVersion": local.version_text,
        "compatibility": assessment.label if assessment else "Brak oceny",
        "sha256": installed.sha256,
    }


def install_overlay(
    installer,
    mod,
    manifest,
    base,
    directory,
    *,
    backup,
    allow_mismatch=False,
    expected_base_hash=None,
    status=None,
    progress=None,
):
    if is_fs25_running():
        raise InstallError("Zamknij Farming Simulator 25 przed instalacją moda")
    if not directory.is_dir():
        raise InstallError("Wskaż istniejący folder modów")
    target = directory / archive_name(mod.archive)
    if target.is_symlink():
        raise InstallError("Docelowy mod jest dowiązaniem")
    try:
        with tempfile.TemporaryDirectory(prefix=".strelok-edit-", dir=directory) as temporary:
            temporary = Path(temporary)
            staged_base, package, output = (
                temporary / "base.zip",
                temporary / "edit.zip",
                temporary / mod.archive,
            )
            if status:
                status("Przygotowanie oryginalnej paczki")
            shutil.copy2(base, staged_base)
            from .fs25 import sha256_file

            if expected_base_hash and sha256_file(staged_base) != expected_base_hash:
                raise ValueError("Plik bazowy zmienił się po potwierdzeniu instalacji")
            if status:
                status("Pobieranie zmienionych plików editu")
            commit = installer.client.get_json(
                f"https://api.github.com/repos/{mod.repository}/commits/HEAD", use_cache=False
            )["sha"]
            if not re.fullmatch("[0-9a-f]{40}", commit):
                raise ValueError("Nieprawidłowy identyfikator wersji repozytorium")
            installer.client.download(
                f"https://codeload.github.com/{mod.repository}/zip/{commit}",
                package,
                progress=progress,
            )
            if status:
                status("Weryfikacja i nakładanie editu")
            result = construct_overlay(
                mod, manifest, staged_base, package, output, allow_mismatch=allow_mismatch
            )
            backup_dir = None
            if target.exists():
                current = inspect_mod_archive(mod.id, target)
                if current.title.casefold() not in {t.casefold() for t in mod.titles}:
                    raise ValueError("Docelowy ZIP zawiera inny mod")
                if backup:
                    backup_dir = installer._new_backup_dir(mod.id)
                    installer._backup_files([target], backup_dir / "mods")
            if is_fs25_running():
                raise InstallError("Zamknij Farming Simulator 25 przed podmianą moda")
            os.replace(output, target)
            event = {
                "type": "file-overlay",
                "modId": mod.id,
                "archiveName": mod.archive,
                "version": manifest["version"],
                "repository": mod.repository,
                "commit": commit,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "backupDirectory": str(backup_dir) if backup_dir else "",
                **result,
            }
            try:
                installer.history.append(event)
            except OSError:
                import logging

                logging.getLogger(__name__).exception("Nie zapisano historii instalacji editu")
                event["historyWarning"] = True
            return event
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise InstallError(str(exc)) from exc


def find_original_backup(installer, mod):
    for event in reversed(installer.history.load()):
        if (
            event.get("modId") != mod.id
            or event.get("archiveName") != mod.archive
            or not event.get("backupDirectory")
        ):
            continue
        candidate = Path(event["backupDirectory"]) / "mods" / mod.archive
        try:
            local = inspect_mod_archive(mod.id, candidate)
            if not _is_strielokpl_author(local.author) and local.title.casefold() in {
                t.casefold() for t in mod.titles
            }:
                return local
        except (OSError, ValueError):
            continue
    return None


def restore_original(installer, mod, directory, *, backup):
    original = find_original_backup(installer, mod)
    if original is None:
        raise InstallError("Nie znaleziono kopii oryginalnego moda")
    with tempfile.TemporaryDirectory(prefix="strelok-restore-") as temporary:
        source = Path(temporary) / mod.archive
        shutil.copy2(original.path, source)
        return installer.install_local(mod, original.version_text, source, directory, backup=backup)
