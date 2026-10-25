"""Compatibility of original releases with one specific edit; no inferred game tests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from importlib.resources import files

from .kingmods import kingmods_url
from .versioning import ModVersion

# Community catalogs cannot supply or extend these trusted metadata locations.
EDIT_REPOSITORIES = {
    "kingmods.63913": "StrielokPL/Edit330Miziuu",
    "kingmods.61633": "StrielokPL/Edit355360Miziuu",
}


class CompatibilityState(str, Enum):
    SOURCE = "source"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


class Verification(str, Enum):
    VERIFIED = "verified"
    ESTIMATED = "estimated"


def parse_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[vV]?\d+(?:\.\d+){0,3}", value):
        raise ValueError(f"Nieprawidłowa wersja oryginału: {value!r}")
    return ModVersion.parse(value)


@dataclass(frozen=True)
class CompatibilityAssessment:
    version: str
    state: CompatibilityState
    verification: Verification | None = None
    notes: str = ""

    @property
    def label(self):
        if self.state is CompatibilityState.SOURCE:
            return "Źródłowa — zalecana"
        if self.state is CompatibilityState.INCOMPATIBLE:
            return "Niekompatybilna"
        if self.verification is Verification.VERIFIED:
            return "Kompatybilna — sprawdzona"
        return "Kompatybilna — oszacowana"

    @property
    def notice(self):
        if self.state is CompatibilityState.SOURCE:
            return "Wersja źródłowa jest zalecaną bazą tego editu."
        if self.state is CompatibilityState.INCOMPATIBLE:
            return (
                "Wykryto niezgodność z tym editem. Zastosowanie zmian może spowodować "
                "błędy lub nieprawidłowy wygląd i działanie moda. " + self.notes
            )
        confidence = (
            "Działanie editu na tej wersji zostało potwierdzone."
            if self.verification is Verification.VERIFIED
            else "Zgodność oszacowano na podstawie porównania zmian; wymaga próby w grze."
        )
        return (
            confidence + " Nowe elementy oryginału mogą zostać nadpisane, pominięte albo "
            "działać inaczej niż w oryginale. Nadal zalecana jest wersja źródłowa. " + self.notes
        )


@dataclass(frozen=True)
class EditCompatibility:
    repository: str
    edit_id: str
    edit_version: str
    kingmods_id: str
    source_version: str
    source_xml_version: str
    compatible: tuple[CompatibilityAssessment, ...] = ()
    incompatible_from: str | None = None
    incompatible_versions: tuple[str, ...] = ()
    incompatibility_reason: str = ""

    @classmethod
    def from_manifest(cls, manifest, repository):
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            raise ValueError("Nieobsługiwany schemat metadanych editu")
        base = manifest.get("baseMod")
        if not isinstance(base, dict):
            raise ValueError("Brak opisu bazy editu")
        url = kingmods_url(base.get("kingmodsUrl", ""))
        kingmods_id = "kingmods." + url.split("/")[6]
        if EDIT_REPOSITORIES.get(kingmods_id) != repository:
            raise ValueError("Metadane editu nie odpowiadają zaufanemu modowi i repozytorium")
        source = base.get("version")
        source_parsed = parse_version(source)
        xml = base.get("modDescVersion", source)
        parse_version(xml)
        threshold = base.get("incompatibleFrom")
        if threshold is not None and parse_version(threshold) <= source_parsed:
            raise ValueError("Granica niezgodności musi być nowsza od wersji źródłowej")
        incompatible = base.get("incompatibleVersions", [])
        compatible = base.get("compatibleVersions", [])
        if (
            not isinstance(compatible, list)
            or not isinstance(incompatible, list)
            or len(compatible) > 200
            or len(incompatible) > 200
        ):
            raise ValueError("Nieprawidłowa lista ocen wersji")
        excluded = [parse_version(v) for v in incompatible]
        if source_parsed in excluded:
            raise ValueError("Wersja źródłowa nie może być niekompatybilna")
        result, seen = [], []
        for entry in compatible:
            # Legacy strings never count as a confirmed game test.
            if isinstance(entry, str):
                entry = {"version": entry, "verification": "estimated"}
            if not isinstance(entry, dict):
                raise ValueError("Nieprawidłowy wpis zgodności")
            version = entry.get("version")
            parsed = parse_version(version)
            verification = Verification(entry.get("verification", "estimated"))
            if (
                parsed == source_parsed
                or parsed in seen
                or parsed in excluded
                or (threshold and parsed >= parse_version(threshold))
            ):
                raise ValueError("Sprzeczne lub powielone oceny zgodności")
            notes = entry.get("notes", "")
            if not isinstance(notes, str) or len(notes) > 4000:
                raise ValueError("Nieprawidłowy opis oceny")
            result.append(
                CompatibilityAssessment(version, CompatibilityState.COMPATIBLE, verification, notes)
            )
            seen.append(parsed)
        edit_id, edit_version = manifest.get("id", ""), manifest.get("version", "")
        reason = base.get("incompatibilityReason", "")
        if (
            not isinstance(edit_id, str)
            or not edit_id
            or not isinstance(edit_version, str)
            or not edit_version
            or not isinstance(reason, str)
            or len(reason) > 4000
        ):
            raise ValueError("Nieprawidłowa identyfikacja lub opis editu")
        return cls(
            repository,
            edit_id,
            edit_version,
            kingmods_id,
            source,
            xml,
            tuple(result),
            threshold,
            tuple(incompatible),
            reason,
        )

    def assess(self, version):
        parsed = parse_version(version)
        if parsed == parse_version(self.source_version):
            return CompatibilityAssessment(version, CompatibilityState.SOURCE)
        if (self.incompatible_from and parsed >= parse_version(self.incompatible_from)) or any(
            parsed == parse_version(v) for v in self.incompatible_versions
        ):
            return CompatibilityAssessment(
                version, CompatibilityState.INCOMPATIBLE, notes=self.incompatibility_reason
            )
        return next(
            (entry for entry in self.compatible if parse_version(entry.version) == parsed), None
        )


def bundled_profiles():
    data = json.loads(
        files("strelok_fs25_mod_updater")
        .joinpath("resources/edit_compatibility.json")
        .read_text(encoding="utf-8")
    )
    result = {}
    for repository, manifest in data.items():
        profile = EditCompatibility.from_manifest(manifest, repository)
        result[profile.kingmods_id] = profile
    return result
