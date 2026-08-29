from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .models import CatalogMod, ReleaseInfo
from .versioning import ModVersion


ProgressCallback = Callable[[int, int], None]
CATALOG_ASSET_NAME = "strelok-mod-catalog.json"
_CATALOG_TAG_RE = re.compile(r"^catalog-v(?P<version>\d+)$", re.IGNORECASE)


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogRelease:
    catalog_version: int
    tag: str
    published_at: str
    download_url: str
    digest: str | None = None


class GitHubClient:
    """Small public GitHub Releases client with a short in-memory cache."""

    def __init__(self, *, timeout: float = 30.0, cache_seconds: float = 300.0):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    def _request(self, url: str, *, accept: str = "application/vnd.github+json"):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": f"StrelokFS25ModUpdater/{__version__}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            return urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GitHubError(
                    "Repozytorium lub wydanie nie istnieje albo nie jest publiczne"
                ) from exc
            if exc.code in (403, 429):
                remaining = exc.headers.get("X-RateLimit-Remaining")
                if remaining == "0":
                    raise GitHubError("Przekroczono godzinowy limit zapytań GitHub") from exc
                raise GitHubError("GitHub tymczasowo odrzucił zbyt wiele zapytań") from exc
            raise GitHubError(f"GitHub zwrócił błąd HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise GitHubError(f"Nie można połączyć się z GitHubem: {reason}") from exc

    def get_json(self, url: str, *, use_cache: bool = True) -> Any:
        now = time.monotonic()
        cached = self._cache.get(url)
        if use_cache and cached and now - cached[0] <= self.cache_seconds:
            return cached[1]
        try:
            with self._request(url) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubError("GitHub zwrócił nieprawidłową odpowiedź") from exc
        self._cache[url] = (now, data)
        return data

    def list_releases(self, repository: str) -> list[dict[str, Any]]:
        owner, name = repository.split("/", 1)
        url = (
            "https://api.github.com/repos/"
            f"{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/releases?per_page=100"
        )
        value = self.get_json(url)
        if not isinstance(value, list):
            raise GitHubError("GitHub zwrócił nieprawidłową listę wydań")
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _matching_asset(release: dict[str, Any], mod: CatalogMod) -> dict[str, Any] | None:
        assets = [item for item in release.get("assets", []) if isinstance(item, dict)]
        matches = [item for item in assets if mod.matches_asset(str(item.get("name", "")))]
        if not matches:
            return None
        exact = [item for item in matches if str(item.get("name", "")) == mod.archive_name]
        return exact[0] if exact else sorted(matches, key=lambda item: str(item.get("name", "")))[0]

    def releases_for_mod(self, mod: CatalogMod) -> list[ReleaseInfo]:
        result: list[ReleaseInfo] = []
        for release in self.list_releases(mod.repository):
            if release.get("draft"):
                continue
            version = ModVersion.try_parse(str(release.get("tag_name", "")))
            asset = self._matching_asset(release, mod)
            if version is None or asset is None:
                continue
            download_url = str(asset.get("browser_download_url", ""))
            if not download_url.startswith("https://"):
                continue
            result.append(
                ReleaseInfo(
                    tag=str(release.get("tag_name", "")),
                    name=str(release.get("name") or release.get("tag_name", "")),
                    version=version,
                    prerelease=bool(release.get("prerelease", False)),
                    published_at=str(release.get("published_at") or release.get("created_at", "")),
                    notes=str(release.get("body") or ""),
                    asset_name=str(asset.get("name", "")),
                    download_url=download_url,
                    size=int(asset.get("size") or 0),
                    digest=(str(asset["digest"]) if asset.get("digest") else None),
                )
            )
        return result

    def latest_catalog_release(self, repository: str) -> CatalogRelease | None:
        candidates: list[CatalogRelease] = []
        for release in self.list_releases(repository):
            if release.get("draft"):
                continue
            tag = str(release.get("tag_name", ""))
            match = _CATALOG_TAG_RE.fullmatch(tag)
            if not match:
                continue
            assets = [item for item in release.get("assets", []) if isinstance(item, dict)]
            asset = next(
                (item for item in assets if item.get("name") == CATALOG_ASSET_NAME),
                None,
            )
            if asset is None:
                continue
            candidates.append(
                CatalogRelease(
                    catalog_version=int(match.group("version")),
                    tag=tag,
                    published_at=str(release.get("published_at") or ""),
                    download_url=str(asset.get("browser_download_url", "")),
                    digest=(str(asset["digest"]) if asset.get("digest") else None),
                )
            )
        return max(candidates, key=lambda item: item.catalog_version, default=None)

    def download(
        self,
        url: str,
        target: Path,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._request(url, accept="application/octet-stream") as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                with target.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        output.write(chunk)
                        received += len(chunk)
                        if progress:
                            progress(received, total)
                if total and received != total:
                    raise GitHubError(
                        f"Pobrano niepełny plik: {received} z {total} bajtów"
                    )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
