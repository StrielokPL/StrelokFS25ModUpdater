from __future__ import annotations

import unittest

from strelok_fs25_mod_updater.github_client import GitHubClient
from strelok_fs25_mod_updater.models import CatalogMod


class FixtureClient(GitHubClient):
    def __init__(self, releases):
        super().__init__()
        self.fixture_releases = releases

    def list_releases(self, _repository):
        return self.fixture_releases


def asset(name: str, *, digest: str | None = None) -> dict:
    value = {
        "name": name,
        "browser_download_url": f"https://github.com/example/repo/releases/download/v1/{name}",
        "size": 123,
    }
    if digest:
        value["digest"] = digest
    return value


class GitHubClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = CatalogMod(
            id="strelokpl.test",
            name="Test",
            archive_name="FS25_Test.zip",
            repository="StrielokPL/Test",
            asset_pattern="FS25_Test*.zip",
        )

    def test_release_asset_is_selected_instead_of_source_archives(self) -> None:
        client = FixtureClient(
            [
                {
                    "tag_name": "v1.2.3.4",
                    "name": "Stable",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-08-29T00:00:00Z",
                    "body": "Notes",
                    "assets": [
                        asset("FS25_Test-debug.zip"),
                        asset("FS25_Test.zip", digest="sha256:abc"),
                    ],
                }
            ]
        )
        releases = client.releases_for_mod(self.mod)
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0].asset_name, "FS25_Test.zip")
        self.assertEqual(releases[0].digest, "sha256:abc")

    def test_draft_and_release_without_asset_are_ignored(self) -> None:
        client = FixtureClient(
            [
                {
                    "tag_name": "v2.0.0.0",
                    "draft": True,
                    "assets": [asset("FS25_Test.zip")],
                },
                {
                    "tag_name": "v1.0.0.0",
                    "draft": False,
                    "assets": [],
                },
            ]
        )
        self.assertEqual(client.releases_for_mod(self.mod), [])

    def test_catalog_release_uses_highest_catalog_tag(self) -> None:
        client = FixtureClient(
            [
                {
                    "tag_name": "v0.1.0",
                    "draft": False,
                    "assets": [asset("StrelokFS25ModUpdater.exe")],
                },
                {
                    "tag_name": "catalog-v2",
                    "draft": False,
                    "published_at": "2026-08-29T00:00:00Z",
                    "assets": [asset("strelok-mod-catalog.json")],
                },
                {
                    "tag_name": "catalog-v5",
                    "draft": False,
                    "published_at": "2026-08-30T00:00:00Z",
                    "assets": [asset("strelok-mod-catalog.json")],
                },
            ]
        )
        release = client.latest_catalog_release("StrielokPL/Updater")
        self.assertIsNotNone(release)
        self.assertEqual(release.catalog_version, 5)


if __name__ == "__main__":
    unittest.main()

