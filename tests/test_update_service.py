from __future__ import annotations

import unittest

from strelok_fs25_mod_updater.models import (
    CatalogMod,
    LocalMod,
    LocalModKind,
    ReleaseChannel,
    ReleaseInfo,
    UpdateState,
)
from strelok_fs25_mod_updater.update_service import UpdateCheckService
from strelok_fs25_mod_updater.versioning import ModVersion


def release(tag: str, prerelease: bool = False) -> ReleaseInfo:
    return ReleaseInfo(
        tag=tag,
        name=tag,
        version=ModVersion.parse(tag),
        prerelease=prerelease,
        published_at="2026-08-29T00:00:00Z",
        notes="",
        asset_name="FS25_Test.zip",
        download_url="https://example.invalid/FS25_Test.zip",
    )


class FakeReleaseClient:
    def __init__(self, releases):
        self.releases = releases

    def releases_for_mod(self, _mod):
        return self.releases


class UpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test.zip",
        )

    def local(
        self,
        version: str,
        *,
        kind: LocalModKind = LocalModKind.MANAGED,
        author: str = "StrielokPL",
    ) -> LocalMod:
        return LocalMod(
            mod_id=self.mod.id,
            path=__import__("pathlib").Path("FS25_Test.zip"),
            version_text=version,
            version=ModVersion.parse(version),
            author=author,
            title="Test mod",
            kind=kind,
        )

    def test_stable_channel_ignores_prerelease(self) -> None:
        service = UpdateCheckService(
            FakeReleaseClient([release("1.1.0.0"), release("2.0.0.0-P1", True)])
        )
        check = service.check_all(
            (self.mod,),
            {self.mod.id: self.local("1.0.0.0")},
            {self.mod.id: ReleaseChannel.STABLE},
        )[0]
        self.assertEqual(check.selected_release.tag, "1.1.0.0")
        self.assertEqual(check.state, UpdateState.UPDATE_AVAILABLE)

    def test_test_channel_selects_newest_version(self) -> None:
        service = UpdateCheckService(
            FakeReleaseClient([release("1.1.0.0"), release("2.0.0.0-P1", True)])
        )
        check = service.check_all(
            (self.mod,),
            {self.mod.id: self.local("1.1.0.0")},
            {self.mod.id: ReleaseChannel.PRERELEASE},
        )[0]
        self.assertEqual(check.selected_release.tag, "2.0.0.0-P1")
        self.assertEqual(check.state, UpdateState.PRERELEASE_AVAILABLE)

    def test_pinned_release_can_select_an_older_version(self) -> None:
        service = UpdateCheckService(
            FakeReleaseClient([release("1.0.0.0"), release("2.0.0.0")])
        )
        check = service.check_all(
            (self.mod,),
            {self.mod.id: self.local("2.0.0.0")},
            {self.mod.id: ReleaseChannel.PINNED},
            {self.mod.id: "1.0.0.0"},
        )[0]
        self.assertEqual(check.selected_release.tag, "1.0.0.0")
        self.assertEqual(check.state, UpdateState.VERSION_CHANGE)
        self.assertEqual(
            [item.tag for item in check.available_releases],
            ["2.0.0.0", "1.0.0.0"],
        )

    def test_missing_pinned_release_is_an_error(self) -> None:
        service = UpdateCheckService(FakeReleaseClient([release("2.0.0.0")]))
        check = service.check_all(
            (self.mod,),
            {},
            {self.mod.id: ReleaseChannel.PINNED},
            {self.mod.id: "1.0.0.0"},
        )[0]
        self.assertIsNone(check.selected_release)
        self.assertEqual(check.state, UpdateState.ERROR)
        self.assertIn("1.0.0.0", check.message)

    def test_reports_current_repository_through_status_callback(self) -> None:
        statuses: list[str] = []
        service = UpdateCheckService(FakeReleaseClient([release("1.0.0.0")]))

        service.check_all(
            (self.mod,),
            {},
            {self.mod.id: ReleaseChannel.STABLE},
            status=statuses.append,
        )

        self.assertEqual(len(statuses), 1)
        self.assertIn("1/1", statuses[0])
        self.assertIn(self.mod.name, statuses[0])
        self.assertIn(self.mod.repository, statuses[0])

    def test_unmanaged_original_can_be_replaced_even_when_version_is_higher(self) -> None:
        service = UpdateCheckService(FakeReleaseClient([release("1.0.0.0")]))
        local = self.local(
            "9.9.9.9",
            kind=LocalModKind.UNMANAGED_REPLACEABLE,
            author="Speedy, Miziuu",
        )

        check = service.check_all(
            (self.mod,),
            {self.mod.id: local},
            {self.mod.id: ReleaseChannel.STABLE},
        )[0]

        self.assertEqual(check.state, UpdateState.UNMANAGED_REPLACEABLE)
        self.assertIn("Speedy, Miziuu", check.message)

    def test_title_conflict_blocks_replacement(self) -> None:
        service = UpdateCheckService(FakeReleaseClient([release("2.0.0.0")]))
        local = self.local("1.0.0.0", kind=LocalModKind.ARCHIVE_CONFLICT)

        check = service.check_all(
            (self.mod,),
            {self.mod.id: local},
            {self.mod.id: ReleaseChannel.STABLE},
        )[0]

        self.assertEqual(check.state, UpdateState.ARCHIVE_CONFLICT)


if __name__ == "__main__":
    unittest.main()
