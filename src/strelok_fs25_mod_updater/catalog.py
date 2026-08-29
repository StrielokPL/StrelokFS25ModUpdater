from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from . import __version__
from .models import OfficialCatalog
from .storage import atomic_write_json
from .versioning import ModVersion


class CatalogManager:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path

    @staticmethod
    def bundled_catalog() -> OfficialCatalog:
        resource = resources.files("strelok_fs25_mod_updater").joinpath(
            "resources/official_catalog.json"
        )
        with resource.open("r", encoding="utf-8") as handle:
            return OfficialCatalog.from_dict(json.load(handle))

    @staticmethod
    def load_file(path: Path) -> OfficialCatalog:
        with path.open("r", encoding="utf-8") as handle:
            return OfficialCatalog.from_dict(json.load(handle))

    def current(self) -> OfficialCatalog:
        bundled = self.bundled_catalog()
        if not self.cache_path.exists():
            return bundled
        try:
            cached = self.load_file(self.cache_path)
            if not self.is_compatible(cached):
                return bundled
            return cached if cached.catalog_version >= bundled.catalog_version else bundled
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return bundled

    @staticmethod
    def is_compatible(catalog: OfficialCatalog) -> bool:
        required = ModVersion.try_parse(catalog.minimum_updater_version)
        current = ModVersion.try_parse(__version__)
        return bool(required and current and current >= required)

    def install(self, catalog: OfficialCatalog) -> None:
        if not self.is_compatible(catalog):
            raise ValueError(
                "Katalog wymaga nowszej wersji Strelok FS25 Mod Updater"
            )
        atomic_write_json(self.cache_path, catalog.to_dict())

