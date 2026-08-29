from __future__ import annotations

import unittest

from strelok_fs25_mod_updater.models import (
    CatalogMod,
    LocalMod,
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

    def local(self, version: str) -> LocalMod:
        return LocalMod(
            mod_id=self.mod.id,
            path=__import__("pathlib").Path("FS25_Test.zip"),
            version_text=version,
            version=ModVersion.parse(version),
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


if __name__ == "__main__":
    unittest.main()

