from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .catalog import CatalogManager
from .fs25 import sha256_file
from .github_client import CatalogRelease, GitHubClient
from .models import OfficialCatalog


UPDATER_REPOSITORY = "StrielokPL/StrelokFS25ModUpdater"


@dataclass(frozen=True)
class CatalogUpdate:
    release: CatalogRelease
    current_version: int


class CatalogUpdateService:
    def __init__(self, client: GitHubClient, manager: CatalogManager):
        self.client = client
        self.manager = manager

    def check(self) -> CatalogUpdate | None:
        current = self.manager.current()
        release = self.client.latest_catalog_release(UPDATER_REPOSITORY)
        if release is None or release.catalog_version <= current.catalog_version:
            return None
        return CatalogUpdate(release=release, current_version=current.catalog_version)

    def download_and_install(self, update: CatalogUpdate) -> OfficialCatalog:
        with tempfile.TemporaryDirectory(prefix="strelok-catalog-") as directory:
            target = Path(directory) / "catalog.json"
            self.client.download(update.release.download_url, target)
            if update.release.digest:
                algorithm, _, expected = update.release.digest.partition(":")
                if algorithm.lower() == "sha256" and expected:
                    actual = sha256_file(target)
                    if actual.casefold() != expected.casefold():
                        raise ValueError("Suma SHA-256 pobranego katalogu jest nieprawidłowa")
            try:
                with target.open("r", encoding="utf-8") as handle:
                    catalog = OfficialCatalog.from_dict(json.load(handle))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("Pobrany katalog nie jest poprawnym plikiem JSON") from exc
            if catalog.catalog_version != update.release.catalog_version:
                raise ValueError("Wersja wewnątrz katalogu nie odpowiada wydaniu GitHub")
            self.manager.install(catalog)
            return catalog

