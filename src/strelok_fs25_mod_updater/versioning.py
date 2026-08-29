from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering


_VERSION_RE = re.compile(
    r"^[vV]?(?P<numbers>\d+(?:\.\d+){0,3})(?P<suffix>.*)$"
)
_TOKEN_RE = re.compile(r"\d+|[a-zA-Z]+")


@total_ordering
@dataclass(frozen=True)
class ModVersion:
    """Comparable FS-style version, including four-number versions and test suffixes."""

    raw: str
    numbers: tuple[int, int, int, int]
    suffix: str = ""

    @classmethod
    def parse(cls, value: str) -> "ModVersion":
        raw = value.strip()
        match = _VERSION_RE.match(raw)
        if not match:
            raise ValueError(f"Nieobsługiwany numer wersji: {value!r}")

        parts = [int(item) for item in match.group("numbers").split(".")]
        parts.extend([0] * (4 - len(parts)))
        suffix = match.group("suffix").strip("-_. ").lower()
        return cls(raw=raw, numbers=tuple(parts), suffix=suffix)  # type: ignore[arg-type]

    @classmethod
    def try_parse(cls, value: str | None) -> "ModVersion | None":
        if not value:
            return None
        try:
            return cls.parse(value)
        except ValueError:
            return None

    def _suffix_key(self) -> tuple[int, tuple[tuple[int, int | str], ...]]:
        if not self.suffix:
            return (1, ())
        tokens: list[tuple[int, int | str]] = []
        for token in _TOKEN_RE.findall(self.suffix):
            if token.isdigit():
                tokens.append((1, int(token)))
            else:
                tokens.append((0, token.lower()))
        return (0, tuple(tokens))

    def _key(self) -> tuple[tuple[int, int, int, int], object]:
        return (self.numbers, self._suffix_key())

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ModVersion):
            return NotImplemented
        return self._key() < other._key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModVersion):
            return False
        return self._key() == other._key()

    def __str__(self) -> str:
        return self.raw


def is_newer(candidate: str, installed: str) -> bool:
    return ModVersion.parse(candidate) > ModVersion.parse(installed)

