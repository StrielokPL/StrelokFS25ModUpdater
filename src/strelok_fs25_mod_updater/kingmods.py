"""Public KingMods watch list. Download pages are opened in the user's browser."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path

from . import __version__
from .storage import atomic_write_json, config_dir, read_json
from .versioning import ModVersion


class KingModsError(ValueError):
    pass


def kingmods_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"kingmods.net", "www.kingmods.net"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not re.fullmatch(r"/[a-z]{2}/fs25/mods/\d+/[a-zA-Z0-9_-]+/?", parsed.path)
    ):
        raise KingModsError(
            "Podaj adres strony moda FS25 na KingMods (https://www.kingmods.net/…)."
        )
    return "https://www.kingmods.net" + parsed.path.rstrip("/")


def modsfire_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"modsfire.com", "www.modsfire.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path)
    ):
        raise KingModsError("Nieprawidłowy adres pliku ModsFire.")
    return "https://modsfire.com" + parsed.path.rstrip("/")


def archive_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.zip", value, re.I) or value.startswith("."):
        raise KingModsError("Nazwa archiwum musi być nazwą ZIP bez ścieżki i spacji.")
    return value


@dataclass(frozen=True)
class KingMod:
    url: str
    name: str = ""
    archive: str = ""
    titles: tuple[str, ...] = ()
    edit_id: str = ""

    def __post_init__(self):
        object.__setattr__(self, "url", kingmods_url(self.url))
        if self.archive:
            archive_name(self.archive)
        if self.edit_id and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", self.edit_id):
            raise KingModsError("Nieprawidłowy identyfikator editu.")
        if not isinstance(self.titles, (tuple, list)) or any(
            not isinstance(t, str) or not t.strip() for t in self.titles
        ):
            raise KingModsError("titles musi być listą tytułów z modDesc.xml.")

    @property
    def id(self) -> str:
        return "kingmods." + self.url.split("/")[6]

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, str):
            return cls(data)
        if not isinstance(data, dict):
            raise KingModsError("Wpis katalogu musi być linkiem lub obiektem JSON.")
        return cls(
            url=str(data.get("url", "")),
            name=str(data.get("name", "")),
            archive=str(data.get("archive", data.get("archiveName", ""))),
            titles=data.get("titles", data.get("modDescTitles", [])),
            edit_id=str(data.get("edit_id", data.get("editId", ""))),
        )


@dataclass(frozen=True)
class KingRelease:
    version: str
    url: str


@dataclass
class KingPage:
    name: str
    releases: list[KingRelease] = field(default_factory=list)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = ""
        self.anchor_text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.heading = False
        self.name: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.anchor_text = []
        if tag == "h1":
            self.heading = True

    def handle_data(self, data):
        self.text.append(data)
        if self.href:
            self.anchor_text.append(data)
        if self.heading:
            self.name.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.links.append((self.href, " ".join(self.anchor_text)))
            self.href = ""
        if tag == "h1":
            self.heading = False


def parse_page(html: str) -> KingPage:
    parser = _PageParser()
    parser.feed(html)
    releases: dict[str, KingRelease] = {}
    for url, label in parser.links:
        try:
            url = modsfire_url(url)
        except ValueError:
            continue
        match = re.search(r"\b[Vv](\d+(?:\.\d+){1,3})\b", label)
        if match:
            version = match.group(1)
            if version in releases and releases[version].url != url:
                raise KingModsError(f"Niejednoznaczny link do wersji {version}. Otwórz KingMods.")
            releases[version] = KingRelease(version, url)
    if not releases:
        raise KingModsError("Nie znaleziono wersji z linkami ModsFire. Otwórz stronę KingMods.")
    return KingPage(
        " ".join(" ".join(parser.name).split()),
        sorted(releases.values(), key=lambda r: ModVersion.parse(r.version), reverse=True),
    )


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise KingModsError(
                "Serwer przekierował do innej domeny; otwórz stronę w przeglądarce."
            )
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise KingModsError("Odrzucono przekierowanie bez HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class KingModsClient:
    def __init__(self, timeout=20, cache_seconds=300):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self.cache: dict[str, tuple[float, str]] = {}

    def read(self, url: str) -> str:
        cached = self.cache.get(url)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"StrelokFS25ModUpdater/{__version__}",
                "Accept": "text/html,text/plain,application/json",
            },
        )
        try:
            with urllib.request.build_opener(_SafeRedirect()).open(
                request, timeout=self.timeout
            ) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise KingModsError("Odpowiedź serwera jest zbyt duża.")
                text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError, urllib.error.URLError) as exc:
            raise KingModsError(f"Nie udało się odczytać strony: {exc}") from exc
        self.cache[url] = (time.monotonic(), text)
        logging.getLogger(__name__).info("KINGMODS GET %s bytes=%d", url, len(raw))
        return text

    def fetch(self, mod: KingMod) -> tuple[KingMod, KingPage]:
        page = parse_page(self.read(kingmods_url(mod.url)))
        name = mod.archive
        if not name:
            parser = _PageParser()
            parser.feed(self.read(modsfire_url(page.releases[0].url)))
            names = re.findall(r"\b(FS25_[A-Za-z0-9_-]+\.zip)\b", " ".join(parser.text), re.I)
            if not names:
                raise KingModsError(
                    "Nie odczytano nazwy ZIP z ModsFire. Uzupełnij archiveName w katalogu."
                )
            name = archive_name(names[0])
        return replace(mod, name=mod.name or page.name, archive=name), page


def github_list_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise KingModsError("Podaj publiczny plik TXT lub JSON na GitHubie.")
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "github.com" and len(parts) >= 5 and parts[2] == "blob":
        parts.pop(2)
    elif parsed.hostname != "raw.githubusercontent.com" or len(parts) < 4:
        raise KingModsError("Podaj link do pliku GitHub (blob) lub raw.githubusercontent.com.")
    if not parts[-1].lower().endswith((".txt", ".json")) or any(
        p in {"", ".", ".."} for p in parts
    ):
        raise KingModsError("Katalog musi być plikiem TXT lub JSON.")
    return "https://raw.githubusercontent.com/" + "/".join(parts)


def parse_watch_list(text: str) -> list[KingMod]:
    if text.lstrip().startswith(("[", "{")):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise KingModsError("Nieprawidłowy JSON katalogu.") from exc
        entries = data.get("mods") if isinstance(data, dict) else data
    else:
        entries = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    if not isinstance(entries, list) or len(entries) > 200:
        raise KingModsError("Katalog musi zawierać listę maksymalnie 200 modów.")
    result = {}
    for entry in entries:
        mod = KingMod.from_dict(entry)
        result[mod.id] = mod
    return list(result.values())


DEFAULT_MODS = (
    KingMod(
        "https://www.kingmods.net/pl/fs25/mods/63913/ursus-c-330330m",
        "Ursus C-330/330M",
        "FS25_UrsusC330_330M_4x2.zip",
        ("Ursus C-330/330M",),
        "strelokpl.ursus330fs25",
    ),
    KingMod(
        "https://www.kingmods.net/pl/fs25/mods/61633/ursus-c355-c360-pack",
        "Ursus C355-C360 Pack",
        "FS25_UrsusC355xC360Pack.zip",
        ("Ursus C355-C360 Pack",),
        "strelokpl.ursus355360",
    ),
)


class KingModsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "kingmods.json"

    def load(self) -> tuple[list[KingMod], str]:
        raw = read_json(self.path, None)
        if raw is None:
            return list(DEFAULT_MODS), ""
        if not isinstance(raw, dict):
            return list(DEFAULT_MODS), ""
        result = []
        for item in raw.get("mods", []):
            try:
                result.append(KingMod.from_dict(item))
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("Pominięto nieprawidłowy wpis KingMods")
        return result, str(raw.get("feed", ""))

    def save(self, mods: list[KingMod], feed: str = "") -> None:
        atomic_write_json(self.path, {"mods": [asdict(m) for m in mods], "feed": feed})
