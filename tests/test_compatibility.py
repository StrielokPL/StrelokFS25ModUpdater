import copy
import io
import json
import unittest
from unittest.mock import patch

from strelok_fs25_mod_updater.compatibility import (
    CompatibilityState,
    EditCompatibility,
    Verification,
    bundled_profiles,
)
from strelok_fs25_mod_updater.github_client import GitHubClient, GitHubError

REPO = "StrielokPL/Edit330Miziuu"
MANIFEST = {
    "schemaVersion": 1,
    "id": "edit330miziuu",
    "version": "0.0.5.1",
    "baseMod": {
        "kingmodsUrl": "https://www.kingmods.net/en/fs25/mods/63913/ursus-c-330330m",
        "version": "1.1.2.0",
        "modDescVersion": "1.1.2.0",
        "compatibleVersions": [
            {"version": "1.1.2.1", "verification": "verified", "notes": "Próba SP."},
            {"version": "1.9.0.0", "verification": "estimated", "notes": "Porównano pliki."},
        ],
        "incompatibleFrom": "1.9.1.0",
        "incompatibleVersions": ["1.0.0.0"],
        "incompatibilityReason": "Zmienione identyfikatory geometrii.",
    },
}


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.profile = EditCompatibility.from_manifest(MANIFEST, REPO)

    def test_source_is_recommended_not_a_claim_about_game_testing(self):
        assessment = self.profile.assess("v1.1.2")
        self.assertEqual(assessment.state, CompatibilityState.SOURCE)
        self.assertIsNone(assessment.verification)
        self.assertIn("zalecana", assessment.label)

    def test_explicit_verified_and_estimated_are_distinct_and_warn_about_new_features(self):
        verified = self.profile.assess("1.1.2.1")
        estimated = self.profile.assess("1.9.0.0")
        self.assertEqual(verified.verification, Verification.VERIFIED)
        self.assertEqual(estimated.verification, Verification.ESTIMATED)
        self.assertIn("sprawdzona", verified.label)
        self.assertIn("oszacowana", estimated.label)
        for assessment in [verified, estimated]:
            self.assertIn("Nowe elementy oryginału", assessment.notice)
            self.assertIn("zalecana jest wersja źródłowa", assessment.notice)

    def test_threshold_covers_unlisted_future_versions_with_numeric_comparison(self):
        for version in ["1.9.1.0", "1.9.1.1", "1.10.0.0", "2.0.0.0", "99.0"]:
            self.assertEqual(self.profile.assess(version).state, CompatibilityState.INCOMPATIBLE)
        self.assertEqual(self.profile.assess("1.0.0.0").state, CompatibilityState.INCOMPATIBLE)

    def test_unassessed_is_not_automatically_compatible(self):
        self.assertIsNone(self.profile.assess("1.1.1.0"))
        self.assertIsNone(self.profile.assess("1.8.0.0"))

    def test_conflicting_or_duplicate_claims_are_rejected(self):
        for extra in [
            {"version": "1.10.0.0", "verification": "verified"},
            {"version": "1.1.2", "verification": "verified"},
            {"version": "1.1.2.1", "verification": "estimated"},
            {"version": "1.0.0.0", "verification": "estimated"},
            {"version": "1.5.0.0", "verification": "invented"},
        ]:
            data = copy.deepcopy(MANIFEST)
            data["baseMod"]["compatibleVersions"].append(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                EditCompatibility.from_manifest(data, REPO)

    def test_legacy_plain_versions_only_count_as_estimated(self):
        data = copy.deepcopy(MANIFEST)
        data["baseMod"]["compatibleVersions"] = ["1.1.2.1"]
        self.assertEqual(
            EditCompatibility.from_manifest(data, REPO).assess("1.1.2.1").verification,
            Verification.ESTIMATED,
        )

    def test_official_c330_cutoff_and_separate_c355_website_and_xml_versions(self):
        profiles = bundled_profiles()
        c330 = profiles["kingmods.63913"]
        self.assertIsNone(c330.assess("1.9.0.0"))
        self.assertEqual(c330.assess("1.9.1.0").state, CompatibilityState.INCOMPATIBLE)
        c355 = profiles["kingmods.61633"]
        self.assertEqual(c355.source_xml_version, "2.0.3.0")
        self.assertEqual(c355.assess("2.0.4.0").state, CompatibilityState.SOURCE)
        self.assertIsNone(c355.assess("2.0.3.0"))

    def test_metadata_cannot_rebind_an_edit_to_another_mod_or_repository(self):
        with self.assertRaises(ValueError):
            EditCompatibility.from_manifest(MANIFEST, "other/metadata")
        data = copy.deepcopy(MANIFEST)
        data["baseMod"]["kingmodsUrl"] = "https://evil.org/mod"
        with self.assertRaises(ValueError):
            EditCompatibility.from_manifest(data, REPO)

    def test_network_metadata_is_bounded_and_only_read_from_built_in_repos(self):
        client = GitHubClient()
        with patch.object(client, "_request") as request, self.assertRaises(GitHubError):
            client.edit_manifest("other/metadata")
        request.assert_not_called()
        with patch.object(
            client, "_request", return_value=io.BytesIO(json.dumps(MANIFEST).encode())
        ):
            self.assertEqual(client.edit_manifest(REPO), MANIFEST)
        client._cache.clear()
        with (
            patch.object(client, "_request", return_value=io.BytesIO(b"X" * (512 * 1024 + 1))),
            self.assertRaises(GitHubError),
        ):
            client.edit_manifest(REPO)
