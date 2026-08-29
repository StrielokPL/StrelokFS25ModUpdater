from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from strelok_fs25_mod_updater.models import ReleaseChannel
from strelok_fs25_mod_updater.storage import AppSettings, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def test_pinned_version_is_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            settings = AppSettings()
            settings.set_pinned_version("strelokpl.test", "1.2.0.0-P1")
            store.save(settings)

            loaded = store.load()
            self.assertEqual(
                loaded.channel_for("strelokpl.test"),
                ReleaseChannel.PINNED,
            )
            self.assertEqual(
                loaded.pinned_version_for("strelokpl.test"),
                "1.2.0.0-P1",
            )

    def test_changing_back_to_channel_clears_pinned_version(self) -> None:
        settings = AppSettings()
        settings.set_pinned_version("strelokpl.test", "1.0.0.0")
        settings.set_channel("strelokpl.test", ReleaseChannel.STABLE)
        settings.clear_pinned_version("strelokpl.test")

        self.assertEqual(
            settings.channel_for("strelokpl.test"),
            ReleaseChannel.STABLE,
        )
        self.assertEqual(settings.pinned_version_for("strelokpl.test"), "")


if __name__ == "__main__":
    unittest.main()
