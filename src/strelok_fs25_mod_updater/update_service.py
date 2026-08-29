from __future__ import annotations

from collections.abc import Iterable

from .github_client import GitHubClient, GitHubError
from .models import (
    CatalogMod,
    LocalMod,
    ModStatus,
    ReleaseChannel,
    ReleaseInfo,
    UpdateCheck,
    UpdateState,
)


def _latest(releases: Iterable[ReleaseInfo]) -> ReleaseInfo | None:
    return max(releases, key=lambda item: (item.version, item.published_at), default=None)


class UpdateCheckService:
    def __init__(self, client: GitHubClient):
        self.client = client

    def check_all(
        self,
        mods: tuple[CatalogMod, ...],
        local_mods: dict[str, LocalMod],
        channels: dict[str, ReleaseChannel],
        pinned_versions: dict[str, str] | None = None,
    ) -> list[UpdateCheck]:
        pinned_versions = pinned_versions or {}
        result: list[UpdateCheck] = []
        for mod in mods:
            local = local_mods.get(mod.id)
            replaced = tuple(
                local_mods[item] for item in mod.replaces if item in local_mods
            )
            channel = channels.get(mod.id, ReleaseChannel.STABLE)
            check = UpdateCheck(mod=mod, local=local, replaced_local_mods=replaced)

            if mod.status is not ModStatus.ACTIVE:
                check.state = UpdateState.DISABLED
                check.message = self._inactive_message(mod)
                result.append(check)
                continue
            if channel is ReleaseChannel.DISABLED:
                check.state = UpdateState.DISABLED
                check.message = "Sprawdzanie aktualizacji zostało wyłączone"
                result.append(check)
                continue

            try:
                releases = self.client.releases_for_mod(mod)
            except GitHubError as exc:
                check.state = UpdateState.ERROR
                check.message = str(exc)
                result.append(check)
                continue

            check.available_releases = tuple(
                sorted(
                    releases,
                    key=lambda item: (item.version, item.published_at),
                    reverse=True,
                )
            )
            check.stable = _latest(item for item in releases if not item.prerelease)
            check.prerelease = _latest(item for item in releases if item.prerelease)
            check.selected_release = self._select_release(
                check,
                channel,
                pinned_versions.get(mod.id, ""),
            )

            if replaced and check.selected_release:
                check.state = UpdateState.MIGRATION_AVAILABLE
                names = ", ".join(item.path.name for item in replaced)
                check.message = f"Migracja zastępuje: {names}"
            elif check.selected_release is None:
                check.state = UpdateState.ERROR
                if channel is ReleaseChannel.PINNED:
                    pinned = pinned_versions.get(mod.id, "")
                    check.message = f"Wybrane wydanie {pinned or '—'} nie jest dostępne"
                else:
                    check.message = "Nie znaleziono pasującego archiwum w wydaniach"
            elif local is None:
                check.state = UpdateState.NOT_INSTALLED
                check.message = "Mod nie jest zainstalowany"
            elif check.selected_release.version > local.version:
                check.state = (
                    UpdateState.PRERELEASE_AVAILABLE
                    if check.selected_release.prerelease
                    else UpdateState.UPDATE_AVAILABLE
                )
                check.message = f"Dostępna wersja {check.selected_release.tag}"
            elif check.selected_release.version == local.version:
                check.state = UpdateState.CURRENT
                check.message = "Zainstalowana jest najnowsza wybrana wersja"
            else:
                if channel is ReleaseChannel.PINNED:
                    check.state = UpdateState.VERSION_CHANGE
                    check.message = (
                        f"Wybrano starszą wersję {check.selected_release.tag}; "
                        "przed zmianą powstanie kopia"
                    )
                else:
                    check.state = UpdateState.LOCAL_NEWER
                    check.message = "Wersja lokalna jest nowsza od wybranego kanału"
            result.append(check)
        return result

    @staticmethod
    def _select_release(
        check: UpdateCheck,
        channel: ReleaseChannel,
        pinned_tag: str,
    ) -> ReleaseInfo | None:
        if channel is ReleaseChannel.STABLE:
            return check.stable
        if channel is ReleaseChannel.PRERELEASE:
            return _latest(item for item in (check.stable, check.prerelease) if item)
        if channel is ReleaseChannel.PINNED:
            return next(
                (item for item in check.available_releases if item.tag == pinned_tag),
                None,
            )
        return None

    @staticmethod
    def _inactive_message(mod: CatalogMod) -> str:
        if mod.status is ModStatus.MERGED:
            return f"Mod został połączony z {mod.replacement_id or 'inną paczką'}"
        if mod.status is ModStatus.DEPRECATED:
            return f"Mod został zastąpiony przez {mod.replacement_id or 'inny projekt'}"
        if mod.status is ModStatus.ARCHIVED:
            return "Mod został zarchiwizowany"
        return "Mod jest obecnie niedostępny"
