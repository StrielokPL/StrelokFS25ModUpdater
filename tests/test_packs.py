import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from strelok_fs25_mod_updater.installer import ModInstaller
from strelok_fs25_mod_updater.kingmods import (
    KingMod,
    KingModsClient,
    _SafeRedirect,
)
from strelok_fs25_mod_updater.packs import (
    MIZIUU_LIST,
    OWN_LIST,
    PUBLIC_URSUS,
    GitHubMod,
    ModPack,
    PackStore,
    pack_source,
    parse_pack,
    trusted_source,
)
from strelok_fs25_mod_updater.storage import HistoryStore
from tests.helpers import make_mod_zip

KM = "https://www.kingmods.net/en/fs25/mods/63913/ursus-c-330330m"
MF = "https://modsfire.com/xnKLKu6d2U89Ej4"


class PackTests(unittest.TestCase):
    def test_simple_format_name_comments_bom_and_both_sources(self):
        name, mods = parse_pack("\ufeffMiziuu\n\n# komentarz\n" + KM + "\n" + MF)
        self.assertEqual(name, "Miziuu")
        self.assertEqual(len(mods), 2)
        self.assertEqual(mods[1].id, "modsfire.xnKLKu6d2U89Ej4")
        name, mods = parse_pack(json.dumps({"name": "Moja paczka", "mods": [KM, MF]}))
        self.assertEqual(name, "Moja paczka")
        self.assertEqual(len(mods), 2)

    def test_spoofed_and_external_addresses_rejected_atomically(self):
        bad = [
            "https://example.com/mod.zip",
            "http://modsfire.com/abc",
            "https://modsfire.com.evil.org/abc",
            "https://modsfire.com@evil.org/abc",
            "https://evil.org@modsfire.com/abc",
            "https://modsfire.com:8080/abc",
            "https://modsfire.com/abc?redirect=https://evil.org",
            "https://modsfire.com/abc#https://evil.org",
            "file:///tmp/mod.zip",
            "javascript:alert(1)",
            "https://www.kingmods.net/redirect",
            "https://github.com/StrielokPL/Ursus16541954",
        ]
        for link in bad:
            with self.subTest(link=link), self.assertRaises(ValueError):
                parse_pack("StrielokPL\n" + KM + "\n" + link)

    def test_source_identity_not_content_grants_github_exception(self):
        contents = "StrielokPL\n" + PUBLIC_URSUS.url
        name, mods = parse_pack(contents, source=OWN_LIST)
        self.assertIsInstance(mods[0], GitHubMod)
        for source in [
            "",
            MIZIUU_LIST,
            OWN_LIST.replace("StrielokPLModList", "StrielokPLModList-copy"),
            OWN_LIST.replace("/HEAD/", "/untrusted/"),
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_pack(contents, source=source)
        with self.assertRaises(ValueError):
            parse_pack("StrielokPL\nhttps://github.com/other/mod", source=OWN_LIST)
        self.assertFalse(
            trusted_source("https://evil.org/StrielokPL/StrielokPLModList/HEAD/mods.txt")
        )

    def test_repo_shortcut_and_bad_source_urls(self):
        self.assertEqual(pack_source("https://github.com/StrielokPL/MiziuuModList"), MIZIUU_LIST)
        self.assertEqual(
            pack_source("https://github.com/user/repo/blob/main/mods.txt"),
            "https://raw.githubusercontent.com/user/repo/main/mods.txt",
        )
        for source in [
            "file:///etc/passwd",
            "https://github.com.evil/user/repo",
            "https://user@github.com/user/repo",
            "https://github.com/user/repo?redirect=evil",
        ]:
            with self.assertRaises(ValueError):
                pack_source(source)

    def test_redirects_cannot_escape_allowlist(self):
        req = urllib.request.Request(MF)
        for target in [
            "https://evil.org/file",
            "http://modsfire.com/abc",
            "https://modsfire.com:8080/abc",
            "https://modsfire.com/redirect?to=evil",
        ]:
            with self.assertRaises(ValueError):
                _SafeRedirect().redirect_request(req, None, 302, "", {}, target)

    def test_network_read_rejects_external_url_before_request(self):
        with patch("urllib.request.build_opener") as opener, self.assertRaises(ValueError):
            KingModsClient().read("https://evil.org/mods.txt")
        opener.assert_not_called()

    def test_independent_pack_storage_and_removed_defaults_do_not_return(self):
        with tempfile.TemporaryDirectory() as d:
            store = PackStore(Path(d) / "packs.json")
            packs = store.load()
            self.assertEqual([p.name for p in packs], ["Miziuu", "StrielokPL"])
            file = Path(d) / "my.txt"
            file.write_text("Własna paczka\n" + MF, encoding="utf-8")
            packs.append(ModPack(str(file), "Własna paczka", [KingMod(MF)], local=True))
            store.save(packs)
            loaded = store.load()
            self.assertEqual([p.id for p in packs], [p.id for p in loaded])
            self.assertIsInstance(loaded[1].mods[0], GitHubMod)
            self.assertEqual(loaded[2].parse(loaded[2].load_text(None))[0], "Własna paczka")
            store.save([])
            self.assertEqual(store.load(), [])

    def test_updated_list_can_rename_remove_and_be_empty(self):
        self.assertEqual(parse_pack("Nowa nazwa\n"), ("Nowa nazwa", []))
        with self.assertRaises(ValueError):
            parse_pack("")
        with self.assertRaises(ValueError):
            parse_pack("A" * 81 + "\n" + KM)

    def test_direct_modsfire_has_unknown_version_until_zip(self):
        client = KingModsClient()
        with patch.object(client, "read", return_value="<h3>FS25_Test.zip</h3>"):
            mod, page = client.fetch(KingMod(MF))
        self.assertEqual(mod.archive, "FS25_Test.zip")
        self.assertEqual(page.releases[0].version, "")
        with (
            tempfile.TemporaryDirectory() as d,
            patch("strelok_fs25_mod_updater.installer.is_fs25_running", return_value=False),
        ):
            root = Path(d)
            folder = root / "mods"
            folder.mkdir()
            source = make_mod_zip(root / "FS25_Test.zip", "2.3.4.5")
            installer = ModInstaller(None, HistoryStore(root / "history.json"), root / "backups")
            event = installer.install_local(mod, "", source, folder, backup=False)
            self.assertEqual(event["version"], "2.3.4.5")
            self.assertTrue((folder / mod.archive).exists())
