from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from .github_client import GitHubClient, GitHubError
from .models import (
    CatalogMod,
    LocalMod,
    LocalModKind,
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
        status: Callable[[str], None] | None = None,
    ) -> list[UpdateCheck]:
        logger = logging.getLogger(__name__)
        pinned_versions = pinned_versions or {}
        result: list[UpdateCheck] = []
        logger.info("MOD CHECK START count=%d", len(mods))
        for index, mod in enumerate(mods, start=1):
            if status:
                status(
                    f"Sprawdzanie {index}/{len(mods)}: {mod.name} "
                    f"({mod.repository})"
                )
            local = local_mods.get(mod.id)
            replaced = tuple(
                local_mods[item] for item in mod.replaces if item in local_mods
            )
            channel = channels.get(mod.id, ReleaseChannel.STABLE)
            logger.info(
                "MOD CHECK ITEM index=%d total=%d mod_id=%s repository=%s channel=%s "
                "local=%s local_kind=%s local_author=%s local_title=%s",
                index,
                len(mods),
                mod.id,
                mod.repository,
                channel.value,
                local.version_text if local else "not-installed",
                local.kind.value if local else "none",
                local.author if local else "none",
                local.title if local else "none",
            )
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
                logger.error(
                    "MOD CHECK SOURCE ERROR mod_id=%s repository=%s error=%s",
                    mod.id,
                    mod.repository,
                    exc,
                )
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

            if local and local.kind is LocalModKind.ARCHIVE_CONFLICT:
                check.state = UpdateState.ARCHIVE_CONFLICT
                check.message = (
                    "Nazwa archiwum pasuje, ale tytuł w modDesc.xml nie odpowiada "
                    "oficjalnemu modowi; automatyczna podmiana została zablokowana"
                )
            elif replaced and check.selected_release:
                check.state = UpdateState.MIGRATION_AVAILABLE
                names = ", ".join(item.path.name for item in replaced)
                check.message = f"Migracja zastępuje: {names}"
            elif check.selected_release is None:
                check.state = UpdateState.ERROR
                if channel is ReleaseChannel.PINNED:
                    pinned = pinned_versions.get(mod.id, "")
                    check.message = f"Wybrane wydanie {pinned or '—'} nie jest dostępne"
                elif channel is ReleaseChannel.STABLE and check.prerelease:
                    check.message = (
                        "Brak stabilnego wydania. Dostępne są tylko wersje testowe "
                        f"(najnowsza: {check.prerelease.tag}). Zmień kanał na „stabilne "
                        "i testowe” albo wybierz konkretną wersję"
                    )
                else:
                    check.message = "Nie znaleziono pasującego archiwum w wydaniach"
            elif local is None:
                check.state = UpdateState.NOT_INSTALLED
                check.message = "Mod nie jest zainstalowany"
            elif local.kind is LocalModKind.UNMANAGED_REPLACEABLE:
                check.state = UpdateState.UNMANAGED_REPLACEABLE
                author = local.author or "nieznany autor"
                check.message = (
                    f"Oryginalny mod ({author}) może zostać zastąpiony wydaniem StrelokPL"
                )
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
            logger.info(
                "MOD CHECK RESULT mod_id=%s state=%s releases=%d selected=%s",
                mod.id,
                check.state.value,
                len(check.available_releases),
                check.selected_release.tag if check.selected_release else "none",
            )
        logger.info("MOD CHECK FINISH count=%d", len(result))
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
