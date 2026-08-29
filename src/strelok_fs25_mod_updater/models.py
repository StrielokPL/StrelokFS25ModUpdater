from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .versioning import ModVersion


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class SourceKind(str, Enum):
    OFFICIAL = "official"
    EXTERNAL = "external"


class ReleaseChannel(str, Enum):
    STABLE = "stable"
    PRERELEASE = "prerelease"
    PINNED = "pinned"
    DISABLED = "disabled"


class ModStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"
    DEPRECATED = "deprecated"
    UNAVAILABLE = "unavailable"


class UpdateState(str, Enum):
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"
    CURRENT = "current"
    UPDATE_AVAILABLE = "update_available"
    PRERELEASE_AVAILABLE = "prerelease_available"
    VERSION_CHANGE = "version_change"
    LOCAL_NEWER = "local_newer"
    MIGRATION_AVAILABLE = "migration_available"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class MigrationSpec:
    type: str = "merge"
    save_risk: bool = True
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MigrationSpec | None":
        if not data:
            return None
        migration_type = str(data.get("type", "merge"))
        if migration_type != "merge":
            raise ValueError(f"Nieobsługiwany typ migracji: {migration_type}")
        return cls(
            type=migration_type,
            save_risk=bool(data.get("saveRisk", True)),
            message=str(data.get("message", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "saveRisk": self.save_risk,
            "message": self.message,
        }


@dataclass(frozen=True)
class CatalogMod:
    id: str
    name: str
    archive_name: str
    repository: str
    asset_pattern: str
    source: SourceKind = SourceKind.OFFICIAL
    status: ModStatus = ModStatus.ACTIVE
    description: str = ""
    replaces: tuple[str, ...] = ()
    replacement_id: str | None = None
    migration: MigrationSpec | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.id):
            raise ValueError(f"Nieprawidłowy identyfikator moda: {self.id}")
        if not self.name.strip():
            raise ValueError("Nazwa moda nie może być pusta")
        if (
            Path(self.archive_name).name != self.archive_name
            or not self.archive_name.lower().endswith(".zip")
        ):
            raise ValueError(f"Nieprawidłowa nazwa archiwum: {self.archive_name}")
        if not _REPOSITORY_RE.fullmatch(self.repository):
            raise ValueError(
                f"Repozytorium musi mieć format właściciel/nazwa: {self.repository}"
            )
        if not self.asset_pattern.strip():
            raise ValueError("Wzorzec assetu nie może być pusty")

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        source: SourceKind = SourceKind.OFFICIAL,
    ) -> "CatalogMod":
        archive_name = str(data.get("archiveName", ""))
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            archive_name=archive_name,
            repository=str(data.get("repository", "")),
            asset_pattern=str(data.get("assetPattern", archive_name)),
            source=source,
            status=ModStatus(str(data.get("status", ModStatus.ACTIVE.value))),
            description=str(data.get("description", "")),
            replaces=tuple(str(item) for item in data.get("replaces", [])),
            replacement_id=(
                str(data["replacementId"]) if data.get("replacementId") else None
            ),
            migration=MigrationSpec.from_dict(data.get("migration")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "archiveName": self.archive_name,
            "repository": self.repository,
            "assetPattern": self.asset_pattern,
            "status": self.status.value,
        }
        if self.description:
            result["description"] = self.description
        if self.replaces:
            result["replaces"] = list(self.replaces)
        if self.replacement_id:
            result["replacementId"] = self.replacement_id
        if self.migration:
            result["migration"] = self.migration.to_dict()
        return result

    def matches_asset(self, asset_name: str) -> bool:
        return fnmatch.fnmatchcase(asset_name, self.asset_pattern)


@dataclass(frozen=True)
class OfficialCatalog:
    schema_version: int
    catalog_version: int
    minimum_updater_version: str
    published_at: str
    mods: tuple[CatalogMod, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Nieobsługiwana wersja schematu katalogu: {self.schema_version}")
        if self.catalog_version < 1:
            raise ValueError("Wersja katalogu musi być dodatnia")

        ids = [mod.id for mod in self.mods]
        archives = [mod.archive_name.casefold() for mod in self.mods]
        if len(ids) != len(set(ids)):
            raise ValueError("Katalog zawiera powielone identyfikatory modów")
        if len(archives) != len(set(archives)):
            raise ValueError("Katalog zawiera powielone nazwy archiwów")

        known_ids = set(ids)
        for mod in self.mods:
            missing = set(mod.replaces) - known_ids
            if missing:
                raise ValueError(
                    f"Mod {mod.id} zastępuje nieznane identyfikatory: {sorted(missing)}"
                )
            if mod.replacement_id and mod.replacement_id not in known_ids:
                raise ValueError(
                    f"Mod {mod.id} wskazuje nieznany zamiennik: {mod.replacement_id}"
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OfficialCatalog":
        mods_data = data.get("mods")
        if not isinstance(mods_data, list):
            raise ValueError("Pole mods musi być listą")
        return cls(
            schema_version=int(data.get("schemaVersion", 0)),
            catalog_version=int(data.get("catalogVersion", 0)),
            minimum_updater_version=str(data.get("minimumUpdaterVersion", "0.0.0")),
            published_at=str(data.get("publishedAt", "")),
            mods=tuple(CatalogMod.from_dict(item) for item in mods_data),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "catalogVersion": self.catalog_version,
            "minimumUpdaterVersion": self.minimum_updater_version,
            "publishedAt": self.published_at,
            "mods": [mod.to_dict() for mod in self.mods],
        }

    def by_id(self) -> dict[str, CatalogMod]:
        return {mod.id: mod for mod in self.mods}


@dataclass(frozen=True)
class LocalMod:
    mod_id: str
    path: Path
    version_text: str
    version: ModVersion
    sha256: str | None = None


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    name: str
    version: ModVersion
    prerelease: bool
    published_at: str
    notes: str
    asset_name: str
    download_url: str
    size: int = 0
    digest: str | None = None


@dataclass
class UpdateCheck:
    mod: CatalogMod
    local: LocalMod | None = None
    stable: ReleaseInfo | None = None
    prerelease: ReleaseInfo | None = None
    available_releases: tuple[ReleaseInfo, ...] = field(default_factory=tuple)
    selected_release: ReleaseInfo | None = None
    state: UpdateState = UpdateState.UNKNOWN
    message: str = ""
    replaced_local_mods: tuple[LocalMod, ...] = field(default_factory=tuple)
