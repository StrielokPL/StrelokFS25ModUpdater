"""Named mod lists. Trust comes from a built-in source identity, never list contents."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .kingmods import KingMod, KingModsError, github_list_url
from .models import CatalogMod
from .storage import atomic_write_json, config_dir, read_json

OWN_LIST = "https://raw.githubusercontent.com/StrielokPL/StrielokPLModList/HEAD/mods.txt"
MIZIUU_LIST = "https://raw.githubusercontent.com/StrielokPL/MiziuuModList/HEAD/mods.txt"
TRUSTED_REPOSITORY = "StrielokPL/Ursus16541954"
MAX_LIST_BYTES = 4 * 1024 * 1024


def pack_source(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise KingModsError("Podaj publiczne repozytorium GitHub albo plik TXT/JSON.")
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "github.com" and len(parts) == 2:
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
            raise KingModsError("Nieprawidłowy adres repozytorium.")
        return "https://raw.githubusercontent.com/" + "/".join(parts) + "/HEAD/mods.txt"
    return github_list_url(value)


def trusted_source(source: str) -> bool:
    # Exact official file, on default/main branch. Copies and similarly named lists are untrusted.
    try:
        source = pack_source(source)
    except ValueError:
        return False
    parts = urlsplit(source).path.strip("/").split("/")
    return (
        len(parts) == 4
        and [p.casefold() for p in parts[:2]] == ["strielokpl", "strielokplmodlist"]
        and parts[2] in {"HEAD", "main"}
        and parts[3] == "mods.txt"
    )


@dataclass(frozen=True)
class GitHubMod:
    catalog: CatalogMod

    @property
    def url(self):
        return "https://github.com/" + self.catalog.repository

    @property
    def id(self):
        return self.catalog.id

    @property
    def archive(self):
        return self.catalog.archive_name

    @property
    def name(self):
        return self.catalog.name

    @property
    def titles(self):
        return self.catalog.mod_desc_titles

    @property
    def edit_id(self):
        return ""


PUBLIC_URSUS = GitHubMod(
    CatalogMod(
        id="strelokpl.ursus16541954",
        name="Ursus 1654/1954 Pack",
        archive_name="FS25_Ursus_1654_1954_Pack.zip",
        repository=TRUSTED_REPOSITORY,
        asset_pattern="FS25_Ursus_1654_1954_Pack.zip",
        mod_desc_titles=("Ursus 1654-1954 Pack",),
    )
)


def parse_entry(entry, *, source=""):
    url = (
        entry if isinstance(entry, str) else entry.get("url", "") if isinstance(entry, dict) else ""
    )
    if not isinstance(url, str):
        raise KingModsError("Każdy wpis musi zawierać adres URL.")
    if url.rstrip("/").casefold() == PUBLIC_URSUS.url.casefold() and trusted_source(source):
        return PUBLIC_URSUS
    # No content-provided trust flag, repository, release URL, or name grants an exception.
    return KingMod.from_dict(entry)


def parse_pack(text: str, *, source: str = "", fallback_name: str = ""):
    if len(text.encode("utf-8")) > MAX_LIST_BYTES:
        raise KingModsError("Plik listy jest zbyt duży (maksymalnie 4 MB).")
    text = text.lstrip("\ufeff")
    if text.lstrip().startswith(("[", "{")):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise KingModsError("Nieprawidłowy JSON listy.") from exc
        name = data.get("name", fallback_name) if isinstance(data, dict) else fallback_name
        entries = data.get("mods") if isinstance(data, dict) else data
    else:
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if lines and not lines[0].startswith(("https:", "http:", "file:", "javascript:")):
            name, entries = lines[0], lines[1:]
        else:
            name, entries = fallback_name, lines
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or "\n" in name:
        raise KingModsError("Pierwszy wiersz musi zawierać nazwę zakładki (1–80 znaków).")
    if not isinstance(entries, list) or len(entries) > 200:
        raise KingModsError("Lista może zawierać maksymalnie 200 modów.")
    mods = {}
    for index, entry in enumerate(entries, 1):
        try:
            mod = parse_entry(entry, source=source)
        except (ValueError, TypeError) as exc:
            raise KingModsError(
                f"Wpis {index}: niedozwolony lub nieprawidłowy link. "
                "Obce paczki mogą zawierać tylko strony KingMods i ModsFire przez HTTPS."
            ) from exc
        mods[mod.id] = mod
    return name.strip(), list(mods.values())


@dataclass
class ModPack:
    source: str
    name: str
    mods: list = field(default_factory=list)
    local: bool = False
    watch: bool = True

    @property
    def id(self):
        identity = ("file:" if self.local else "url:") + self.source
        return hashlib.sha256(identity.encode()).hexdigest()[:20]

    def load_text(self, client):
        if self.local:
            with Path(self.source).open("rb") as handle:
                raw = handle.read(MAX_LIST_BYTES + 1)
            if len(raw) > MAX_LIST_BYTES:
                raise KingModsError("Plik listy jest zbyt duży.")
            return raw.decode("utf-8-sig")
        return client.read(pack_source(self.source))

    def parse(self, text):
        return parse_pack(text, source="" if self.local else self.source, fallback_name=self.name)

    def to_dict(self):
        return {
            "source": self.source,
            "name": self.name,
            "local": self.local,
            "watch": self.watch,
            "mods": [
                ({"url": m.url} if isinstance(m, GitHubMod) else asdict(m)) for m in self.mods
            ],
        }


class PackStore:
    def __init__(self, path=None):
        self.path = path or config_dir() / "packs.json"

    def load(self):
        raw = read_json(self.path, None)
        if raw is None:
            # Seed only the two requested lists. Legacy observations migrate to a separate tab.
            packs = [
                ModPack(MIZIUU_LIST, "Miziuu"),
                ModPack(OWN_LIST, "StrielokPL", [PUBLIC_URSUS]),
            ]
            legacy = read_json(self.path.parent / "kingmods.json", {})
            if isinstance(legacy, dict) and legacy.get("mods"):
                try:
                    mods = [KingMod.from_dict(m) for m in legacy["mods"]]
                    path = self.path.parent / "moje-obserwowane.json"
                    atomic_write_json(
                        path, {"name": "Moje obserwowane", "mods": [asdict(m) for m in mods]}
                    )
                    if legacy.get("feed"):
                        packs.append(ModPack(pack_source(legacy["feed"]), "Moje obserwowane", mods))
                    else:
                        packs.append(ModPack(str(path), "Moje obserwowane", mods, local=True))
                except (ValueError, TypeError):
                    logging.getLogger(__name__).warning("Nie można przenieść starej listy KingMods")
            self.save(packs)
            return packs
        packs = []
        if not isinstance(raw, list):
            raise KingModsError("Uszkodzony plik packs.json. Zachowano go do odzyskania.")
        for item in raw:
            try:
                local = item.get("local") is True
                source = str(item["source"]) if local else pack_source(item["source"])
                name, mods = parse_pack(
                    json.dumps({"name": item["name"], "mods": item["mods"]}),
                    source="" if local else source,
                )
                packs.append(ModPack(source, name, mods, local, bool(item.get("watch", True))))
            except (ValueError, TypeError, KeyError) as exc:
                logging.getLogger(__name__).warning("Pominięto uszkodzoną listę: %s", exc)
        return packs

    def save(self, packs):
        atomic_write_json(self.path, [pack.to_dict() for pack in packs])
